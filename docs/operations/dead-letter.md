# Dead Letter Queue

Messages that exceed `max_retries` are moved to `CeleryOutboxDeadLetter`.

## Viewing Dead Letters

### Django Admin

Navigate to Django Admin > Celery Outbox > Dead Letter Queue

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
| `moved_at` | When dead-lettered |

## Replaying Dead Letters

Currently manual. Copy task data and re-queue:

```python
from django_celery_outbox.models import CeleryOutboxDeadLetter
from myproject.celery import app

dl = CeleryOutboxDeadLetter.objects.get(pk=123)
app.send_task(dl.task_name, args=dl.args, kwargs=dl.kwargs)
dl.delete()
```

## Purging Old Entries

```bash
# Delete entries older than 30 days
python manage.py celery_outbox_purge_dead_letter --older-than-dead 30d
```

## Retention Policy

Dead letters should be reviewed and purged regularly. Recommended:

1. **Alert** on `dead_letter.count > 0`
2. **Investigate** within 24 hours
3. **Purge** entries older than 30 days
