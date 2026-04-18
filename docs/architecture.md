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
│                         APPLICATION                              │
│                                                                  │
│   ┌─────────────┐     ┌─────────────────┐     ┌──────────────┐   │
│   │ Django View │ ──► │ OutboxCelery    │ ──► │ CeleryOutbox │   │
│   │ (Producer)  │     │ .send_task()    │     │ (DB Table)   │   │
│   └─────────────┘     └─────────────────┘     └──────────────┘   │
│                                                       │          │
│                            COMMIT ───────────────────►│          │
└──────────────────────────────────────────────────────────────────┘
                                                        │
                                                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                         RELAY DAEMON                             │
│                                                                  │
│   ┌─────────────────┐     ┌─────────────────┐     ┌───────────┐  │
│   │ MessageSelector │ ──► │ Relay           │ ──► │ Relay     │  │
│   │ claim batch     │     │ orchestration   │     │ Publisher │  │
│   └─────────────────┘     └─────────────────┘     └─────┬─────┘  │
│                                    │                     │        │
│                                    ▼                     ▼        │
│                          ┌─────────────────┐     ┌───────────┐    │
│                          │ RelayMutations  │     │ Celery    │    │
│                          │ retry/delete/DL │     │ Broker    │    │
│                          └─────────────────┘     └───────────┘    │
└──────────────────────────────────────────────────────────────────┘
                                                        │
                                                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                         CELERY WORKER                            │
│                                                                  │
│   ┌─────────────┐     ┌─────────────────┐                        │
│   │ Task        │ ◄── │ Celery Worker   │                        │
│   │ Execution   │     │ (Consumer)      │                        │
│   └─────────────┘     └─────────────────┘                        │
└──────────────────────────────────────────────────────────────────┘
```

## Data Flow

1. **Producer** calls `OutboxCelery.send_task()` inside `transaction.atomic()`
2. **OutboxCelery** serializes the call and writes to `CeleryOutbox` table
3. **Transaction commits** — task is now visible
4. **Relay.start()** sets up signal handlers and delayed delivery support
5. **MessageSelector** selects pending rows with `SELECT FOR UPDATE SKIP LOCKED` and marks them in-flight
6. **RelayPublisher** restores options, tracing headers, and structlog context, then calls `Celery.send_task()`
7. **RelayMutations** updates retries, deletes published rows, and moves exceeded rows to dead letter
8. **Worker** executes task

## Relay Processing Loop

`Relay` is the public daemon class, but it delegates the batch work to internal collaborators:

- `MessageSelector` owns row selection and in-flight stamping
- `RelayPublisher` owns publish-time option restoration and raw broker send
- `RelayMutations` owns retry, delete, and dead-letter persistence
- `_runtime.py` owns exception classification and traceback logging policy

Conceptually, each batch looks like this:

```
relay.start()
  ├── _setup_signals()
  ├── _setup_delayed_delivery()
  └── while _running:
        └── _processing()
              ├── selector.run()
              ├── publisher.publish(msg) for each selected message
              ├── mutations.update_failed(failed)
              ├── mutations.delete_published(published)
              ├── mutations.move_exceeded_to_dead_letter(exceeded)
              └── metrics, liveness, idle/busy decision
```

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
| redacted_args | JSONField | Redacted positional arguments for inspection |
| redacted_kwargs | JSONField | Redacted keyword arguments for inspection |
| options | JSONField | Task options (serialized) |
| schema_version | SmallIntegerField | Serialized payload format version |
| retries | SmallIntegerField | Current retry count |
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
| redacted_args | JSONField | Redacted positional arguments for inspection |
| redacted_kwargs | JSONField | Redacted keyword arguments for inspection |
| options | JSONField | Task options (serialized) |
| sentry_trace_id | CharField(512) | Sentry trace propagation header |
| sentry_baggage | CharField(2048) | Sentry baggage header |
| structlog_context | TextField | Captured structlog context (JSON) |
| schema_version | SmallIntegerField | Serialized payload format version |
| retries | SmallIntegerField | Final retry count |
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
and will be re-sent after stale-timeout recovery. **Consumers must be idempotent.**

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

Observability context is captured at `send_task()` time and restored by `RelayPublisher` at relay time:

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
| Relay sends to broker, crashes before TX2 | Message re-sent after stale timeout recovery. **Duplicate delivery.** |
| Broker rejects message | Relay catches exception, message retried with backoff. |
| Relay max retries exceeded | Message moved to dead letter table. Operator can retry via admin. |

**Delivery semantics: at-least-once.** Consumers must be idempotent.

## Schema Versioning

The outbox stores a `schema_version` on each row so the relay can reject unsupported payload
formats safely.

Current implementation:

- `CURRENT_SCHEMA_VERSION = 1`
- `MIN_SUPPORTED_VERSION = 1`
- `MessageSelector` only selects rows whose `schema_version` falls within that supported range

Today that means version `1` rows are processed normally, while older or newer versions are
skipped until compatible code is deployed.

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
    ├── relay/ (Relay package)
    │     ├── __init__.py (Relay, RelayConfig exports)
    │     ├── _relay module (Relay orchestration loop)
    │     ├── _config.py (RelayConfig)
    │     ├── _message_selector.py (MessageSelector)
    │     ├── _publisher.py (RelayPublisher)
    │     ├── _mutations.py (RelayMutations)
    │     └── _runtime.py (exception policy)
    │
    ├── signals.py (Django Signal instances)
    │
    ├── metrics.py (increment, gauge, timing)
    │     └── statsd.py (get_statsd)
    │
    ├── statsd.py (DogStatsd singleton)
    │
    └── management/commands/celery_outbox_relay (Command module)
          └── relay (Relay, RelayConfig)

admin.py (standalone, auto-registered)
    └── models.py (CeleryOutbox, CeleryOutboxDeadLetter)
```
