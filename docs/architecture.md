# Architecture

## Overview

`django-celery-outbox` implements the **Transactional Outbox** pattern for Celery tasks in Django.
Instead of sending tasks directly to the broker (where they can be lost if the transaction rolls back),
tasks are written to a database table within the same transaction as business data.
A separate relay process reads the table and sends tasks to the broker asynchronously.

This guarantees **at-least-once delivery**: if the business transaction commits, the task will eventually be sent.

## Components

```
┌──────────────────────────────────────────────────────────────────┐
│                         APPLICATION                               │
│                                                                   │
│   ┌─────────────┐     ┌─────────────────┐     ┌──────────────┐  │
│   │ Django View │ ──► │ OutboxCelery    │ ──► │ CeleryOutbox │  │
│   │ (Producer)  │     │ .send_task()    │     │ (DB Table)   │  │
│   └─────────────┘     └─────────────────┘     └──────────────┘  │
│                                                       │          │
│                            COMMIT ───────────────────►│          │
└──────────────────────────────────────────────────────────────────┘
                                                        │
                                                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                         RELAY DAEMON                              │
│                                                                   │
│   ┌─────────────────┐     ┌─────────────────┐     ┌───────────┐  │
│   │ MessageSelector │ ──► │ Relay           │ ──► │ Celery    │  │
│   │ (SELECT...SKIP  │     │ ._send_task()   │     │ Broker    │  │
│   │  LOCKED)        │     └─────────────────┘     └───────────┘  │
│   └─────────────────┘              │                             │
│                                    ▼                             │
│                          ┌─────────────────┐                     │
│                          │ Dead Letter     │                     │
│                          │ (on max retry)  │                     │
│                          └─────────────────┘                     │
└──────────────────────────────────────────────────────────────────┘
                                                        │
                                                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                         CELERY WORKER                             │
│                                                                   │
│   ┌─────────────┐     ┌─────────────────┐                        │
│   │ Task        │ ◄── │ Celery Worker   │                        │
│   │ Execution   │     │ (Consumer)      │                        │
│   └─────────────┘     └─────────────────┘                        │
└──────────────────────────────────────────────────────────────────┘
```

## Data Flow

1. **Producer** calls `task.delay()` inside `transaction.atomic()`
2. **OutboxCelery** intercepts and writes to `CeleryOutbox` table
3. **Transaction commits** — task is now visible
4. **Relay** polls table with `SELECT FOR UPDATE SKIP LOCKED`
5. **Relay** sends to broker via `Celery.send_task()`
6. **Worker** executes task

## Database Tables

### celery_outbox

Pending messages waiting for relay:

| Column | Type | Description |
|--------|------|-------------|
| id | BigAutoField | Primary key |
| task_id | CharField(255) | Celery task UUID |
| task_name | CharField(255) | Dotted task name |
| args | JSONField | Positional arguments |
| kwargs | JSONField | Keyword arguments |
| options | JSONField | Task options (serialized) |
| retries | IntegerField | Current retry count |
| retry_after | DateTimeField | Next retry time |
| created_at | DateTimeField | When queued |
| updated_at | DateTimeField | Last attempt timestamp |
| sentry_trace_id | CharField(512) | Sentry trace propagation header |
| sentry_baggage | CharField(2048) | Sentry baggage header |
| structlog_context | TextField | Captured structlog context (JSON) |

### celery_outbox_dead_letter

Failed messages exceeding max retries:

| Column | Type | Description |
|--------|------|-------------|
| id | BigAutoField | Primary key |
| task_id | CharField(255) | Celery task UUID |
| task_name | CharField(255) | Dotted task name |
| args | JSONField | Original arguments |
| kwargs | JSONField | Original keyword arguments |
| options | JSONField | Task options (serialized) |
| retries | IntegerField | Final retry count |
| failure_reason | TextField | Error message |
| created_at | DateTimeField | Original queue time |
| dead_at | DateTimeField | When moved to dead letter |

## Concurrency

Multiple relay instances are safe via `SELECT FOR UPDATE SKIP LOCKED`:

- Each relay locks different rows
- No double-processing
- Scales horizontally

```
  Relay Instance A                    Relay Instance B
┌──────────────────┐                ┌──────────────────┐
│ SELECT ... FOR   │                │ SELECT ... FOR   │
│ UPDATE SKIP      │                │ UPDATE SKIP      │
│ LOCKED           │                │ LOCKED           │
│ -> gets msgs 1-5 │                │ -> gets msgs 6-10│
│ (1-5 are locked) │                │ (1-5 skipped)    │
└──────────────────┘                └──────────────────┘
```

