# Architecture

## Overview

`django-celery-outbox` implements the **Transactional Outbox** pattern for Celery tasks in Django.
Instead of sending tasks directly to the broker (where they can be lost if the transaction rolls back),
tasks are written to a database table within the same transaction as business data.
A separate relay process reads the table and sends tasks to the broker asynchronously.

This guarantees **at-least-once delivery**: if the business transaction commits, the task will eventually be sent.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Django Application                       │
│                                                                 │
│   ┌──────────────┐    transaction.atomic()    ┌──────────────┐  │
│   │ Business     │ ──────────────────────────>│ CeleryOutbox │  │
│   │ Logic        │  OutboxCelery.send_task()  │ (DB table)   │  │
│   │              │                            │              │  │
│   │ Order.save() │ ── same transaction ──────>│ INSERT INTO  │  │
│   └──────────────┘                            │ celery_outbox│  │
│                                               └──────┬───────┘  │
└──────────────────────────────────────────────────────┼──────────┘
                                                       │
                              ┌────────────────────────┘
                              │ Relay reads pending messages
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Relay Process (daemon)                      │
│                                                                 │
│   ┌──────────────┐                            ┌──────────────┐  │
│   │ SELECT       │    Celery.send_task()      │ RabbitMQ /   │  │
│   │ FOR UPDATE   │ ─────────────────────────> │ Redis /      │  │
│   │ SKIP LOCKED  │                            │ Broker       │  │
│   └──────────────┘                            └──────┬───────┘  │
│         │                                            │          │
│         │ DELETE sent messages                       ▼          │
│         │ UPDATE failed retries              ┌───────────────┐  │
│         │ MOVE exceeded → dead letter        │ Celery Worker │  │
│         └───────────────────────────────────>│ executes task │  │
│                                              └───────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. OutboxCelery (`app.py`)

Drop-in replacement for `celery.Celery`. Overrides `send_task()` to intercept task calls
and write them to the outbox table instead of sending directly to the broker.

```
OutboxCelery.send_task(name, args, kwargs, **options)
        │
        ├── Is task in CELERY_OUTBOX_EXCLUDE_TASKS?
        │       YES ──> super().send_task() ──> directly to broker
        │       NO  ──┐
        │             ▼
        ├── Generate task_id (uuid)
        ├── _collect_options() ──> merge explicit params + **options
        ├── serialize_options() ──> convert Signatures, datetime, kombu objects to JSON-safe
        ├── Capture context:
        │       ├── sentry_sdk.get_traceparent()
        │       ├── sentry_sdk.get_baggage()
        │       └── get_structlog_context_json()
        ├── Check: connections[CeleryOutbox.objects.db].in_atomic_block
        │       NO ──> log warning 'celery_outbox_not_in_transaction'
        ├── CeleryOutbox.objects.create(...)
        ├── outbox_message_created signal ──> (sender=OutboxCelery, task_id, task_name)
        └── Return AsyncResult(task_id)
```

Key design decisions:
- **Multi-DB aware**: checks `in_atomic_block` on the correct database connection
- **Exclude list**: `CELERY_OUTBOX_EXCLUDE_TASKS` setting bypasses outbox for specific tasks
- **Context propagation**: captures Sentry trace + structlog context at call time
- **Signal emission**: fires `outbox_message_created` after inserting the row

### 2. Models (`models.py`)

#### CeleryOutbox

Database table storing pending tasks.

```
┌──────────────────────────────────────────────────────────┐
│                   celery_outbox table                    │
├──────────────────────┬───────────────────────────────────┤
│ id                   │ BigAutoField (PK)                 │
│ created_at           │ DateTimeField (auto_now_add)      │
│ updated_at           │ DateTimeField (nullable)          │
│ retries              │ SmallIntegerField (default=0)     │
│ retry_after          │ DateTimeField (nullable, indexed) │
│ task_id              │ CharField[255] (indexed)          │
│ task_name            │ CharField[255] (indexed)          │
│ args                 │ JSONField (list)                  │
│ kwargs               │ JSONField (dict)                  │
│ options              │ JSONField (dict)                  │
│ sentry_trace_id      │ CharField[512] (nullable)         │
│ sentry_baggage       │ CharField[2048] (nullable)        │
│ structlog_context    │ TextField (nullable)              │
├──────────────────────┴───────────────────────────────────┤
│ Indexes:                                                 │
│   celery_outbox_pending_idx  (id) WHERE updated_at NULL  │
│   retry_after                (B-tree index)              │
└──────────────────────────────────────────────────────────┘
```

