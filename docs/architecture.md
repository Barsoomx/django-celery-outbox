# Architecture

## Overview

`django-celery-outbox` implements the **Transactional Outbox** pattern for Celery tasks in Django.
Instead of sending tasks directly to the broker (where they can be lost if the transaction rolls back),
tasks are written to a database table within the same transaction as business data.
A separate relay process reads the table and sends tasks to the broker asynchronously.

This is designed to provide durable recovery for committed tasks: the outbox row remains available
for relay retry or recovery until it is published or dead-lettered, but end-to-end delivery still
depends on broker acknowledgement semantics.

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
│   ┌─────────────────┐     ┌─────────────────┐     ┌─────────────┐ │
│   │ MessageSelector │ ──► │ Relay           │ ──► │ Relay       │ │
│   │ claim batch     │     │ orchestration   │     │ Publisher   │ │
│   └─────────────────┘     └────────┬────────┘     └──────┬──────┘ │
│                                    │                     │         │
│                     ┌──────────────┴──────────────┐      ▼         │
│                     ▼                             ▼  ┌───────────┐ │
│          ┌─────────────────┐           ┌────────────────────────┐  │
│          │ RelayMutations  │           │ RelayPolicy            │  │
│          │ retry/delete/DL │           │ outage/shutdown policy │  │
│          └─────────────────┘           └────────────────────────┘  │
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
5. **RelayPolicy** decides whether a process-local breaker cooldown should skip the next batch
6. **MessageSelector** selects pending rows with `SELECT FOR UPDATE SKIP LOCKED` and marks them in-flight
7. **RelayPublisher** restores options, tracing headers, and structlog context, then calls `Celery.send_task()` with `--send-timeout`
8. **RelayPolicy** classifies broker outages, tracks consecutive-outage breaker state, and enforces the shutdown deadline
9. **RelayMutations** updates retries, deletes published rows, moves exceeded rows to dead letter, and defers broker-outage rows without incrementing retries
10. **Worker** executes task

## Relay Processing Loop

`Relay` is the public daemon class, but it delegates the batch work to internal collaborators:

- `MessageSelector` owns row selection and in-flight stamping
- `RelayPublisher` owns publish-time option restoration and raw broker send
- `RelayMutations` owns retry, delete, and dead-letter persistence
- `_policy.py` owns broker-outage classification, process-local breaker state, and shutdown deadlines
- `_runtime.py` owns exception classification and traceback logging policy

Conceptually, each batch looks like this:

```
relay.start()
  ├── _setup_signals()
  ├── _setup_delayed_delivery()
  └── while _running:
        └── _processing()
              ├── policy.should_skip_batch()
              ├── selector.run()
              ├── publisher.publish(msg) for each selected message
              ├── policy.record_success()/record_outage()/shutdown_deadline_exceeded()
              ├── mutations.update_failed(failed)
              ├── mutations.delete_published(published)
              ├── mutations.move_exceeded_to_dead_letter(exceeded)
              ├── mutations.defer_due_to_outage(deferred_due_to_outage)
              └── metrics, liveness, idle/busy decision
```

## Relay Command

```bash
python manage.py celery_outbox_relay \
  --batch-size 100 \
  --idle-time 1.0 \
  --backoff-time 120 \
  --max-retries 5 \
  --stale-timeout-seconds 300 \
  --send-timeout 10.0 \
  --shutdown-timeout 30.0 \
  --broker-outage-cooldown 30.0 \
  --max-backoff 3600.0 \
  --liveness-file /tmp/celery-outbox-alive
```

## Operational Helpers

