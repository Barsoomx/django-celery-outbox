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

### celery_outbox_batch_processed

**Level:** INFO
**When:** Each processing cycle completes

| Field | Type | Description |
|-------|------|-------------|
| published | int | Messages successfully sent |
| failed | int | Messages that will retry |
| exceeded | int | Messages moved to dead letter |
| queue_depth | int | Pending messages in outbox |

### celery_outbox_relay_idle

**Level:** DEBUG
**When:** Batch size below threshold

No additional fields.

### celery_outbox_relay_busy

**Level:** DEBUG
**When:** Batch at or near capacity

No additional fields.

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

### celery_outbox_signal_error

**Level:** ERROR
**When:** Django signal receiver raises exception

| Field | Type | Description |
|-------|------|-------------|
| signal | str | Signal name |
| task_id | str | Task UUID |
| task_name | str | Task name |

## App Events

### celery_outbox_not_in_transaction

**Level:** WARNING
**When:** send_task called outside database transaction

| Field | Type | Description |
|-------|------|-------------|
| task_name | str | Task name |
| task_id | str | Task UUID |

## Serialization Events

### celery_outbox_signatures_dropped

**Level:** WARNING
**When:** Signatures failed to serialize

| Field | Type | Description |
|-------|------|-------------|
| dropped | int | Number of dropped signatures |
| total | int | Total signatures attempted |