- `updated_at = NULL` means "never attempted" (fresh message)
- `updated_at = <timestamp>` means "in progress or failed"
- `retry_after` stores the next eligible retry time (exponential backoff)
- `retries` tracks how many times sending failed
- `sentry_trace_id` and `sentry_baggage` are `CharField` (not `TextField`) with explicit `max_length`

#### CeleryOutboxDeadLetter

Stores messages that exceeded the maximum retry count. Preserves the full message
payload so that operators can inspect failures and retry via admin.

```
┌──────────────────────────────────────────────────────────┐
│               celery_outbox_dead_letter table            │
├──────────────────────┬───────────────────────────────────┤
│ id                   │ BigAutoField (PK)                 │
│ created_at           │ DateTimeField (original creation) │
│ dead_at              │ DateTimeField (auto_now_add)      │
│ retries              │ SmallIntegerField (default=0)     │
│ task_id              │ CharField[255] (indexed)          │
│ task_name            │ CharField[255] (indexed)          │
│ args                 │ JSONField (list)                  │
│ kwargs               │ JSONField (dict)                  │
│ options              │ JSONField (dict)                  │
│ sentry_trace_id      │ CharField[512] (nullable)         │
│ sentry_baggage       │ CharField[2048] (nullable)        │
│ structlog_context    │ TextField (nullable)              │
│ failure_reason       │ TextField (nullable)              │
└──────────────────────────────────────────────────────────┘
```

- `created_at` is copied from the original outbox message (not auto-generated)
- `dead_at` is auto-set when the dead letter row is created
- `failure_reason` stores why the message was moved (e.g. `'max retries exceeded'`)

### 3. Relay (`relay.py`)

Daemon process that reads the outbox table and sends tasks to the broker.
Runs as a Django management command.

#### Processing Loop

