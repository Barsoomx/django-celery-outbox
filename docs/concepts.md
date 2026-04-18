# Concepts

## The Problem

Traditional Celery task dispatch has a fundamental race condition:

```python
with transaction.atomic():
    order = Order.objects.create(...)
    send_email.delay(order.id)  # Task sent NOW, before commit
# Transaction commits HERE
```

If the transaction rolls back after the task is sent, the worker receives a task for an order that doesn't exist.

## The Solution: Transactional Outbox

Instead of sending tasks directly to the broker, we write them to a database table within the same transaction:

```
┌─────────────────────────────────────────────────────────┐
│                    TRANSACTION                          │
│  ┌─────────────┐    ┌─────────────────────────────┐     │
│  │ Order.save()│ →  │ CeleryOutbox.create(task)   │     │
│  └─────────────┘    └─────────────────────────────┘     │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼ COMMIT
┌─────────────────────────────────────────────────────────┐
│                    RELAY DAEMON                         │
│  ┌─────────────────────────┐    ┌─────────────────┐     │
│  │ SELECT FOR UPDATE       │ →  │ app.send_task() │     │
│  │ SKIP LOCKED             │    │ to broker       │     │
│  └─────────────────────────┘    └─────────────────┘     │
└─────────────────────────────────────────────────────────┘
```

## Delivery Guarantees

**At-least-once delivery**: Once the transaction commits, the task will eventually be delivered to the broker. If the relay crashes, it will retry on next startup.

**No duplicate prevention**: The same task may be delivered multiple times if the relay crashes after sending but before deleting from the outbox. Your tasks should be idempotent.

## Components

### OutboxCelery

Drop-in replacement for `celery.Celery`. Intercepts `send_task()` calls and writes to the outbox table instead of the broker.

### Relay Daemon

Management command (`celery_outbox_relay`) that:

1. Polls the outbox table for pending messages
2. Sends them to the broker via Celery's `send_task()`
3. Deletes successfully sent messages
4. Retries failed messages with exponential backoff
5. Moves permanently failed messages to dead letter queue

### Dead Letter Queue

Messages that exceed `max_retries` are moved to `CeleryOutboxDeadLetter` for inspection and optional replay via the Django admin `retry_selected` action or your own automation.
