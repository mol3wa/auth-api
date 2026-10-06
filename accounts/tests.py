import hashlib

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase
from unittest.mock import patch

from .models import (
    AuditRecord,
    CreditUsage,
    IdempotencyKey,
    Notification,
    Project,
    Task,
    Workspace,
    WorkspaceMembership,
)
from .services import NotificationService, TaskService, WorkspaceService, use_credits


User = get_user_model()


class UseCreditsViewTest(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="credits-view@example.com",
            first_name="Credits",
            last_name="User",
            password="password123",
        )
        self.workspace = Workspace.objects.create(
            name="Credits View Workspace",
            credit_balance=100,
        )
        WorkspaceMembership.objects.create(
            user=self.user,
            workspace=self.workspace,
            role=WorkspaceMembership.RoleType.OWNER,
        )
        self.url = reverse(
            "use-credits",
            kwargs={"workspace_id": self.workspace.id},
        )
        self.client.force_authenticate(user=self.user)

    def test_deducts_credits_and_returns_success(self):
        response = self.client.post(
            self.url,
            {"amount": 20},
            format="json",
            HTTP_IDEMPOTENCY_KEY="test-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["detail"], "Successfully used 20 credits.")
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.credit_balance, 80)
        self.assertEqual(CreditUsage.objects.count(), 1)
        self.assertEqual(AuditRecord.objects.count(), 1)
        self.assertEqual(IdempotencyKey.objects.count(), 1)
        idempotency_record = IdempotencyKey.objects.get()
        expected_request_hash = hashlib.sha256(
            f"{self.workspace.id}:{self.user.id}:20".encode("utf-8")
        ).hexdigest()
        self.assertEqual(idempotency_record.key, "test-key")
        self.assertEqual(idempotency_record.request_hash, expected_request_hash)
        self.assertEqual(idempotency_record.workspace, self.workspace)
        self.assertEqual(idempotency_record.status, IdempotencyKey.StatusType.SUCCESS)

    def test_repeated_request_with_same_key_is_processed_once(self):
        request_data = {"amount": 20}
        first_response = self.client.post(
            self.url,
            request_data,
            format="json",
            HTTP_IDEMPOTENCY_KEY="repeat-key",
        )
        second_response = self.client.post(
            self.url,
            request_data,
            format="json",
            HTTP_IDEMPOTENCY_KEY="repeat-key",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.credit_balance, 80)
        self.assertEqual(CreditUsage.objects.count(), 1)
        self.assertEqual(AuditRecord.objects.count(), 1)
        self.assertEqual(IdempotencyKey.objects.count(), 1)

    def test_rejects_same_key_for_different_request(self):
        first_response = self.client.post(
            self.url,
            {"amount": 10},
            format="json",
            HTTP_IDEMPOTENCY_KEY="reused-key",
        )
        second_response = self.client.post(
            self.url,
            {"amount": 20},
            format="json",
            HTTP_IDEMPOTENCY_KEY="reused-key",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 400)
        self.assertIn(
            "already been used for a different request",
            second_response.data["detail"],
        )
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.credit_balance, 90)
        self.assertEqual(CreditUsage.objects.count(), 1)
        self.assertEqual(AuditRecord.objects.count(), 1)
        self.assertEqual(IdempotencyKey.objects.count(), 1)

    def test_rejects_non_positive_amount(self):
        response = self.client.post(
            self.url,
            {"amount": 0},
            format="json",
            HTTP_IDEMPOTENCY_KEY="test-key",
        )

        self.assertEqual(response.status_code, 400)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.credit_balance, 100)
        self.assertEqual(CreditUsage.objects.count(), 0)

    def test_returns_bad_request_when_balance_is_insufficient(self):
        response = self.client.post(
            self.url,
            {"amount": 101},
            format="json",
            HTTP_IDEMPOTENCY_KEY="test-key",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["detail"],
            "Insufficient credits in workspace.",
        )
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.credit_balance, 100)
        self.assertEqual(CreditUsage.objects.count(), 0)
        self.assertEqual(AuditRecord.objects.count(), 0)
        self.assertEqual(IdempotencyKey.objects.count(), 1)
        idempotency_record = IdempotencyKey.objects.get()
        self.assertEqual(idempotency_record.key, "test-key")
        self.assertEqual(idempotency_record.workspace, self.workspace)
        self.assertEqual(idempotency_record.status, IdempotencyKey.StatusType.FAILED)

    def test_requires_idempotency_key(self):
        response = self.client.post(self.url, {"amount": 20}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["detail"],
            "Idempotency-Key header is required.",
        )
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.credit_balance, 100)
        self.assertEqual(IdempotencyKey.objects.count(), 0)
        self.assertEqual(CreditUsage.objects.count(), 0)
        self.assertEqual(AuditRecord.objects.count(), 0)

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(self.url, {"amount": 20}, format="json")

        self.assertEqual(response.status_code, 401)


class UseCreditsTransactionTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
          email="test@example.com",
          first_name="Test",
          last_name="User",
          password="password123",
)
      
        self.workspace = Workspace.objects.create(
            name="Test Workspace",
            credit_balance=100,
        )

        self.workspace.members.add(self.user)

    def test_credits_are_deducted_and_records_created(self):
        use_credits(
            workspace=self.workspace,
            user=self.user,
            amount=20,
        )

        self.workspace.refresh_from_db()

        self.assertEqual(self.workspace.credit_balance, 80)

        self.assertEqual(
            CreditUsage.objects.count(),
            1,
        )

        self.assertEqual(
            AuditRecord.objects.count(),
            1,
        )

    def test_transaction_rolls_back_on_failure(self):
        original_balance = self.workspace.credit_balance

        try:
            with self.assertRaises(Exception):
                self._failing_credit_operation()
        finally:
            self.workspace.refresh_from_db()

        self.assertEqual(
            self.workspace.credit_balance,
            original_balance,
        )

        self.assertEqual(
            CreditUsage.objects.count(),
            0,
        )

        self.assertEqual(
            AuditRecord.objects.count(),
            0,
        )

    def _failing_credit_operation(self):
        from django.db import transaction

        with transaction.atomic():
            self.workspace.credit_balance -= 20
            self.workspace.save()

            raise Exception("Intentional failure")

            CreditUsage.objects.create(
                workspace=self.workspace,
                user=self.user,
                credits_used=20,
            )

            AuditRecord.objects.create(
                workspace=self.workspace,
                user=self.user,
                action="20 credits deducted",
            )


class ProjectAndTaskCreationApiTest(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com",
            first_name="Project",
            last_name="Owner",
            password="password123",
        )
        self.workspace = Workspace.objects.create(
            name="Creation Workspace",
            credit_balance=10,
        )
        WorkspaceMembership.objects.create(
            user=self.user,
            workspace=self.workspace,
            role=WorkspaceMembership.RoleType.OWNER,
        )
        self.client.force_authenticate(user=self.user)

    def test_create_project_then_task(self):
        project_response = self.client.post(
            "/api/projects/",
            {
                "workspace": self.workspace.id,
                "name": "Launch Project",
                "description": "Project creation smoke test",
            },
            format="json",
        )

        self.assertEqual(project_response.status_code, 201)
        project = Project.objects.get(id=project_response.data["id"])
        self.assertEqual(project.created_by, self.user)

        task_response = self.client.post(
            "/api/tasks/",
            {
                "project": project.id,
                "title": "Create API task",
                "description": "Task creation smoke test",
            },
            format="json",
        )

        self.assertEqual(task_response.status_code, 201)
        task = Task.objects.get(id=task_response.data["id"])
        self.assertEqual(task.created_by, self.user)
        self.assertEqual(task.project, project)
        self.assertEqual(task.status, Task.StatusType.TODO)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.credit_balance, 5)


class DatabaseConstraintTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="constraint-user@example.com",
            first_name="Constraint",
            last_name="User",
            password="password123",
        )
        self.other_user = User.objects.create_user(
            email="other-user@example.com",
            first_name="Other",
            last_name="User",
            password="password123",
        )
        self.workspace = Workspace.objects.create(
            name="Constraint Workspace",
            credit_balance=10,
        )
        self.project = Project.objects.create(
            workspace=self.workspace,
            name="Constraint Project",
            created_by=self.user,
        )

    def test_duplicate_workspace_membership_constraint(self):
        WorkspaceMembership.objects.create(
            user=self.user,
            workspace=self.workspace,
            role=WorkspaceMembership.RoleType.MEMBER,
        )
        WorkspaceMembership.objects.create(
            user=self.other_user,
            workspace=self.workspace,
            role=WorkspaceMembership.RoleType.MEMBER,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WorkspaceMembership.objects.create(
                    user=self.user,
                    workspace=self.workspace,
                    role=WorkspaceMembership.RoleType.MEMBER,
                )

    def test_duplicate_workspace_membership_has_friendly_error(self):
        WorkspaceMembership.objects.create(
            user=self.user,
            workspace=self.workspace,
            role=WorkspaceMembership.RoleType.MEMBER,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "This user is already a member of the workspace.",
        ):
            WorkspaceService.add_member(
                invited_by=self.other_user,
                validated_data={
                    "user": self.user,
                    "workspace": self.workspace,
                    "role": WorkspaceMembership.RoleType.MEMBER,
                },
            )

    def test_non_negative_credit_balance_constraint(self):
        self.workspace.credit_balance = 0
        self.workspace.save(update_fields=["credit_balance"])
        self.workspace.credit_balance = 25
        self.workspace.save(update_fields=["credit_balance"])

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Workspace.objects.filter(pk=self.workspace.pk).update(
                    credit_balance=-1,
                )

    def test_negative_credit_integrity_error_has_friendly_error(self):
        def force_negative_balance(instance, *args, **kwargs):
            return Workspace.objects.filter(pk=instance.pk).update(
                credit_balance=-1,
            )

        with self.assertRaisesMessage(
            ValidationError,
            "The workspace does not have enough credits for this operation.",
        ):
            with patch.object(
                Workspace,
                "save",
                force_negative_balance,
            ):
                use_credits(self.workspace, self.user, 1)

    def test_invalid_task_status_constraint(self):
        Task.objects.create(
            project=self.project,
            title="Valid task",
            created_by=self.user,
            status=Task.StatusType.TODO,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Task.objects.create(
                    project=self.project,
                    title="Invalid task",
                    created_by=self.user,
                    status="NOT_A_STATUS",
                )

    def test_invalid_task_status_has_friendly_error(self):
        with self.assertRaisesMessage(
            ValidationError,
            "The requested task status is invalid.",
        ):
            TaskService.create_task(
                user=self.user,
                validated_data={
                    "project": self.project,
                    "title": "Invalid task",
                    "status": "NOT_A_STATUS",
                },
            )


class WorkspaceCreatedNotificationDeduplicationTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="workspace-notifications@example.com",
            first_name="Workspace",
            last_name="Owner",
            password="password123",
        )

    @patch("accounts.tasks.send_notification_email")
    def test_workspace_creation_creates_expected_notification(self, send_email):
        workspace = WorkspaceService.create_workspace(
            user=self.user,
            validated_data={"name": "Notification Workspace"},
        )

        self.assertEqual(Notification.objects.count(), 1)
        notification = Notification.objects.get()
        self.assertEqual(
            notification.notification_type,
            Notification.NotificationType.WORKSPACE_CREATED,
        )
        self.assertEqual(
            notification.deduplication_key,
            f"workspace_created:{workspace.id}:{self.user.id}",
        )
        self.assertEqual(
            notification.payload,
            {
                "workspace_id": workspace.id,
                "workspace_name": workspace.name,
            },
        )
        send_email.assert_called_once_with(notification.id)

    def test_duplicate_workspace_created_notification_returns_same_record(self):
        workspace = Workspace.objects.create(name="Duplicate Event Workspace")
        deduplication_key = f"workspace_created:{workspace.id}:{self.user.id}"
        notification_data = {
            "recipient": self.user,
            "notification_type": Notification.NotificationType.WORKSPACE_CREATED,
            "payload": {
                "workspace_id": workspace.id,
                "workspace_name": workspace.name,
            },
            "deduplication_key": deduplication_key,
        }

        first_notification = NotificationService.create(**notification_data)
        second_notification = NotificationService.create(**notification_data)

        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(first_notification.pk, second_notification.pk)
        self.assertEqual(first_notification.deduplication_key, deduplication_key)

    @patch("accounts.tasks.send_notification_email")
    def test_different_workspaces_have_distinct_notification_keys(self, send_email):
        first_workspace = WorkspaceService.create_workspace(
            user=self.user,
            validated_data={"name": "First Notification Workspace"},
        )
        second_workspace = WorkspaceService.create_workspace(
            user=self.user,
            validated_data={"name": "Second Notification Workspace"},
        )

        self.assertEqual(Notification.objects.count(), 2)
        notifications = list(Notification.objects.order_by("deduplication_key"))
        self.assertEqual(
            {notification.deduplication_key for notification in notifications},
            {
                f"workspace_created:{first_workspace.id}:{self.user.id}",
                f"workspace_created:{second_workspace.id}:{self.user.id}",
            },
        )
        self.assertEqual(send_email.call_count, 2)