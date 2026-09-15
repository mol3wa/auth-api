import logging
from datetime import timedelta

from django.utils import timezone
from django.db import transaction
from huey import crontab
from huey.contrib.djhuey import db_task, db_periodic_task

from accounts.services import NotificationDeliveryService

from .models import Notification
from .providers.brevo import BrevoEmailProvider
from .providers.base import RetryableEmailError, NonRetryableEmailError


logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


@db_task(retries=MAX_ATTEMPTS, retry_delay=60)
def send_notification_email(notification_id: int):
    from .services import render_notification_email
    logger.info("Task started: send_notification_email id=%s", notification_id)

    notification = NotificationDeliveryService.lock_for_sending(notification_id)
    if notification is None:
        return

    NotificationDeliveryService.deliver(notification)
@db_task()
def send_reminder_email(notification_id: int):
    notification = Notification.objects.filter(
        id=notification_id, status=Notification.StatusType.SUCCESS
    ).first()
    if not notification:
        return
    logger.info("Sending reminder for notification id=%s", notification_id)
    

def schedule_invite_reminder(notification_id: int):
    send_reminder_email.schedule(args=(notification_id,), delay=60 * 60 * 24)


@db_periodic_task(crontab(hour=3, minute=0))
def cleanup_old_notifications():
    cutoff = timezone.now() - timedelta(days=90)
    deleted_count, _ = Notification.objects.filter(
        status=Notification.StatusType.SUCCESS,
        created_at__lt=cutoff,
    ).delete()
    logger.info("Cleanup: removed %s old successful notifications", deleted_count)