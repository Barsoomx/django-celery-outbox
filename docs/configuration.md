# Configuration

All settings are prefixed with `CELERY_OUTBOX_`.

## Required Settings

| Setting | Type | Description |
|---------|------|-------------|
| `CELERY_OUTBOX_APP` | `str` | Dotted path to your Celery app instance. Example: `'myproject.celery.app'` |

## Optional Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `CELERY_OUTBOX_EXCLUDE_TASKS` | `set[str]` | `set()` | Task names to bypass the outbox (sent directly to broker) |
| `CELERY_OUTBOX_STRUCTLOG_ENABLED` | `bool` | `True` | Enable structlog context propagation |
| `CELERY_OUTBOX_STRUCTLOG_FILTER_KEYS` | `set[str]` | `set()` | structlog keys to exclude from propagation |
| `CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK` | `bool` | `True` | Include full traceback in exception logs |
| `CELERY_OUTBOX_PII_REDACTOR` | `str` | `None` | Dotted path to PII redaction callable |

## Relay Command Options

```bash
python manage.py celery_outbox_relay [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--batch-size` | `100` | Messages per batch |
| `--idle-time` | `1.0` | Seconds to sleep when queue is empty |
| `--backoff-time` | `5.0` | Base seconds for exponential backoff |
| `--max-retries` | `5` | Retries before dead letter |
| `--liveness-file` | `None` | File to touch after each batch (for k8s probes) |

## Metrics Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `CELERY_OUTBOX_STATSD_HOST` | `str` | `'localhost'` | StatsD server host |
| `CELERY_OUTBOX_STATSD_PORT` | `int` | `8125` | StatsD server port |
| `CELERY_OUTBOX_STATSD_PREFIX` | `str` | `'celery_outbox'` | Metric name prefix |
| `CELERY_OUTBOX_STATSD_TAGS` | `dict` | `{}` | Default tags for all metrics |
| `CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS` | `bool` | `False` | Disable task_name tags entirely |
| `CELERY_OUTBOX_MONITORED_TASKS` | `set[str]` | `None` | Allowlist of task names for tags (others become "other") |
