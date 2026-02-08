__version__ = '0.1.0'

__all__ = [
    'OutboxCelery',
    'Relay',
    'CeleryOutbox',
    'CeleryOutboxDeadLetter',
    'outbox_message_created',
    'outbox_message_sent',
    'outbox_message_failed',
    'outbox_message_dead_lettered',
]


def __getattr__(name: str) -> type:
    if name == 'OutboxCelery':
        from django_celery_outbox.app import OutboxCelery

        return OutboxCelery

    if name == 'Relay':
        from django_celery_outbox.relay import Relay

        return Relay

    if name == 'CeleryOutbox':
        from django_celery_outbox.models import CeleryOutbox

        return CeleryOutbox

    if name == 'CeleryOutboxDeadLetter':
        from django_celery_outbox.models import CeleryOutboxDeadLetter

        return CeleryOutboxDeadLetter

    if name in (
        'outbox_message_created',
        'outbox_message_sent',
        'outbox_message_failed',
        'outbox_message_dead_lettered',
    ):
        from django_celery_outbox import signals

        return getattr(signals, name)

    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
