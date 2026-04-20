from collections.abc import Sequence

from django.db import transaction

from django_celery_outbox._settings import get_outbox_db_alias
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter


def replay_dead_letters(dead_letter_ids: Sequence[int], *, limit: int | None = None) -> int:
    db_alias = get_outbox_db_alias()
    queryset = CeleryOutboxDeadLetter.objects.using(db_alias).filter(pk__in=dead_letter_ids).order_by('pk')
    if limit is not None:
        queryset = queryset[:limit]

    rows = list(queryset)
    if not rows:
        return 0

    with transaction.atomic(using=db_alias):
        CeleryOutbox.objects.using(db_alias).bulk_create(
            [
                CeleryOutbox(
                    task_id=row.task_id,
                    task_name=row.task_name,
                    args=row.args,
                    kwargs=row.kwargs,
                    redacted_args=row.redacted_args,
                    redacted_kwargs=row.redacted_kwargs,
                    options=row.options,
                    schema_version=row.schema_version,
                    sentry_trace_id=row.sentry_trace_id,
                    sentry_baggage=row.sentry_baggage,
                    structlog_context=row.structlog_context,
                )
                for row in rows
            ]
        )
        CeleryOutboxDeadLetter.objects.using(db_alias).filter(pk__in=[row.pk for row in rows]).delete()

    return len(rows)
