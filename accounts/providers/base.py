from abc import ABC, abstractmethod


class EmailProviderError(Exception):
    """Base error for provider failures."""


class RetryableEmailError(EmailProviderError):
    """Timeout, connection error, 5xx — try again later."""


class NonRetryableEmailError(EmailProviderError):
    """Bad request, invalid address, auth failure — retrying won't help."""


class EmailProvider(ABC):
    @abstractmethod
    def send_email(self, *, to: str, subject: str, html_body: str) -> None:
        """Send an email. Raise RetryableEmailError or NonRetryableEmailError on failure."""
        ...