from datetime import timedelta
from typing import Any
from typing import cast

from celery import shared_task

from django_celery_outbox._settings import load_dlq_retention_setting
from django_celery_outbox.purge import purge_dead_letter


@shared_task(name='django_celery_outbox.tasks.purge_dead_letter')
def purge_dead_letter_task() -> dict[str, Any]:
    retention = load_dlq_retention_setting()
    if retention is None:
        raise ValueError('CELERY_OUTBOX_DLQ_RETENTION setting is required for purge_dead_letter task')

    result = purge_dead_letter(
        older_than_dead=cast(timedelta | None, retention['older_than_dead']),
        older_than_created=cast(timedelta | None, retention['older_than_created']),
        task_name_pattern=cast(str | None, retention['task_name_pattern']),
        dry_run=False,
    )

    return {
        'deleted_count': result.deleted_count,
        'task_names': result.task_names,
    }
