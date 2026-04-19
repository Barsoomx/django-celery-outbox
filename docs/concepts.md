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

**Durable recovery for committed rows**: Once the transaction commits, the outbox row stays available for relay retry or recovery until it is published or moved to dead letter.

**Duplicate delivery is possible**: If the relay crashes after publishing to the broker but before cleaning up the outbox row, stale-timeout recovery can reclaim and resend it. Your tasks should be idempotent.

**Broker-confirm caveat**: Successful return from `Celery.send_task()` is not the same thing as a broker acknowledgement. Without publisher confirms, the relay can still lose a message after deleting the outbox row.

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