- `DjangoCeleryOutboxConfig.ready()` registers Django system checks that validate supported database backends, required and importable `CELERY_OUTBOX_APP`, valid `CELERY_OUTBOX_EXCLUDE_TASKS`, and applied outbox migrations before runtime.
- `celery_outbox_stats` reports `queue_depth`, `dlq_count`, `oldest_pending_seconds`, and `top_failing`, with `--format` and `--top` options.
- `celery_outbox_purge_dead_letter` and the shared task `django_celery_outbox.tasks.purge_dead_letter` share the same purge core and can read `CELERY_OUTBOX_DLQ_RETENTION`.
- A packaged pytest plugin is auto-discovered through `pytest11` and exposes `outbox`, `assert_task_sent`, `fake_relay`, and `drain_outbox()`.

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
| redacted_args | JSONField | Optional sanitized positional arguments for inspection; falls back to original when `NULL` |
| redacted_kwargs | JSONField | Optional sanitized keyword arguments for inspection; falls back to original when `NULL` |
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
| redacted_args | JSONField | Optional sanitized positional arguments for inspection; falls back to original when `NULL` |
| redacted_kwargs | JSONField | Optional sanitized keyword arguments for inspection; falls back to original when `NULL` |
| options | JSONField | Task options (serialized) |
| sentry_trace_id | CharField(512) | Sentry trace propagation header |
| sentry_baggage | CharField(2048) | Sentry baggage header |
| structlog_context | TextField | Captured structlog context (JSON) |
| schema_version | SmallIntegerField | Serialized payload format version |
| retries | SmallIntegerField | Final retry count |
| failure_reason | TextField | Dead-letter reason string, e.g. `max retries exceeded` |
| created_at | DateTimeField | Original queue time |
| dead_at | DateTimeField | When moved to dead letter |

## Concurrency

Multiple relay instances can coordinate claims via `SELECT FOR UPDATE SKIP LOCKED`:

- Each relay locks different rows
- Prevents simultaneous claims on the same row while it stays locked or within the stale-timeout window
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
and become eligible for reclaim after `--stale-timeout-seconds` recovery (default: `300` seconds).
If publish already succeeded, that reclaim can lead to a resend. **Consumers must be idempotent.**

## Outage Policy and Graceful Shutdown

`RelayPolicy` is the control layer for outage handling and draining mode:

- `--send-timeout` bounds a single `Celery.send_task()` publish attempt.
- Two consecutive broker outages in one batch open a process-local breaker for `--broker-outage-cooldown`.
- Broker-outage deferral does not increment `retries` and does not consume `--max-retries`.
- `SIGTERM` or `SIGINT` starts draining mode.
- The relay stops starting new sends after `--shutdown-timeout`.
- Already-selected but not-yet-started rows recover later through `--stale-timeout-seconds` reclaim.

## Exponential Backoff

Failed messages are retried with exponential backoff plus random jitter:

```
retry_after = Now() + min(backoff_time * 2^retries + random(0, backoff_time * 0.1), max_backoff)
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
| structlog | `structlog.contextvars.get_contextvars()` | `bound_contextvars()` inside the relay publish path |

## Delivery Guarantees

| Scenario | Outcome |
|----------|---------|
| Business transaction rolls back | Task never created in outbox. No delivery. |
| Relay crashes before sending to broker | Message remains in outbox and becomes eligible for reclaim after `--stale-timeout-seconds` (default: `300s`). |
| Relay sends to broker, crashes before TX2 | Message may be re-sent after stale-timeout reclaim. **Duplicate delivery is possible.** |
| Broker outage or publish timeout | Selected rows are deferred by `--broker-outage-cooldown`; retries are not incremented, and a process-local breaker may pause the next batch attempt. |
| Ordinary publish failure | Relay catches the exception, increments retries, and applies exponential backoff capped by `--max-backoff`. |
| Broker fails silently (no publisher confirms) | Message may still be lost after the relay deletes the outbox row. Stronger guarantees require broker confirms. |
| Relay max retries exceeded | Message moved to dead letter table. Operator can retry via admin. |

**Delivery semantics:** duplicate-tolerant recovery with broker-confirm caveats, not an
unconditional end-to-end at-least-once guarantee. Consumers must be idempotent.

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
    ├── apps.py
    │     └── checks.py (Django system checks)
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
    │     ├── _policy.py (outage classification, breaker, shutdown policy)
    │     └── _runtime.py (exception policy)
    │
    ├── signals.py (Django Signal instances)
    │
    ├── fixtures.py (pytest plugin helpers)
    │
    ├── metrics.py (increment, gauge, timing)
    │     └── statsd.py (get_statsd)
    │
    ├── stats.py (queue statistics)
    ├── purge.py (dead-letter purge core)
    ├── tasks.py (shared purge task)
    │
    ├── statsd.py (DogStatsd singleton)
    │
    └── management/commands/
          ├── celery_outbox_relay (Relay command)
          ├── celery_outbox_stats (operator stats command)
          └── celery_outbox_purge_dead_letter (DLQ purge command)

admin.py (standalone, auto-registered)
    └── models.py (CeleryOutbox, CeleryOutboxDeadLetter)
```
