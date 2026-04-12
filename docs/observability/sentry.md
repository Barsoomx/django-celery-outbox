# Sentry Integration

The outbox propagates Sentry trace context across the transaction boundary.

## How It Works

1. Producer captures `sentry_sdk.get_traceparent()` and `sentry_sdk.get_baggage()`
2. Trace IDs are stored in `CeleryOutbox.sentry_trace_id` and `sentry_baggage`
3. Relay sends them as `sentry-trace` and `baggage` headers
4. Worker continues the trace

## Configuration

No configuration needed. If Sentry SDK is installed and initialized, trace propagation is automatic.

```python
# settings.py or wsgi.py
import sentry_sdk

sentry_sdk.init(
    dsn="...",
    traces_sample_rate=1.0,
)
```

## Trace Continuity

```
Producer Transaction
    └── celery_outbox.intercept (span)
            │
         [DATABASE]
            │
Relay Transaction
    └── celery_outbox.relay.send (span)
            │
         [BROKER]
            │
Worker Transaction
    └── task.execute (span)
```

## Sentry Dashboard

In Sentry, you'll see:

1. **Producer transaction**: Original HTTP request that created the task
2. **Relay span**: `celery_outbox.relay.send` with message ID
3. **Worker transaction**: Task execution linked to producer

This gives you end-to-end visibility from HTTP request to task completion.
