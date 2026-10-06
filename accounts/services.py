import logging

from django.db import IntegrityError, transaction
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError, PermissionDenied
from .models import EmailOTP,WorkspaceMembership, Workspace, Project, Task, Notification,AuditRecord,CreditUsage,IdempotencyKey
import hashlib

User = get_user_model()

logger = logging.getLogger(__name__)


def _raise_constraint_validation_error(error, constraint_name, message):
    cause = error.__cause__
    database_constraint = getattr(getattr(cause, "diag", None), "constraint_name", None)
    if database_constraint is None and cause is not None:
        database_constraint = str(cause)

    database_error = str(database_constraint)
    sqlite_markers = {
        "unique_workspace_membership": (
            "accounts_workspacemembership.workspace_id",
            "accounts_workspacemembership.user_id",
        ),
        "credit_balance_non_negative": ("credit_balance",),
    }
    markers = sqlite_markers.get(constraint_name, ())
    matches_constraint = constraint_name in database_error or (
        bool(markers) and all(marker in database_error for marker in markers)
    )
    if not matches_constraint:
        raise error

    raise ValidationError({"detail": message}) from error


def send_otp_email(email, first_name, otp_code, purpose):
    """
    Sends OTP email using Brevo transactional API.
    """
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = settings.BREVO_API_KEY

    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    subject = "Verify your email" if purpose == "signup" else "Confirm your new email"
    html_content = f"""
    <p>Hi {first_name},</p>
    <p>Your OTP code is: <strong>{otp_code}</strong></p>
    <p>This code expires in 10 minutes.</p>
    """
    sender = {"name": "Your App", "email": settings.DEFAULT_FROM_EMAIL}
    to = [{"email": email}]
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=to, sender=sender, subject=subject, html_content=html_content
    )

    try:
        api_instance.send_transac_email(send_smtp_email)
    except ApiException as e:
        logger.error(f"Failed to send OTP email to {email}: {e}")


def signup_user(serializer):
    """
    Saves a new (inactive) user, generates a signup OTP, and emails it.
    Rolls back the user if the email fails to send.
    """
    user = serializer.save()
    otp = EmailOTP.generate_otp(user, 'signup')
    try:
        send_otp_email(user.email, user.first_name, otp.otp_code, 'signup')
    except Exception:
        user.delete()
        raise ValidationError({"detail": "Unable to send OTP email. Please try again later."})
    return user


def verify_signup_otp(email, otp_code):
    """
    Verifies a signup OTP and activates the corresponding user.
    Raises ValidationError on any failure case.
    """
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        raise ValidationError({"detail": "Invalid email."})

    try:
        otp = EmailOTP.objects.get(user=user, purpose='signup', is_verified=False)
    except EmailOTP.DoesNotExist:
        raise ValidationError({"detail": "No OTP found or already verified."})

    if otp.is_expired():
        otp.delete()
        raise ValidationError({"detail": "OTP expired. Please sign up again."})

    if otp.otp_code != otp_code:
        raise ValidationError({"detail": "Invalid OTP."})

    otp.is_verified = True
    otp.save()
    user.is_active = True
    user.is_email_verified = True
    user.save()
    return user


def initiate_email_update(user, new_email):
    """
    Generates an email-update OTP and sends it to the new address.
    Rolls back the OTP if the email fails to send.
    """
    otp = EmailOTP.generate_otp(user, 'email_update', new_email=new_email)
    try:
        send_otp_email(new_email, user.first_name, otp.otp_code, 'email_update')
    except Exception:
        otp.delete()
        raise ValidationError({"detail": "Unable to send OTP email to the new address. Please try again later."})
    return otp


def verify_email_update(user, otp_code):
    """
    Verifies an email-update OTP and applies the new email to the user.
    Raises ValidationError on any failure case.
    """
    try:
        otp = EmailOTP.objects.get(user=user, purpose='email_update', is_verified=False)
    except EmailOTP.DoesNotExist:
        raise ValidationError({"detail": "No pending email update OTP."})

    if otp.is_expired():
        otp.delete()
        raise ValidationError({"detail": "OTP expired. Please request a new one."})

    if otp.otp_code != otp_code:
        raise ValidationError({"detail": "Invalid OTP."})

    user.email = otp.new_email
    user.save()
    otp.is_verified = True
    otp.save()
    return user


def delete_user_account(user, password):
    """
    Deletes the given user's account after verifying their password.
    Raises ValidationError if the password is incorrect.
    """
    if not user.check_password(password):
        raise ValidationError({"detail": "Incorrect password."})
    user.delete()

