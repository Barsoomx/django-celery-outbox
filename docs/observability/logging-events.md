# Logging Events Reference

This document defines the stable logging events emitted by django-celery-outbox.
Event names and field schemas are part of the public API.

## Relay Events

### celery_outbox_relay_started

**Level:** INFO
**When:** Relay daemon starts

| Field | Type | Description |
|-------|------|-------------|
| batch_size | int | Batch processing size |
| idle_time | float | Seconds to sleep when idle |
| backoff_time | int | Base retry backoff in seconds |
| max_retries | int | Maximum retry attempts |

### celery_outbox_delayed_delivery_setup

**Level:** INFO
**When:** Relay successfully declares native delayed delivery exchanges at startup

| Field | Type | Description |
|-------|------|-------------|
| queue_type | str | Queue type used (e.g., `quorum`) |

### celery_outbox_delayed_delivery_setup_failed

**Level:** WARNING
**When:** Relay fails to declare delayed delivery exchanges (non-fatal, countdown/eta may not work)

| Field | Type | Description |
|-------|------|-------------|
| exception_type | str | Exception class name |
| exception_message | str | Exception message |

### celery_outbox_relay_shutdown

**Level:** INFO
**When:** Relay receives SIGTERM/SIGINT

| Field | Type | Description |
|-------|------|-------------|
| signal | int | Signal number (15=SIGTERM, 2=SIGINT) |

### celery_outbox_relay_breaker_open

**Level:** WARNING
**When:** A broker-outage cooldown suppresses the next batch attempt

| Field | Type | Description |
|-------|------|-------------|
| cooldown_seconds | float | Seconds remaining before the relay retries a batch |

Treat this as "relay alive but broker unavailable." It should route differently from process-down alerts.

### celery_outbox_relay_breaker_trip

**Level:** WARNING
**When:** A second consecutive broker outage without an intervening successful publish opens the process-local breaker

| Field | Type | Description |
|-------|------|-------------|
| deferred_count | int | Selected rows deferred by outage handling in this batch |
| exception_type | str | Broker-outage exception class name |
| exception_message | str | Exception message |

### celery_outbox_batch_processed

**Level:** INFO
**When:** Each processing cycle completes

| Field | Type | Description |
|-------|------|-------------|
| published | int | Messages successfully sent |
| failed | int | Messages that will retry |
| exceeded | int | Messages moved to dead letter |
| deferred_due_to_outage | int | Selected rows deferred by broker-outage handling |
| shutdown_aborted | int | Selected rows left untouched because shutdown deadline was reached |
| queue_depth | int | Pending messages in outbox |

### celery_outbox_relay_shutdown_deadline_exceeded

**Level:** WARNING
**When:** Draining mode stops the relay from starting more sends in the current batch

| Field | Type | Description |
|-------|------|-------------|
| aborted_count | int | Number of selected rows left unstarted in this batch |
| aborted_task_ids | list[str] | Task IDs of the aborted rows |
| aborted_task_names | list[str] | Task names of the aborted rows |

### celery_outbox_relay_idle

**Level:** DEBUG
**When:** Batch size below threshold

No additional fields.

### celery_outbox_relay_busy

**Level:** DEBUG
**When:** Batch at or near capacity

No additional fields.

### celery_outbox_relay_iteration_failed

**Level:** ERROR
**When:** The top-level relay loop catches an unexpected exception, records it, and retries after the idle sleep

| Field | Type | Description |
|-------|------|-------------|
| exception_type | str | Exception class name |
| exception_message | str | Exception message |

### celery_outbox_send_failed

**Level:** ERROR
**When:** Message send fails (will retry)

| Field | Type | Description |
|-------|------|-------------|
| outbox_id | int | Database ID of message |
| task_name | str | Celery task name |
| task_id | str | Celery task UUID |
| retries | int | Current retry count |
| exception_type | str | Exception category |
| exception_message | str | Exception message |

### celery_outbox_max_retries_exceeded

**Level:** WARNING
**When:** Message exceeds max retries, moved to DLQ

| Field | Type | Description |
|-------|------|-------------|
| exception_type | str | `pre_exceeded` if already exceeded before send, or exception category |
| exception_message | str | Details about the exceeded condition |

**Note:** Two scenarios trigger this event:

1. **Pre-send exceeded:** Message was already at max retries when relay picked it up (e.g., after restart). `exception_type='pre_exceeded'`.
2. **Post-send exceeded:** Send attempt failed on the last allowed retry. `exception_type` contains the actual exception category.

`celery_outbox_relay_iteration_failed` is the catch-all relay-loop failure event. Wire it into your log-alerting stack.

## App Events

### celery_outbox_not_in_transaction

**Level:** WARNING
**When:** send_task called outside database transaction

| Field | Type | Description |
|-------|------|-------------|
| task_name | str | Task name |
| task_id | str | Task UUID |

### celery_outbox_signal_error

**Level:** ERROR
**When:** A package-owned Django signal receiver raises an exception; enqueue/relay continues because signals use `send_robust()`

| Field | Type | Description |
|-------|------|-------------|
| signal | str | Signal name passed to `_send_signal_safe()` |
| task_id | str | Task UUID |
| task_name | str | Task name |
| receiver | str | Receiver `__qualname__` or repr used in the log |

### celery_outbox_metric_error

**Level:** WARNING
**When:** Producer-side metric emission fails during `messages.enqueued`

| Field | Type | Description |
|-------|------|-------------|
| metric | str | Metric name that failed to emit |
| task_name | str | Task name being enqueued |

## Inspection Events

### celery_outbox_inspection_redaction_failed

**Level:** WARNING
**When:** Admin/debug inspection redaction fails and the package falls back to stored raw `options`

| Field | Type | Description |
|-------|------|-------------|
| task_name | str | Task whose inspection payload could not be redacted |

## Serialization Events

### celery_outbox_signatures_dropped

**Level:** WARNING
**When:** Signatures failed to serialize

| Field | Type | Description |
|-------|------|-------------|
| dropped | int | Number of dropped signatures |
| total | int | Total signatures attempted |

## Purge Events

### celery_outbox_dead_letter_purged

**Level:** INFO
**When:** Dead-letter purge logic finishes, including dry runs

| Field | Type | Description |
|-------|------|-------------|
| deleted_count | int | Number of rows matched for deletion |
| dry_run | bool | Whether the purge only reported matches |
| older_than_dead | str \| null | Effective `dead_at` retention window |
| older_than_created | str \| null | Effective `created_at` retention window |
| task_name_pattern | str \| null | Effective task-name glob filter |
