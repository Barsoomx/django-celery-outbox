import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def send_order_confirmation(order_id: int, email: str) -> dict:
    logger.info('Sending confirmation email for order %s to %s', order_id, email)

    return {'order_id': order_id, 'email': email, 'status': 'sent'}


@shared_task
def notify_warehouse(order_id: int) -> dict:
    logger.info('Notifying warehouse about order %s', order_id)

    return {'order_id': order_id, 'status': 'notified'}


@shared_task
def schedule_shipping_reminder(order_id: int) -> dict:
    logger.info('Sending shipping reminder for order %s', order_id)

    return {'order_id': order_id, 'status': 'reminded'}