## Two-Transaction Design

The relay deliberately uses two separate transactions with network I/O between them:

```
  Transaction 1           Network I/O           Transaction 2
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ SELECT + lock   │   │ Send to broker  │   │ Update retries  │
│ UPDATE stamp    │──>│ (may be slow)   │──>│ Delete done     │
│ COMMIT (unlock) │   │                 │   │ Move dead letter│
│                 │   │                 │   │ COMMIT          │
└─────────────────┘   └─────────────────┘   └─────────────────┘
```

This avoids holding a database lock open during broker communication, which could take seconds.

The tradeoff: if the process crashes between transaction 1 and 2, sent messages remain in the outbox
and will be re-sent after `retry_after` time. **Consumers must be idempotent.**

## Exponential Backoff

Failed messages are retried with exponential backoff plus random jitter:

```
retry_after = Now() + backoff_time * 2^retries + random(0, backoff_time * 0.1)
```

Example with `backoff_time=120`, `max_retries=5`:

| Attempt | retries | Base delay | Jitter range | Total range |
|---------|---------|------------|--------------|-------------|
| 1st fail | 0 | 120s | 0-12s | 120-132s |
| 2nd fail | 1 | 240s | 0-12s | 240-252s |
| 3rd fail | 2 | 480s | 0-12s | 480-492s |
| 4th fail | 3 | 960s | 0-12s | 960-972s |
| 5th fail | → dead letter | | | |

## Context Propagation

Observability context is captured at `send_task()` time and restored at relay time:

| Context | Captured | Restored as |
|---------|----------|-------------|
| Sentry trace | `sentry_sdk.get_traceparent()` | `sentry-trace` header |
| Sentry baggage | `sentry_sdk.get_baggage()` | `baggage` header |
| structlog | `structlog.contextvars.get_contextvars()` | `bound_contextvars()` |

## Delivery Guarantees

| Scenario | Outcome |
|----------|---------|
| Business transaction rolls back | Task never created in outbox. No delivery. |
| Relay crashes before sending to broker | Message remains in outbox. Recovered after stale timeout (5 min). |
| Relay sends to broker, crashes before TX2 | Message re-sent after backoff. **Duplicate delivery.** |
| Broker rejects message | Relay catches exception, message retried with backoff. |
| Relay max retries exceeded | Message moved to dead letter table. Operator can retry via admin. |

**Delivery semantics: at-least-once.** Consumers must be idempotent.

## Schema Versioning

The outbox uses a `schema_version` field to enable safe format migrations across library upgrades.

### Upgrade Policy

- **N-1 compatibility**: Each version supports deserializing the current and previous schema versions
- **Rolling deployments**: Old relay instances skip messages with newer schema versions (picked up by updated relays)
- **Deprecated versions**: Messages below minimum supported version are skipped

### Behavior

| Relay Version | Message Version | Action |
|--------------|-----------------|--------|
| 1 | 1 | Process normally |
| 2 | 1 | Process (N-1 support) |
| 2 | 2 | Process normally |
| 1 | 2 | Skip (future version) |

## Module Dependency Graph

```
__init__.py (lazy exports)
    │
    ├── app.py (OutboxCelery)
    │     ├── models.py (CeleryOutbox)
    │     ├── serialization.py (serialize_options)
    │     ├── structlog_utils.py (get_structlog_context_json)
    │     └── signals.py (outbox_message_created)
    │
    ├── relay.py (Relay)
    │     ├── models.py (CeleryOutbox, CeleryOutboxDeadLetter)
    │     ├── serialization.py (deserialize_options)
    │     ├── signals.py (outbox_message_sent/failed/dead_lettered)
    │     └── metrics.py (increment, gauge, timing)
    │
    ├── signals.py (Django Signal instances)
    │
    ├── metrics.py (increment, gauge, timing)
    │     └── statsd.py (get_statsd)
    │
    ├── statsd.py (DogStatsd singleton)
    │
    └── management/commands/celery_outbox_relay.py (Command)
          └── relay.py (Relay)

admin.py (standalone, auto-registered)
    └── models.py (CeleryOutbox, CeleryOutboxDeadLetter)
```
