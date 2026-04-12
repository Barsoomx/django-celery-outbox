# Structlog Integration

The outbox propagates structlog context from producer to consumer.

## How It Works

1. Producer captures `structlog.contextvars.get_contextvars()`
2. Context is stored in `CeleryOutbox.structlog_context` as JSON
3. Relay restores context before sending to broker
4. Worker receives context in task headers

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

When `CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS` is set, only the listed keys are stored and propagated.

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

Worker logs will include `request_id` and `user_id`.

## Disabling

```python
CELERY_OUTBOX_STRUCTLOG_ENABLED = False
```

When disabled, no context is captured or propagated.
