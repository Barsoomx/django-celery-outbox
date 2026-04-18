# Dead Letter Queue

Messages that exceed `max_retries` are moved to `CeleryOutboxDeadLetter`.

## Viewing Dead Letters

### Django Admin

Navigate to Django Admin > Celery Outbox > Dead Letter Queue.

The changelist supports:

- filtering by `task_name`, `failure_reason`, `dead_at`, and `schema_version`
- searching by `task_id`, `task_name`, and `failure_reason`

### Management Command

```bash
python manage.py celery_outbox_stats
```

Output includes dead letter count.

## Investigating Failures

Each dead letter entry contains:

| Field | Description |
|-------|-------------|
| `task_name` | The failed task |
| `task_id` | Celery task ID |
| `args`, `kwargs` | Task arguments |
| `retries` | Number of attempts |
| `failure_reason` | Why it failed |
| `created_at` | Original queue time |
| `dead_at` | When dead-lettered |

## Replaying Dead Letters

Use the Django admin bulk action `retry_selected`.

What it does:

- copies the selected `CeleryOutboxDeadLetter` rows back into `CeleryOutbox`
- preserves the stored payload and `schema_version`
- deletes the retried rows from `celery_outbox_dead_letter`

There is no built-in management command equivalent. If you need scripted replay, wrap the same model-to-model copy in your own command.

Example automation sketch:

```python
from django.db import transaction
from django_celery_outbox.models import CeleryOutboxDeadLetter
from django_celery_outbox.models import CeleryOutbox

dl = CeleryOutboxDeadLetter.objects.get(pk=123)

with transaction.atomic():
    CeleryOutbox.objects.create(
        task_id=dl.task_id,
        task_name=dl.task_name,
        args=dl.args,
        kwargs=dl.kwargs,
        redacted_args=dl.redacted_args,
        redacted_kwargs=dl.redacted_kwargs,
        options=dl.options,
        schema_version=dl.schema_version,
        sentry_trace_id=dl.sentry_trace_id,
        sentry_baggage=dl.sentry_baggage,
        structlog_context=dl.structlog_context,
    )
    dl.delete()
```

## Purging Old Entries

**Option 1: Celery Beat (recommended)**

```python
# settings.py
CELERY_OUTBOX_DLQ_RETENTION = {
    'older_than_dead': '30d',
}

# celery.py
from celery.schedules import crontab

app.conf.beat_schedule = {
    'purge-dead-letters': {
        'task': 'django_celery_outbox.tasks.purge_dead_letter',
        'schedule': crontab(hour=3, minute=0),  # daily at 3am
    },
}
```

**Option 2: Management command**

```bash
# Delete entries older than 30 days
python manage.py celery_outbox_purge_dead_letter --older-than-dead 30d

# Preview what would be deleted
python manage.py celery_outbox_purge_dead_letter --older-than-dead 30d --dry-run
```

## Retention Policy

Dead letters should be reviewed and purged regularly. Recommended:

1. **Alert** on `dead_letter.count > 0`
2. **Investigate** within 24 hours
3. **Purge** entries older than 30 days
