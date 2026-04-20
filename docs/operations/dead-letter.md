# Dead Letter Queue

Messages that exceed `max_retries` are moved to `CeleryOutboxDeadLetter`.

## Viewing Dead Letters

### Django Admin

Navigate to Django Admin > Celery Outbox > Dead Letter Queue.

The changelist supports:

- filtering by `task_name`, `failure_reason`, `dead_at`, and `schema_version`
- searching by `task_id`, `task_name`, and `failure_reason`

### Snapshot Command

```bash
python manage.py celery_outbox_stats
```

Output includes dead letter count.

### Replay Command

```bash
python manage.py celery_outbox_replay_dead_letter 123 124
python manage.py celery_outbox_replay_dead_letter 123 124 125 --limit 2
```

The replay command requeues only the selected dead-letter IDs. It preserves stored payload, schema, and tracing/context fields, then removes replayed rows from `celery_outbox_dead_letter`.
If some selected IDs were already replayed or deleted by another operator, the command requeues only the remaining matches and prints `0` when nothing is left to move.

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
- preserves the stored payload, `schema_version`, and tracing/context fields
- deletes the retried rows from `celery_outbox_dead_letter`

For scripted replay, use `python manage.py celery_outbox_replay_dead_letter ...` instead of writing your own model-copy loop.

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

1. **Alert** on `increase(celery_outbox_messages_exceeded_total[10m]) > 0`
2. **Investigate** within 24 hours
3. **Purge** entries older than 30 days

Treat dead-letter growth as "new failures over time," not as a fixed table-size threshold. A large but stable table may just mean you need a purge job; a non-zero increase means something is failing now.
