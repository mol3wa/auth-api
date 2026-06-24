import logging

import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError

from .models import EmailOTP

User = get_user_model()

logger = logging.getLogger(__name__)


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
