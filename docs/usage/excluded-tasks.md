# Excluded Tasks

## Bypassing the Outbox

Some tasks should bypass the outbox and go directly to the broker:

- Real-time notifications that can't wait for relay
- Tasks that don't need transactional guarantees
- High-volume tasks where relay latency matters

## Configuration

```python
# settings.py
CELERY_OUTBOX_EXCLUDE_TASKS = {
    'myapp.tasks.send_push_notification',
    'myapp.tasks.log_analytics',
}
```

## Behavior

Excluded tasks are sent directly to the broker using the original `Celery.send_task()`:

```python
# This goes through outbox
order_created.delay(order.id)

# This bypasses outbox (if in EXCLUDE_TASKS)
send_push_notification.delay(user.id, 'Order shipped!')
```

!!! warning "No Transactional Guarantee"
    Excluded tasks can be lost if the broker connection fails, or executed with uncommitted data if called inside a transaction.
