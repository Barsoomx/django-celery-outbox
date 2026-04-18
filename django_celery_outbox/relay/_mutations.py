import random
from datetime import timedelta

from django.db.models import F
from django.db.models.functions import Now

from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter


class RelayMutations:
    def __init__(self, backoff_time: int) -> None:
        self._backoff_time = backoff_time

    def update_failed(self, failed_messages: list[tuple[int, int]]) -> None:
        if not failed_messages:
            return

        grouped_ids: dict[int, list[int]] = {}
        for msg_id, retries in failed_messages:
            grouped_ids.setdefault(retries, []).append(msg_id)

        for retries, message_ids in grouped_ids.items():
            jitter = random.uniform(0, self._backoff_time * 0.1)  # noqa: S311
            delay = timedelta(seconds=self._backoff_time * (2**retries) + jitter)
            CeleryOutbox.objects.filter(pk__in=message_ids).update(
                retries=F('retries') + 1,
                updated_at=Now(),
                retry_after=Now() + delay,
            )

    def delete_published(self, message_ids: list[int]) -> None:
        if not message_ids:
            return

        CeleryOutbox.objects.filter(pk__in=message_ids).delete()

    def move_exceeded_to_dead_letter(self, exceeded_messages: list[CeleryOutbox]) -> None:
        if not exceeded_messages:
            return

        dead_letters = [
            CeleryOutboxDeadLetter(
                created_at=msg.created_at,
                retries=msg.retries,
                task_id=msg.task_id,
                task_name=msg.task_name,
                args=msg.args,
                kwargs=msg.kwargs,
                redacted_args=msg.redacted_args,
                redacted_kwargs=msg.redacted_kwargs,
                options=msg.options,
                sentry_trace_id=msg.sentry_trace_id,
                sentry_baggage=msg.sentry_baggage,
                structlog_context=msg.structlog_context,
                schema_version=msg.schema_version,
                failure_reason='max retries exceeded',
            )
            for msg in exceeded_messages
        ]

        CeleryOutboxDeadLetter.objects.bulk_create(dead_letters)
        CeleryOutbox.objects.filter(pk__in=[msg.id for msg in exceeded_messages]).delete()
