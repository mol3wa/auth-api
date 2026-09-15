import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from django.conf import settings
from .base import EmailProvider, RetryableEmailError, NonRetryableEmailError


class BrevoEmailProvider(EmailProvider):
    def send_email(self, *, to: str, subject: str, html_body: str) -> None:
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = settings.BREVO_API_KEY
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
            sib_api_v3_sdk.ApiClient(configuration)
        )

        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": to}],
            sender={"name": "Your App", "email": settings.DEFAULT_FROM_EMAIL},
            subject=subject,
            html_content=html_body,
        )

        try:
            api_instance.send_transac_email(send_smtp_email)
        except ApiException as e:
            if e.status and e.status >= 500:
                raise RetryableEmailError(f"Brevo server error: {e.status}")
            raise NonRetryableEmailError(f"Brevo rejected request: {e.status} {e.body}")