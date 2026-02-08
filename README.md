# django-celery-outbox

[![CI](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/ci.yml/badge.svg)](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/django-celery-outbox.svg)](https://pypi.org/project/django-celery-outbox/)
[![Ruff](https://img.shields.io/badge/lint-ruff-46a2f1.svg)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Transactional Outbox pattern for Celery tasks in Django. Instead of sending tasks directly to the message broker (where they can be lost if the database transaction rolls back), tasks are written to a database table within the same transaction as your business data. A separate relay process reads the table and sends tasks to the broker asynchronously, guaranteeing **at-least-once delivery**.

## Features

- Drop-in replacement for `celery.Celery` -- swap `Celery()` for `OutboxCelery()`, everything else works as before
- Tasks are stored in the database within the same transaction as business data
- Relay daemon with configurable batch size, idle time, backoff, and max retries
- `SELECT FOR UPDATE SKIP LOCKED` for safe concurrent relay instances
- Sentry trace propagation (`sentry-trace` + `baggage` headers) across the outbox boundary
- structlog context propagation with configurable key filtering
- Serialization of Celery Signatures, chains, chords, countdown/eta, expires
- Read-only Django Admin interface for outbox inspection
- Selective bypass -- exclude specific tasks from the outbox via settings
- `countdown` is converted to absolute `eta` at intercept time, so the task runs at the correct time regardless of relay delay
- Graceful shutdown on SIGTERM/SIGINT
- Multi-database aware
- StatsD metrics for monitoring relay throughput and errors
- Health check endpoint for load balancer / k8s probes

## Quick Start

### 1. Install

```bash
pip install django-celery-outbox
```

### 2. Add to INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    'django_celery_outbox',
]
```

### 3. Replace Celery app

In your `myproject/celery.py`:

```python
from django_celery_outbox import OutboxCelery

app = OutboxCelery('myproject')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

### 4. Configure the outbox app path

In your Django settings:

```python
CELERY_OUTBOX_APP = 'myproject.celery.app'
```

### 5. Run migrations

```bash
python manage.py migrate
```

### 6. Start the relay

```bash
python manage.py celery_outbox_relay
```

Now every `app.send_task(...)` or `my_task.delay(...)` call inside a `transaction.atomic()` block will write to the outbox table instead of sending directly to the broker.

## Configuration

All settings are configured in your Django settings module.

| Setting | Default | Description |
|---------|---------|-------------|
| `CELERY_OUTBOX_APP` | **required** | Dotted path to your Celery app instance, e.g. `'myproject.celery.app'` |
| `CELERY_OUTBOX_EXCLUDE_TASKS` | `()` | Tuple/set of task names that bypass the outbox and send directly to the broker |
| `CELERY_OUTBOX_STRUCTLOG_ENABLED` | `True` | Enable structlog context capture at `send_task()` time |
| `CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS` | `None` | List of structlog context keys to capture. `None` means capture all keys |
| `MONITORING_STATSD_HOST` | `'localhost'` | StatsD server host for metrics |
| `MONITORING_STATSD_PORT` | `9125` | StatsD server port |
| `MONITORING_STATSD_PREFIX` | `'celery_outbox'` | Prefix for all StatsD metric names |
| `MONITORING_STATSD_TAGS` | `{}` | Extra tags attached to every StatsD metric |
| `MONITORING_METRICS_ENABLED` | `True` | Enable StatsD metrics emission |

## Relay Command

The relay is a Django management command that runs as a long-lived daemon:

```bash
python manage.py celery_outbox_relay [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--batch-size` | `100` | Maximum number of messages to process per batch |
| `--idle-time` | `1.0` | Seconds to sleep when a batch is smaller than `batch_size` |
| `--backoff-time` | `120` | Seconds to wait before retrying a failed message |
| `--max-retries` | `5` | Maximum retry attempts before a message is discarded |

Example:

```bash
python manage.py celery_outbox_relay \
    --batch-size 200 \
    --idle-time 0.5 \
    --backoff-time 60 \
    --max-retries 10
```

The relay handles SIGTERM and SIGINT for graceful shutdown -- it finishes the current batch before exiting.

## Usage Examples

### Basic task

```python
from django.db import transaction

with transaction.atomic():
    order = Order.objects.create(total=99.99)
    app.send_task('process_order', args=[order.id])
```

### With countdown or eta

```python
from datetime import datetime, timezone

with transaction.atomic():
    order = Order.objects.create(total=99.99)

    # Delay execution by 60 seconds
    app.send_task('process_order', args=[order.id], countdown=60)

    # Or specify an exact time
    app.send_task(
        'send_reminder',
        args=[order.id],
        eta=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
    )
```

### With link (callback chain)

```python
from celery import signature

with transaction.atomic():
    app.send_task(
        'process_payment',
        args=[order.id],
        link=signature('send_receipt', args=[order.id]),
    )
```

### Excluded tasks

Tasks in `CELERY_OUTBOX_EXCLUDE_TASKS` bypass the outbox and go directly to the broker:

```python
# settings.py
CELERY_OUTBOX_EXCLUDE_TASKS = {'debug.ping', 'monitoring.heartbeat'}
```

```python
# This goes directly to the broker, not through the outbox
app.send_task('debug.ping')
```

### Outside a transaction

If `send_task` is called outside `transaction.atomic()`, the task is still written to the outbox, but a warning is logged (`celery_outbox_not_in_transaction`). The outbox pattern provides the strongest guarantees only when used inside a transaction.

## Kubernetes Liveness Probe

The relay supports a file-based liveness probe for Kubernetes. Pass `--liveness-file` to touch
a file after each processing cycle:

```bash
python manage.py celery_outbox_relay --liveness-file /tmp/celery-outbox-alive
```

Configure the k8s liveness probe to check the file's modification time:

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

If the relay hangs, the file stops being updated and k8s restarts the pod.

## Metrics

When `MONITORING_METRICS_ENABLED` is `True` (the default), the relay emits StatsD metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `messages.published` | counter | Messages successfully sent to broker |
| `messages.failed` | counter | Messages that failed to send (retries remain) |
| `messages.exceeded` | counter | Messages that exceeded max retries |
| `queue.depth` | gauge | Total outbox queue size |
| `dead_letter.count` | gauge | Total dead letter table size |
| `batch.duration_ms` | timing | Time to process one batch (milliseconds) |

### Tags

All metrics include `task_name` as a tag. You can add custom tags via `MONITORING_STATSD_TAGS`:

```python
MONITORING_STATSD_TAGS = {
    'env': 'production',
    'service': 'myproject',
}
```

### Kubernetes / Datadog setup

Point the StatsD settings to your DogStatsD agent:

```python
MONITORING_STATSD_HOST = 'localhost'
MONITORING_STATSD_PORT = 8125
MONITORING_STATSD_PREFIX = 'celery_outbox'
```

## Observability

### structlog Context Propagation

The outbox captures structlog context variables at `send_task()` time and restores them when the relay sends the task to the broker. This means your request IDs, user IDs, and other context flow through the outbox boundary.

```python
# Capture all context keys (default)
CELERY_OUTBOX_STRUCTLOG_ENABLED = True
CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS = None

# Capture only specific keys
CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS = ['request_id', 'user_id']

# Disable entirely
CELERY_OUTBOX_STRUCTLOG_ENABLED = False
```

### Sentry Trace Propagation

Sentry trace context (`sentry-trace` and `baggage` headers) is automatically captured at `send_task()` time and injected into the Celery task headers when the relay sends the task. No configuration needed -- if `sentry-sdk` is installed, it works automatically.

## Dead Letter Table

When a message exceeds `max_retries`, it is moved to the `celery_outbox_dead_letter` table
and a warning is logged with `celery_outbox_max_retries_exceeded`. Messages are **never silently
deleted**. Operators can inspect and retry dead-lettered messages via the Django admin.

## Delivery Guarantees

**Semantics: at-least-once delivery.** Consumers must be idempotent.

| Scenario | Outcome |
|----------|---------|
| Business transaction rolls back | Task never created in outbox. No delivery. |
| Relay crashes before sending to broker | Message remains in outbox. Retried after `backoff_time`. |
| Relay sends to broker, crashes before cleanup | Message re-sent after `backoff_time`. **Duplicate delivery.** |
| Broker accepts but worker crashes | Standard Celery retry/ack behavior. Outside outbox scope. |
| Max retries exceeded | Message moved to dead letter table. Operator can retry via admin. |

The relay uses a two-transaction design: transaction 1 selects and locks messages, network I/O sends them to the broker, and transaction 2 deletes/updates results. This avoids holding database locks during broker communication.

## Multiple Relay Instances

You can run multiple relay instances for higher throughput. The relay uses `SELECT FOR UPDATE SKIP LOCKED`, which means each instance picks up different messages without conflicts:

```
  Relay Instance A                    Relay Instance B
  SELECT ... FOR UPDATE               SELECT ... FOR UPDATE
  SKIP LOCKED                         SKIP LOCKED
  -> gets messages 1-100              -> gets messages 101-200
  (1-100 are locked)                  (1-100 skipped)
```

No additional configuration is needed -- just start multiple processes.

## Development

### Setup

```bash
git clone https://github.com/Barsoomx/django-celery-outbox.git
cd django-celery-outbox
docker compose build
```

### Run tests

```bash
docker compose run --rm app pytest -v
```

### Linting

```bash
docker compose run --rm app ruff check .
docker compose run --rm app ruff format --check .
```

### Type checking

```bash
docker compose run --rm app mypy -p django_celery_outbox --config-file=pyproject.toml
```

## License

GPL-3.0-or-later. See [LICENSE](LICENSE) for details.
