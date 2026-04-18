# Troubleshooting

## Tasks Not Being Sent

### Check queue depth

```bash
python manage.py celery_outbox_stats
```

If queue is growing, relay may not be running.

### Check relay logs

```bash
docker compose logs relay
```

Look for `celery_outbox_relay_started` and `celery_outbox_batch_processed`.

### Check broker connectivity

```bash
celery -A myproject inspect ping
```

## Tasks Sent But Not Executed

### Check worker logs

```bash
celery -A myproject worker -l info
```

### Verify broker has messages

RabbitMQ Management UI: http://localhost:15672/

## High Queue Depth

1. Scale relay instances
2. Increase batch size
3. Check for slow broker

## Messages Going to Dead Letter

### Check failure reasons

```python
from django_celery_outbox.models import CeleryOutboxDeadLetter

for dl in CeleryOutboxDeadLetter.objects.all()[:10]:
    print(dl.task_name, dl.failure_reason)
```

### Common causes

- Broker connection refused
- Invalid task name (task not registered)
- Serialization errors

## "Not in transaction" Warnings

```
celery_outbox_not_in_transaction task_name=myapp.tasks.send_email
```

Task was sent outside `transaction.atomic()`. Either:

1. Wrap in transaction
2. Add to `CELERY_OUTBOX_EXCLUDE_TASKS`

## Database Lock Contention

If using many relay instances, you may see lock waits. Reduce instances or batch size.

```sql
-- PostgreSQL
SELECT * FROM pg_locks WHERE relation = 'celery_outbox'::regclass;

-- MySQL 8
SELECT *
FROM performance_schema.data_locks
WHERE OBJECT_NAME = 'celery_outbox';
```
