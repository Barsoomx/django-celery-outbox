# Configuration

All settings are prefixed with `CELERY_OUTBOX_`.

## Required Settings

| Setting | Type | Description |
|---------|------|-------------|
| `CELERY_OUTBOX_APP` | `str` | Dotted path to your Celery app instance. Example: `'myproject.celery_app.app'` |

## Optional Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `CELERY_OUTBOX_EXCLUDE_TASKS` | `set[str] \| frozenset[str] \| list[str] \| tuple[str, ...]` | `set()` | Task names to bypass the outbox (sent directly to broker). Invalid values fail in `python manage.py check` and at runtime. |
| `CELERY_OUTBOX_STRUCTLOG_ENABLED` | `bool` | `True` | Enable structlog context propagation |
| `CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS` | `list[str] \| None` | `None` | structlog keys to capture. `None` captures all keys |
| `CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK` | `bool` | `True` | Include full traceback in exception logs |
| `CELERY_OUTBOX_PII_REDACTOR` | `str \| callable` | `None` | Callable (or dotted path to one) that stores redacted inspection copies of task args/kwargs |

## Relay Command Options

```bash
python manage.py celery_outbox_relay [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--batch-size` | `100` | Messages per batch |
| `--idle-time` | `1.0` | Seconds to sleep when queue is empty |
| `--backoff-time` | `120` | Base seconds for exponential backoff |
| `--max-retries` | `5` | Retries before dead letter |
| `--stale-timeout-seconds` | `300` | Seconds before in-flight rows are considered stale and reclaimable |
| `--send-timeout` | `10.0` | Timeout passed to `Celery.send_task()` during broker publish |
| `--shutdown-timeout` | `30.0` | Drain window for starting additional sends after `SIGTERM`/`SIGINT` |
| `--broker-outage-cooldown` | `30.0` | Process-local breaker cooldown before the next batch attempt |
| `--max-backoff` | `3600.0` | Upper bound for normal message retry delay |
| `--liveness-file` | `None` | File to touch after each batch (for k8s probes) |

## Metrics Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `MONITORING_STATSD_HOST` | `str` | `'localhost'` | StatsD server host |
| `MONITORING_STATSD_PORT` | `int` | `9125` | StatsD server port |
| `MONITORING_STATSD_PREFIX` | `str` | `'celery_outbox'` | Metric name prefix |
| `MONITORING_STATSD_TAGS` | `dict` | `{}` | Default tags for all metrics |
| `CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS` | `bool` | `False` | Disable task_name tags entirely |
| `CELERY_OUTBOX_MONITORED_TASKS` | `set[str]` | `None` | Allowlist of task names for tags (others become "other") |
