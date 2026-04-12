from datetime import timedelta

from django.db.models import Q
from django.db.models.functions import Now

from django_celery_outbox.models import CeleryOutbox
from django_celery_outbox.serialization import CURRENT_SCHEMA_VERSION, MIN_SUPPORTED_VERSION

_STALE_TIMEOUT = timedelta(minutes=5)


def get_pending_filter(stale_timeout: timedelta = _STALE_TIMEOUT) -> Q:
    return (Q(updated_at__isnull=True) | Q(retry_after__lte=Now()) | Q(updated_at__lte=Now() - stale_timeout, retry_after__isnull=True)) & Q(
        schema_version__gte=MIN_SUPPORTED_VERSION,
        schema_version__lte=CURRENT_SCHEMA_VERSION,
    )


class MessageSelector:
    def __init__(self, batch_size: int, stale_timeout: timedelta = _STALE_TIMEOUT) -> None:
        self._batch_size = batch_size
        self._stale_timeout = stale_timeout

    def run(self) -> list[CeleryOutbox]:
        messages = self._select()
        self._mark_in_flight(messages)
        return messages

    def _select(self) -> list[CeleryOutbox]:
        queryset = (
            CeleryOutbox.objects.select_for_update(skip_locked=True)
            .filter(get_pending_filter(self._stale_timeout))
            .order_by('id')[: self._batch_size]
        )

        return list(queryset)

    def _mark_in_flight(self, messages: list[CeleryOutbox]) -> None:
        message_ids = [msg.id for msg in messages]
        if not message_ids:
            return

        CeleryOutbox.objects.filter(pk__in=message_ids).update(updated_at=Now())
