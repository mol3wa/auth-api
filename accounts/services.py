import threading
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from django.conf import settings

def send_otp_email(email, first_name, otp_code, purpose):
    """
    Sends OTP email using Brevo transactional API in a separate thread.
    """
    def _send():
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = settings.BREVO_API_KEY
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))
        
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
            print(f"Failed to send email: {e}")

    thread = threading.Thread(target=_send)
    thread.start()