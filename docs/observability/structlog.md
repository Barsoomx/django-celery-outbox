# Structlog Integration

The outbox captures structlog context with the queued message and restores it inside the relay process when that message is published.

## How It Works

1. Producer captures `structlog.contextvars.get_contextvars()`
2. Context is stored in `CeleryOutbox.structlog_context` as JSON
3. Relay parses that JSON and re-binds it with `structlog.contextvars.bound_contextvars(...)`
4. The package does not serialize structlog keys into Celery task headers for workers

## Configuration

```python
# settings.py
CELERY_OUTBOX_STRUCTLOG_ENABLED = True  # Default

# Optional: capture only safe keys
CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS = [
    'request_id',
    'trace_id',
    'user_id',
]
```

When `CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS` is set, only the listed keys are stored and rebound by the relay.

## Example

```python
import structlog

log = structlog.get_logger()

with structlog.contextvars.bound_contextvars(
    request_id='abc-123',
    user_id=42,
):
    with transaction.atomic():
        order = Order.objects.create(...)
        send_email.delay(order.id)
        # Context captured: {'request_id': 'abc-123', 'user_id': 42}
```

The relay-side publish path will see `request_id` and `user_id` bound while this message is being sent.

## Disabling

```python
CELERY_OUTBOX_STRUCTLOG_ENABLED = False
```

When disabled, no structlog context is captured on enqueue or rebound inside the relay.