```
relay.start()
    │
    ├── _setup_signals()    # SIGTERM/SIGINT -> _running = False
    ├── log 'celery_outbox_relay_started'
    │
    └── while _running:
            │
            _processing()
                │
                ├── close_old_connections()
                │
                ├── ┌─── Transaction 1 ────────────────────────┐
                │   │ messages = _select_messages()            │
                │   │   SELECT ... FOR UPDATE SKIP LOCKED      │
                │   │   WHERE updated_at IS NULL               │
                │   │      OR retry_after <= Now()             │
                │   │      OR (updated_at <= Now()-5min        │
                │   │          AND retry_after IS NULL)        │
                │   │   ORDER BY id ASC                        │
                │   │   LIMIT batch_size                       │
                │   │                                          │
                │   │ UPDATE ... SET updated_at = Now()        │
                │   │   (mark as "in progress")                │
                │   └──────────────────────────────────────────┘
                │
                ├── _process_messages(messages)    # Network I/O
                │       │
                │       │   for each message:
                │       │       │
                │       │       ├── retries >= max_retries?
                │       │       │       YES -> exceeded[]
                │       │       │              increment('messages.exceeded')
                │       │       │       NO  ──┐
                │       │       │             ▼
                │       │       ├── try: _send_task(msg)
                │       │       │       │
                │       │       │       ├── deserialize_options()
                │       │       │       ├── Restore headers (sentry-trace, baggage)
                │       │       │       ├── Parse structlog context
                │       │       │       └── Celery.send_task() -> broker
                │       │       │
                │       │       ├── else (Success) -> published[]
                │       │       │       increment('messages.published')
                │       │       │       _send_signal_safe(outbox_message_sent)
                │       │       │
                │       │       └── except (Failure) -> retries >= max-1?
                │       │               YES -> exceeded[]
                │       │                      increment('messages.exceeded')
                │       │               NO  -> failed[]
                │       │                      increment('messages.failed')
                │       │                      _send_signal_safe(outbox_message_failed)
                │       │
                │       └── return (published, failed, exceeded)
                │
                ├── close_old_connections()
                │
                ├── ┌─── Transaction 2 ────────────────────────┐
                │   │ _update_failed(failed)                   │
                │   │   UPDATE SET retries = retries + 1,      │
                │   │              updated_at = Now(),         │
                │   │              retry_after = <exp backoff> │
                │   │                                          │
                │   │ _delete_done(published)                  │
                │   │   DELETE WHERE id IN (...)               │
                │   │                                          │
                │   │ _move_to_dead_letter(exceeded)           │
                │   │   INSERT INTO celery_outbox_dead_letter  │
                │   │   DELETE FROM celery_outbox              │
                │   │   _send_signal_safe(dead_lettered)       │
                │   └──────────────────────────────────────────┘
                │
                ├── gauge('queue.depth', CeleryOutbox.objects.count())
                ├── gauge('dead_letter.count', CeleryOutboxDeadLetter.objects.count())
                ├── timing('batch.duration_ms', elapsed_ms)
                ├── log 'celery_outbox_batch_processed'
                │
                ├── _touch_liveness()
                │       Path(liveness_file).touch() if configured
                │
                └── batch < batch_size?
                        YES -> sleep(idle_time)
                        NO  -> continue immediately
```

#### Two-Transaction Design

The relay deliberately uses **two separate transactions** with network I/O between them:

```
  Transaction 1           Network I/O           Transaction 2
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ SELECT + lock   │   │ Send to broker  │   │ Update retries  │
│ UPDATE stamp    │──>│ (may be slow)   │──>│ Delete done     │
│ COMMIT (unlock) │   │                 │   │ Move dead letter│
│                 │   │                 │   │ COMMIT          │
└─────────────────┘   └─────────────────┘   └─────────────────┘
```

Why not one transaction?
- Holding a transaction open during broker communication (potentially seconds)
  wastes DB connections and increases lock contention
- If the broker is slow or down, the DB lock would be held for the entire retry/timeout

Tradeoff:
- If the process crashes between transaction 1 and 2, sent messages remain in the outbox
  and will be re-sent after `retry_after` time (at-least-once delivery)
- Consumers **must be idempotent**

#### Database-side Now()

All `updated_at` and `retry_after` assignments in ORM `update()` calls use Django's `Now()`
database function instead of Python's `datetime.now()`. This ensures timestamps are consistent
with the database clock, which matters when relay instances run on different hosts.

`retry_after` is calculated as `Now() + timedelta(...)`, producing a database-side expression.

#### Concurrent Relay Instances

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

`SKIP LOCKED` ensures multiple relay instances process different messages without conflicts.

#### Exponential Backoff with Jitter

Failed messages are retried with exponential backoff. The `retry_after` field stores the next
eligible time for each message.

Formula:

```
retry_after = Now() + backoff_time * 2^retries + random(0, backoff_time * 0.1)
```