class WorkspaceService:

    @staticmethod
    def create_workspace(user, validated_data):
        workspace = Workspace.objects.create(**validated_data)
        WorkspaceMembership.objects.create(
            user=user,
            workspace=workspace,
            role=WorkspaceMembership.RoleType.OWNER,
        )

        notification = NotificationService.create(
            recipient=user,
            notification_type=Notification.NotificationType.WORKSPACE_CREATED,
            payload={
                "workspace_id": workspace.id,
                "workspace_name": workspace.name,
            },
            deduplication_key=f"workspace_created:{workspace.id}:{user.id}",
        )

        from accounts.tasks import send_notification_email
        send_notification_email(notification.id)

        return workspace
    @staticmethod
    def add_member(invited_by, validated_data):
        """
        Creates a new WorkspaceMembership and notifies the invited user.
        `validated_data` comes straight from WorkspaceMembershipSerializer —
        expected to contain `user`, `workspace`, and `role`.
        """
        try:
            with transaction.atomic():
                membership = WorkspaceMembership.objects.create(**validated_data)
        except IntegrityError as error:
            _raise_constraint_validation_error(
                error,
                "unique_workspace_membership",
                "This user is already a member of the workspace.",
            )

        notification = NotificationService.create(
            recipient=membership.user,
            notification_type=Notification.NotificationType.WORKSPACE_INVITE,
            payload={
                "workspace_name": membership.workspace.name,
                "invited_by": invited_by.first_name,
            },
        )
        from accounts.tasks import send_notification_email
        send_notification_email(notification.id)

        return membership


class ProjectService:

    @staticmethod
    @transaction.atomic
    def create_project(user, validated_data):
        workspace = validated_data["workspace"]

        use_credits(
            workspace=workspace,
            user=user,
            amount=5,
        )

        return Project.objects.create(
            created_by=user,
            **validated_data
        )


class TaskService:

    @staticmethod
    @transaction.atomic
    def create_task(user, validated_data):
        project = validated_data["project"]
        assigned_to = validated_data.get("assigned_to")

        if assigned_to:
            use_credits(
                workspace=project.workspace,
                user=user,
                amount=3,
            )

        try:
            task = Task.objects.create(
                created_by=user,
                **validated_data
            )
        except IntegrityError as error:
            _raise_constraint_validation_error(
                error,
                "valid_task_status",
                "The requested task status is invalid.",
            )

        if task.assigned_to_id:
            notification = NotificationService.create(
                recipient=task.assigned_to,
                notification_type=Notification.NotificationType.TASK_ASSIGNED,
                payload={"task_title": task.title},
            )

            from accounts.tasks import send_notification_email
            send_notification_email(notification.id)

        return task

    @staticmethod
    def transition(task, action_name, user):
        if action_name in ("approve", "reject") and task.assigned_to_id == user.id:
            raise PermissionDenied(
                f"You cannot {action_name} a task assigned to yourself."
            )

        if not task.can_transition(action_name):
            raise ValidationError(
                f"Cannot '{action_name}' a task in status '{task.status}'."
            )

        task.apply_transition(action_name)

        if action_name == "approve":
            notification = NotificationService.create(
                recipient=task.assigned_to,
                notification_type=Notification.NotificationType.TASK_APPROVED,
                payload={"task_title": task.title, "approved_by": user.first_name},
            )
            from accounts.tasks import send_notification_email
            send_notification_email(notification.id)

        return task
    
   

class NotificationService:


    @staticmethod
    def create(
        *,
        recipient,
        notification_type: str,
        payload: dict,
        deduplication_key: str | None = None,
    ) -> Notification:

        if deduplication_key:
            notification, created = Notification.objects.get_or_create(
                deduplication_key=deduplication_key,
                defaults={
                    "recipient": recipient,
                    "notification_type": notification_type,
                    "payload": payload,
                },
            )

            if not created:
                logger.info(
                    "Duplicate notification skipped key=%s",
                    deduplication_key,
                )

            return notification

        notification = Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            payload=payload,
        )

        logger.info(
            "Notification created id=%s type=%s recipient=%s",
            notification.id,
            notification_type,
            recipient.id,
        )

        return notification


def render_notification_email(notification):
    data = notification.payload
    nt = notification.notification_type

    if nt == Notification.NotificationType.WORKSPACE_INVITE:
        subject = f"You've been invited to {data['workspace_name']}"
        body = f"<p>Hi,</p><p>{data['invited_by']} invited you to join {data['workspace_name']}.</p>"

    elif nt == Notification.NotificationType.TASK_ASSIGNED:
        subject = f"New task assigned: {data['task_title']}"
        body = f"<p>You've been assigned: <strong>{data['task_title']}</strong>.</p>"

    elif nt == Notification.NotificationType.TASK_APPROVED:
        subject = f"Task approved: {data['task_title']}"
        body = f"<p>{data['approved_by']} approved your task: <strong>{data['task_title']}</strong>.</p>"

    elif nt == Notification.NotificationType.WORKSPACE_CREATED:
        subject = f"Workspace {data['workspace_name']} created"
        body = f"<p>Your workspace <strong>{data['workspace_name']}</strong> is ready.</p>"

    else:
        raise ValueError(f"No email renderer for notification type: {nt}")

    return subject, body


