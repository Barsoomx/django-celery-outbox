from typing import Any

from celery import shared_task
from django.conf import settings

from django_celery_outbox.purge import parse_duration, purge_dead_letter


@shared_task(name='celery_outbox.purge_dead_letter')
def purge_dead_letter_task() -> dict[str, Any]:
    retention = getattr(settings, 'CELERY_OUTBOX_DLQ_RETENTION', None)
    if retention is None:
        raise ValueError('CELERY_OUTBOX_DLQ_RETENTION setting is required for purge_dead_letter task')

    older_than_dead_str = retention.get('older_than_dead')
    older_than_created_str = retention.get('older_than_created')
    task_name_pattern = retention.get('task_name')

    if not older_than_dead_str and not older_than_created_str:
        raise ValueError('CELERY_OUTBOX_DLQ_RETENTION must specify older_than_dead or older_than_created')

    older_than_dead = parse_duration(older_than_dead_str) if older_than_dead_str else None
    older_than_created = parse_duration(older_than_created_str) if older_than_created_str else None

    result = purge_dead_letter(
        older_than_dead=older_than_dead,
        older_than_created=older_than_created,
        task_name_pattern=task_name_pattern,
        dry_run=False,
    )

    return {
        'deleted_count': result.deleted_count,
        'task_names': result.task_names,
    }