- `Now()` uses the database clock (not Python's `datetime.now()`)
- `backoff_time` is the base delay in seconds (default: 120)
- `2^retries` doubles the delay on each failure
- Random jitter (up to 10% of `backoff_time`) prevents thundering herd

Example with `backoff_time=120`, `max_retries=5`:

```
  Attempt   retries   Base delay     Jitter range     Total range
  ───────   ───────   ──────────     ────────────     ───────────
  1st fail  0         120s           0-12s            120-132s
  2nd fail  1         240s           0-12s            240-252s
  3rd fail  2         480s           0-12s            480-492s
  4th fail  3         960s           0-12s            960-972s
  5th fail  -> dead letter
```

The `_select_messages()` query filters messages by:

```python
Q(updated_at__isnull=True)
| Q(retry_after__lte=Now())
| Q(updated_at__lte=Now() - _STALE_TIMEOUT, retry_after__isnull=True)
```

This means a message is eligible when:
- It has never been attempted (`updated_at IS NULL`), or
- Its backoff period has elapsed (`retry_after <= database now`), or
- It is stale: picked up > 5 minutes ago but never got a `retry_after` (crashed relay recovery)

The stale timeout (`_STALE_TIMEOUT = 5 minutes`) prevents in-flight messages (between TX1 and TX2)
from being picked up by another relay instance, which would cause duplicate task execution.

#### Retry Flow (with Dead Letter)

```
Message lifecycle:
                                  max_retries = 5
  ┌────────┐
  │ created│  retries=0, updated_at=NULL, retry_after=NULL
  └───┬────┘
      │ Relay picks up
      ▼
  ┌────────┐
  │ send   │──── success ──> DELETE (done)
  │attempt │                 signal: outbox_message_sent
  └───┬────┘
      │ failure
      ▼
  retries=1, updated_at=Now(), retry_after=now+120s+jitter
  signal: outbox_message_failed
  (wait for retry_after)
      │
      ▼
  ┌────────┐
  │ send   │──── success ──> DELETE (done)
  │attempt │
  └───┬────┘
      │ failure
      ▼
  retries=2, updated_at=Now(), retry_after=now+240s+jitter
  (wait for retry_after)
      │
      ▼
  ... (continues with exponential backoff) ...
      │
      ▼
  retries >= max_retries
  log 'celery_outbox_max_retries_exceeded'
      │
      ▼
  ┌───────────────────────────────────────────┐
  │ _move_to_dead_letter()                    │
  │   INSERT INTO celery_outbox_dead_letter   │
  │     (copies all fields + failure_reason)  │
  │   DELETE FROM celery_outbox               │
  │   signal: outbox_message_dead_lettered    │
  └───────────────────────────────────────────┘
```

Messages are **never silently deleted**. Failed messages that exceed retries are moved to the
dead letter table where operators can inspect them and retry via admin.

### 4. Serialization (`serialization.py`)

Handles conversion between Python/Celery objects and JSON-safe dicts for database storage.

```
                    serialize_options()
                    (at send_task time)
┌─────────────────────────────────────────────────┐
│                                                 │
│  countdown: 60 ────────> eta: "2026-01-01T..."  │
│  eta: datetime ────────> eta: "ISO string"      │
│  expires: datetime ───> expires: "ISO string"   │
│  expires: int ────────> expires: 300 (as-is)    │
│                                                 │
│  link: Signature ─────> link: [dict(sig)]       │
│  link_error: [Sig] ──> link_error: [dict, ...]  │
│  chain: [Sig] ───────> chain: [dict, ...]       │
│  chord: Signature ───> chord: dict(sig)         │
│                                                 │
│  queue: KombuQueue ──> queue: "queue_name"      │
│  exchange: KombuExch > exchange: "exch_name"    │
│                                                 │
│  _TRANSIENT_KEYS ────> DROPPED (producer,       │
│                        connection, app, etc.)   │
│  None values ────────> DROPPED                  │
└─────────────────────────────────────────────────┘

                    deserialize_options()
                    (at relay send time)
┌─────────────────────────────────────────────────┐
│                                                 │
│  eta: "ISO string" ──> eta: datetime            │
│  expires: "ISO str" ─> expires: datetime        │
│  expires: 300 ───────> expires: 300 (as-is)     │
│                                                 │
│  link: [dict, ...] ──> link: [Signature, ...]   │
│  chain: [dict, ...] ─> chain: [Signature, ...]  │
│  chord: dict ────────> chord: Signature         │
│                                                 │
│  other keys ─────────> passed through as-is     │
└─────────────────────────────────────────────────┘
```

### 5. Context Propagation

The outbox captures observability context at `send_task` time and restores it at relay time.

```
  send_task() time                              relay _send_task() time
┌───────────────────┐                         ┌───────────────────────┐
│                   │                         │                       │
│ sentry_sdk        │                         │ headers:              │
│  .get_traceparent │──> sentry_trace_id ────>│  sentry-trace: "..."  │
│  .get_baggage()   │──> sentry_baggage ─────>│  baggage: "..."       │
│                   │                         │                       │
│ structlog         │                         │ structlog.contextvars │
│  .contextvars     │                         │  .bound_contextvars(  │
│  .get_contextvars │──> structlog_context ──>│    request_id='abc',  │
│                   │    (JSON string)        │    user_id=42,        │
│                   │                         │  )                    │
└───────────────────┘                         └───────────────────────┘
```

structlog context capture is configurable:
- `CELERY_OUTBOX_STRUCTLOG_ENABLED = False` disables capture entirely
- `CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS = ['request_id']` captures only specified keys

### 6. Django Signals (`signals.py`)

Four signals are emitted at different points of the message lifecycle.

All relay signals are sent via `_send_signal_safe()` which wraps the call in try/except —
if a signal receiver raises an exception, the error is logged but the relay continues processing.
This prevents user code from crashing the relay daemon.

```
  outbox_message_created        Emitted in: app.py (OutboxCelery.send_task)
  │  sender=OutboxCelery        After CeleryOutbox.objects.create()
  │  task_id, task_name         (NOT wrapped — propagates to caller)
  │
  outbox_message_sent           Emitted in: relay.py (_process_messages, else block)
  │  sender=Relay               After successful _send_task()
  │  task_id, task_name         (wrapped in _send_signal_safe)
  │
  outbox_message_failed         Emitted in: relay.py (_process_messages, except block)
  │  sender=Relay               After failed _send_task(), when retries remain
  │  task_id, task_name,        (wrapped in _send_signal_safe)
  │  retries
  │
  outbox_message_dead_lettered  Emitted in: relay.py (_move_to_dead_letter)
     sender=Relay               After bulk_create into dead letter table
     task_id, task_name,        (wrapped in _send_signal_safe, per message)
     task_ids, task_names
```

Usage example:

```python
from django_celery_outbox.signals import outbox_message_failed

def on_message_failed(sender, task_id, task_name, retries, **kwargs):
    logger.warning('Task failed', task_id=task_id, retries=retries)

outbox_message_failed.connect(on_message_failed)
```

### 7. StatsD Metrics (`statsd.py`, `metrics.py`)

#### statsd.py -- DogStatsd Singleton

Lazily creates a `DogStatsd` client configured from Django settings:

```
get_statsd()
    │
    ├── host:      MONITORING_STATSD_HOST      (default: 'localhost')
    ├── port:      MONITORING_STATSD_PORT      (default: 9125)
    ├── namespace: MONITORING_STATSD_PREFIX    (default: 'celery_outbox')
    └── tags:      MONITORING_STATSD_TAGS      (default: {})
                   dict -> ['k:v', ...] constant tags
```

#### metrics.py -- Wrapper Functions

Thin wrappers that check `MONITORING_METRICS_ENABLED` (default: `True`) before emitting:

- `increment(name, value=1, tags=None)` -- counter
- `gauge(name, value, tags=None)` -- gauge
- `timing(name, value_ms, tags=None)` -- timing in milliseconds

Tags are passed as `dict[str, str]` and converted to `['k:v']` format.

#### Metrics Emitted in Relay

| Metric | Type | Tags | Where |
|--------|------|------|-------|
| `messages.published` | increment | `task_name` | After successful send |
| `messages.failed` | increment | `task_name` | After failed send (retries remain) |
| `messages.exceeded` | increment | `task_name` | When max retries exceeded |
| `queue.depth` | gauge | -- | End of each batch (total outbox count) |
| `dead_letter.count` | gauge | -- | End of each batch (total dead letter count) |
| `batch.duration_ms` | timing | -- | End of each batch (wall clock ms) |

All metrics are prefixed with the `MONITORING_STATSD_PREFIX` namespace (default: `celery_outbox`).

#### k8s / DogStatsD Configuration

Typical Kubernetes setup with a DogStatsD sidecar or host agent:

```python
MONITORING_STATSD_HOST = os.environ.get('DD_AGENT_HOST', 'localhost')
MONITORING_STATSD_PORT = int(os.environ.get('DD_DOGSTATSD_PORT', 9125))
MONITORING_STATSD_PREFIX = 'celery_outbox'
MONITORING_STATSD_TAGS = {
    'service': 'my-service',
    'env': os.environ.get('ENV', 'dev'),
}
```

### 8. Liveness Probe (file-based, for k8s)

The relay supports a file-based liveness probe via the `--liveness-file` argument. After each
`_processing()` cycle, the relay calls `_touch_liveness()`, which does `Path(liveness_file).touch()`
if the file path is configured.

Kubernetes `livenessProbe` example:

```yaml
livenessProbe:
  exec:
    command:
      - sh
      - -c
      - '[ $(( $(date +%s) - $(stat -c %Y /tmp/celery-outbox-alive) )) -lt 30 ]'
  initialDelaySeconds: 10
  periodSeconds: 10
```

The probe checks whether the file was modified within the last 30 seconds. If the relay hangs
or crashes, the file stops being updated and Kubernetes restarts the pod.

If `liveness_file` is `None` (default), the method is a no-op.

### 9. Management Command (`celery_outbox_relay`)

```bash
$ python manage.py celery_outbox_relay \
    --batch-size 100 \
    --idle-time 1.0 \
    --backoff-time 120 \
    --max-retries 5 \
    --liveness-file /tmp/celery-outbox-alive
```
```
    │
    ├── _get_celery_app()
    │       reads CELERY_OUTBOX_APP setting
    │       e.g. 'myproject.celery.app'
    │       importlib.import_module() + getattr()
    │
    └── Relay(app=..., batch_size=..., liveness_file=..., ...).start()
```

### 10. Admin (`admin.py`)

#### CeleryOutboxAdmin

Read-only Django admin interface for the outbox queue. All permissions (add, change, delete)
are disabled.

Custom `changelist_view` injects batch summary stats into the template context:

| Context variable | Value |
|-----------------|-------|
| `pending_count` | Messages with `updated_at IS NULL` |
| `failed_count` | Messages with `retries > 0` |
| `total_count` | Total outbox messages |
| `oldest_pending` | `timedelta` since the oldest pending message |

Uses a custom template: `admin/django_celery_outbox/celeryoutbox/change_list.html`.

Action: **reset_retries** -- Sets `retries=0`, `retry_after=NULL`, `updated_at=NULL` for
selected messages, making them eligible for immediate reprocessing.

#### CeleryOutboxDeadLetterAdmin

Read-only admin for the dead letter table.

Action: **retry_selected** -- Atomically (`transaction.atomic`) copies selected dead-lettered
messages back to the outbox table via `bulk_create` (with `retries=0`) and deletes them from
the dead letter table. This re-enqueues them for the relay to process.

## Data Flow: Complete Lifecycle

```
 1. Application code                        2. Database
 ─────────────────                          ────────────

 with transaction.atomic():
   order = Order.objects.create(...)
   app.send_task(                       ┌─────────────────┐
     'process_order',                   │ INSERT INTO     │
     args=[order.id],             ───>  │ celery_outbox   │
   )                                    │ (task_id,       │
   # COMMIT                             │  task_name,     │
                                        │  args, kwargs,  │
 --> signal: outbox_message_created     │  options,       │
                                        │  sentry_*,      │
                                        │  structlog_ctx) │
                                        └────────┬────────┘
                                                 │
 3. Relay daemon                                 │
 ───────────────                                 │
                                                 │
 _processing():                                  │
   close_old_connections()                       │
   ┌─ TX1 ──────────────────────┐                │
   │ SELECT ... FOR UPDATE  <───┼────────────────┘
   │   SKIP LOCKED              │
   │   WHERE updated_at IS NULL │
   │     OR retry_after <= Now  │
   │     OR (stale > 5min AND   │
   │         retry_after NULL)  │
   │ UPDATE set updated_at=Now()│
   │ COMMIT                     │
   └────────────────────────────┘
                │
                ▼
 4. Broker communication
 ───────────────────────

   _send_task(msg):
     deserialize_options()
     Celery.send_task(                  ┌─────────────────┐
       name='process_order',            │                 │
       args=[42],                 ───>  │  Message Broker │
       task_id='abc-123',               │  (RabbitMQ /    │
       headers={sentry-trace, ...},     │   Redis)        │
     )                                  └────────┬────────┘
                │                                │
                ▼                                │
 --> signal: outbox_message_sent                 │
                                                 │
   close_old_connections()                       │
   ┌─ TX2 ──────────────────────┐                │
   │ DELETE FROM celery_outbox  │                │
   │   WHERE id IN (published)  │                │
   │                            │                │
   │ UPDATE failed: retries++,  │                │
   │   retry_after = exp backoff│                │
   │                            │                │
   │ MOVE exceeded ->           │                │
   │   celery_outbox_dead_letter│                │
   │ COMMIT                     │                │
   └────────────────────────────┘                │
                                                 │
 5. Celery Worker                                │
 ────────────────                                │
                                                 │
   @app.task                                     │
   def process_order(order_id):  <───────────────┘
     order = Order.objects.get(id=order_id)
     # ... business logic
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `CELERY_OUTBOX_APP` | required | Dotted path to Celery app instance |
| `CELERY_OUTBOX_EXCLUDE_TASKS` | `()` | Set of task names to bypass outbox |
| `CELERY_OUTBOX_STRUCTLOG_ENABLED` | `True` | Enable structlog context capture |
| `CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS` | `None` (all) | Whitelist of structlog context keys |
| `MONITORING_METRICS_ENABLED` | `True` | Enable StatsD metric emission |
| `MONITORING_STATSD_HOST` | `'localhost'` | DogStatsD agent host |
| `MONITORING_STATSD_PORT` | `9125` | DogStatsD agent port |
| `MONITORING_STATSD_PREFIX` | `'celery_outbox'` | Metric namespace prefix |
| `MONITORING_STATSD_TAGS` | `{}` | Constant tags dict, e.g. `{'service': 'my-app'}` |

## Delivery Guarantees

| Scenario | Outcome |
|----------|---------|
| Business transaction rolls back | Task never created in outbox. No delivery. |
| Relay crashes before sending to broker | Message remains in outbox with `updated_at` set. Recovered after stale timeout (5 min). |
| Relay sends to broker, crashes before TX2 | Message re-sent after backoff. **Duplicate delivery.** |
| Broker accepts but worker crashes | Standard Celery retry/ack behavior. Outside outbox scope. |
| Relay max retries exceeded | Message moved to dead letter table. Operator can inspect and retry via admin. |

**Delivery semantics: at-least-once.** Consumers must be idempotent.

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
    │     (no internal deps)
    │
    ├── metrics.py (increment, gauge, timing)
    │     └── statsd.py (get_statsd)
    │
    ├── statsd.py (DogStatsd singleton)
    │     (reads django.conf.settings)
    │
    └── management/commands/celery_outbox_relay.py (Command)
          └── relay.py (Relay)

admin.py (standalone, auto-registered)
    └── models.py (CeleryOutbox, CeleryOutboxDeadLetter)
```

## Database Indexes Strategy

```
celery_outbox_pending_idx:
    Partial index on (id) WHERE updated_at IS NULL
    Used by: _select_messages() for fresh messages

retry_after index:
    B-tree index on retry_after
    Used by: _select_messages() for backoff-eligible messages

task_id index:
    B-tree index on task_id
    Used by: lookups by Celery task UUID (both tables)

task_name index:
    B-tree index on task_name
    Used by: admin filtering, debugging queries (both tables)
```