class NotificationDeliveryService:
    """Owns the business rules for delivering a single notification email:
    guarding against double-send, recording attempts, and recording outcome.
    Knows nothing about Huey, retries, or task scheduling.
    """

    @staticmethod
    def lock_for_sending(notification_id: int) -> Notification | None:
        """Locks the row, guards against re-sending, marks PROCESSING.
        Returns None if there's nothing to do (missing or already sent).
        """
        with transaction.atomic():
            try:
                notification = Notification.objects.select_for_update().get(id=notification_id)
            except Notification.DoesNotExist:
                logger.error("Notification id=%s not found, aborting", notification_id)
                return None

            if notification.status == Notification.StatusType.SUCCESS:
                logger.info("Notification id=%s already sent, skipping", notification_id)
                return None

            notification.status = Notification.StatusType.PROCESSING
            notification.attempts += 1
            notification.save(update_fields=["status", "attempts"])
            return notification

    @staticmethod
    def deliver(notification: Notification) -> None:
        """Sends the email and records the outcome. Raises RetryableEmailError
        (or any unexpected exception) if the caller should retry.
        """
        provider = BrevoEmailProvider()
        subject, html_body = render_notification_email(notification)

        try:
            provider.send_email(
                to=notification.recipient.email,
                subject=subject,
                html_body=html_body,
            )
        except NonRetryableEmailError as e:
            logger.error("Notification id=%s permanently failed: %s", notification.id, e)
            notification.status = Notification.StatusType.FAILED
            notification.last_error_message = str(e)
            notification.save(update_fields=["status", "last_error_message"])
            return

        except RetryableEmailError as e:
            logger.warning(
                "Notification id=%s failed (attempt %s/%s): %s",
                notification.id, notification.attempts, MAX_NOTIFICATION_ATTEMPTS, e,
            )
            notification.status = Notification.StatusType.FAILED
            notification.last_error_message = str(e)
            notification.save(update_fields=["status", "last_error_message"])
            raise

        except Exception as e:
            # Anything we didn't anticipate: don't let it disappear silently.
            # Record it like a retryable failure and let the caller decide
            # whether to retry, so one unknown bug doesn't just eat the email.
            logger.exception(
                "Notification id=%s failed with unexpected error (attempt %s/%s): %s",
                notification.id, notification.attempts, MAX_NOTIFICATION_ATTEMPTS, e,
            )
            notification.status = Notification.StatusType.FAILED
            notification.last_error_message = f"Unexpected error: {e}"
            notification.save(update_fields=["status", "last_error_message"])
            raise

        else:
            notification.status = Notification.StatusType.SUCCESS
            notification.sent_at = timezone.now()
            notification.save(update_fields=["status", "sent_at"])
            logger.info("Notification id=%s sent successfully", notification.id)

@transaction.atomic
def use_credits(workspace,user,amount):
    if amount<=0:
        raise ValueError("Amount must be greater than zero.")

    
    workspace = Workspace.objects.select_for_update().get(pk=workspace.pk)
    
    if workspace.credit_balance < amount:
    
        raise ValueError("Insufficient credits in workspace.")

    workspace.credit_balance -= amount
    try:
        with transaction.atomic():
            workspace.save(update_fields=["credit_balance", "updated_at"])
    except IntegrityError as error:
        _raise_constraint_validation_error(
            error,
            "credit_balance_non_negative",
            "The workspace does not have enough credits for this operation.",
        )

    CreditUsage.objects.create(
        workspace=workspace,
        user=user,
        credits_used=amount
    )

    AuditRecord.objects.create(
        workspace=workspace,
        user=user,
        action=f" {amount} credits deducted.",
    )

    return workspace


@transaction.atomic
def use_credits_idempotently(
    workspace,
    user,
    amount,
    idempotency_key,
):
    request_data = f"{workspace.id}:{user.id}:{amount}"

    request_hash = hashlib.sha256(
        request_data.encode("utf-8")
    ).hexdigest()

    try:
        idempotency_record = (
            IdempotencyKey.objects
            .select_for_update()
            .get(key=idempotency_key)
        )

    except IdempotencyKey.DoesNotExist:

        try:
            with transaction.atomic():
                idempotency_record = IdempotencyKey.objects.create(
                    key=idempotency_key,
                    request_hash=request_hash,
                    workspace=workspace,
                    status=IdempotencyKey.StatusType.PENDING,
                )

        except IntegrityError:
            idempotency_record = (
                IdempotencyKey.objects
                .select_for_update()
                .get(key=idempotency_key)
            )

    if idempotency_record.request_hash != request_hash:
        raise ValueError(
            "This Idempotency-Key has already been used for a different request."
        )

    if idempotency_record.status == IdempotencyKey.StatusType.SUCCESS:
        return {
            "detail": "Request has already been processed."
        }

    if idempotency_record.status == IdempotencyKey.StatusType.FAILED:
        raise ValueError(
            "This request has already failed. Use a new Idempotency-Key to try again."
        )

    try:
        workspace = use_credits(
            workspace=workspace,
            user=user,
            amount=amount,
        )

    except ValueError as error:
        idempotency_record.status = IdempotencyKey.StatusType.FAILED
        idempotency_record.save(update_fields=["status"])
        raise error

    idempotency_record.status = IdempotencyKey.StatusType.SUCCESS
    idempotency_record.save(update_fields=["status"])

    return {
        "detail": f"Successfully used {amount} credits.",
    }