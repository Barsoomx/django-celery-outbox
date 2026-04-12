# Observability & Security Hardening Design

**Date:** 2026-04-12
**Issues:** #24, #26, #33
**Status:** Draft

## Overview

This spec combines three related issues into a cohesive observability and security hardening effort:

- **#24** Critical relay metrics (oldest_pending_age, send_latency, exception labels, cardinality)
- **#26** Observability artifacts (logging contract, Grafana dashboard, alerts, log sampling)
- **#33** PII handling (redaction hook, structlog safety, exception scrubbing, DLQ retention docs)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     WRITE PATH (app.py)                         │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────────────┐  │
│  │ send_task() │───►│ PII Redactor │───►│ CeleryOutbox.save │  │
│  └─────────────┘    │   (NEW #33)  │    └───────────────────┘  │
│                     └──────────────┘                            │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     RELAY (relay.py)                            │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────────────┐  │
│  │ _processing │───►│ New Metrics  │───►│ Exception Logger  │  │
│  │             │    │   (#24)      │    │   (#33)           │  │
│  └─────────────┘    └──────────────┘    └───────────────────┘  │
│         │                                                       │
│         ▼                                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ oldest_pending_age_seconds | send_latency_seconds        │  │
│  │ exception_type labels      | cardinality control         │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                 OBSERVABILITY ARTIFACTS (#26)                   │
│  docs/observability/                                            │
│  ├── logging-events.md      # Public API contract               │
│  ├── grafana-dashboard.json # Ready-to-import                   │
│  ├── alert-rules.yml        # Prometheus alerts                 │
│  └── log-sampling.md        # High-throughput guidance          │
└─────────────────────────────────────────────────────────────────┘
```

**Files to modify:**
- `django_celery_outbox/app.py` — PII redaction hook
- `django_celery_outbox/relay.py` — new metrics, exception logging setting
- `django_celery_outbox/metrics.py` — helper for cardinality control
- `django_celery_outbox/conf.py` — new settings
- `docs/observability/*` — 4 new documentation files
- `README.md` — security warning section

## New Settings

```python
# === Issue #33: PII Handling ===

# Callable path: 'myapp.security.redact'
# Signature: (task_name: str, args: list, kwargs: dict) -> tuple[list, dict]
# Default: None (no redaction)
CELERY_OUTBOX_PII_REDACTOR: str | None = None

# Whether to include exception traceback in error logs
# Set to False in production to prevent PII leakage via locals
# Default: True (backward compatible)
CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK: bool = True


# === Issue #24: Metrics Cardinality ===

# Disable task_name tag on metrics to prevent cardinality explosion
# Default: False (task_name tags enabled for backward compatibility)
CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS: bool = False

# Alternative: allowlist of task names to tag (others become "other")
# Default: None (all task names tagged if DISABLE_TASK_NAME_TAGS=False)
CELERY_OUTBOX_MONITORED_TASKS: set[str] | None = None
```

### Cardinality Control Logic

```python
def _get_task_tag(task_name: str) -> dict[str, str]:
    if settings.CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS:
        return {}

    monitored = settings.CELERY_OUTBOX_MONITORED_TASKS
    if monitored is not None and task_name not in monitored:
        return {'task_name': 'other'}

    return {'task_name': task_name}
```

## PII Redaction Hook

**Location:** `app.py`, method `send_task()`, before creating `CeleryOutbox` record.

### Implementation

```python
# django_celery_outbox/app.py

from django.utils.module_loading import import_string
from functools import lru_cache

@lru_cache(maxsize=1)
def _get_redactor() -> Callable[[str, list, dict], tuple[list, dict]] | None:
    """Load and cache PII redactor from settings."""
    path = getattr(settings, 'CELERY_OUTBOX_PII_REDACTOR', None)
    if not path:
        return None
    return import_string(path)

def _redact_task_data(
    task_name: str,
    args: list,
    kwargs: dict
) -> tuple[list, dict]:
    redactor = _get_redactor()
    if redactor is None:
        return args, kwargs

    return redactor(task_name, args, kwargs)


class OutboxCelery(Celery):
    def send_task(self, name, args=None, kwargs=None, **options):
        # ... existing code ...

        args_list = list(args) if args else []
        kwargs_dict = dict(kwargs) if kwargs else {}

        # NEW: Apply PII redaction before persistence
        args_list, kwargs_dict = _redact_task_data(name, args_list, kwargs_dict)

        CeleryOutbox.objects.create(
            task_id=task_id,
            task_name=name,
            args=args_list,      # redacted
            kwargs=kwargs_dict,  # redacted
            options=serialized_options,
            # ... rest ...
        )
```

### Example User Redactor

```python
# myapp/security.py

SENSITIVE_KEYS = {'email', 'phone', 'ssn', 'password', 'token', 'credit_card'}

def redact_task_data(
    task_name: str,
    args: list,
    kwargs: dict
) -> tuple[list, dict]:
    redacted_kwargs = {
        k: '[REDACTED]' if k in SENSITIVE_KEYS else v
        for k, v in kwargs.items()
    }
    return args, redacted_kwargs

# settings.py
CELERY_OUTBOX_PII_REDACTOR = 'myapp.security.redact_task_data'
```

**Error handling:** If redactor raises exception, it propagates (task won't be created). This allows blocking sensitive tasks.

## New Metrics

### oldest_pending_age_seconds (gauge)

```python
# relay.py, in _processing() after existing gauge metrics

oldest = (
    CeleryOutbox.objects
    .filter(updated_at__isnull=True)  # never attempted
    .order_by('created_at')
    .values_list('created_at', flat=True)
    .first()
)
if oldest:
    age_seconds = (timezone.now() - oldest).total_seconds()
    metrics.gauge('oldest_pending_age_seconds', age_seconds)
else:
    metrics.gauge('oldest_pending_age_seconds', 0)
```

### send_latency_ms (histogram/timing)

```python
# relay.py, in _process_messages() after successful send

import time

# Success path
published.append(msg.id)

# NEW: send latency (created_at -> now)
latency_seconds = time.time() - msg.created_at.timestamp()
latency_ms = latency_seconds * 1000
tags = _get_task_tag(msg.task_name)
metrics.timing('send_latency_ms', latency_ms, tags=tags)

metrics.increment('messages.published', tags=tags)
```

### exception_type Label

```python
# relay.py

_EXCEPTION_CATEGORIES = {
    ConnectionError: 'connection',
    TimeoutError: 'timeout',
    OSError: 'os_error',
}

def _classify_exception(exc: Exception) -> str:
    for exc_class, label in _EXCEPTION_CATEGORIES.items():
        if isinstance(exc, exc_class):
            return label
    return 'unknown'


# In exception handler:
except Exception as e:
    exc_type = _classify_exception(e)
    tags = _get_task_tag(msg.task_name)
    tags['exception_type'] = exc_type

    if msg.retries >= self._max_retries - 1:
        metrics.increment('messages.exceeded', tags=tags)
    else:
        metrics.increment('messages.failed', tags=tags)
```

### Metrics Summary

| Metric | Type | Tags | Status |
|--------|------|------|--------|
| `oldest_pending_age_seconds` | gauge | — | NEW |
| `send_latency_ms` | timing | task_name | NEW |
| `messages.published` | counter | task_name | cardinality control |
| `messages.failed` | counter | task_name, exception_type | +exception_type |
| `messages.exceeded` | counter | task_name, exception_type | +exception_type |

## Exception Logging Changes

### Setting

```python
CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK: bool = True
```

### Implementation

```python
# relay.py

def _should_log_traceback() -> bool:
    return getattr(settings, 'CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK', True)


# In exception handlers:
except Exception as e:
    exc_type = _classify_exception(e)

    log_kwargs = {
        'outbox_id': msg.id,
        'task_name': msg.task_name,
        'task_id': msg.task_id,
        'retries': msg.retries,
        'exception_type': exc_type,
        'exception_message': str(e),
    }

    if _should_log_traceback():
        _logger.error('celery_outbox_send_failed', **log_kwargs, exc_info=True)
    else:
        _logger.error('celery_outbox_send_failed', **log_kwargs)
```

## Observability Documentation

### docs/observability/logging-events.md

Public API contract for all log events:

| Event | Level | Fields |
|-------|-------|--------|
| `celery_outbox_relay_started` | INFO | batch_size, idle_time, backoff_time, max_retries |
| `celery_outbox_relay_shutdown` | INFO | signal |
| `celery_outbox_batch_processed` | INFO | published, failed, exceeded, queue_depth |
| `celery_outbox_relay_idle` | DEBUG | — |
| `celery_outbox_relay_busy` | DEBUG | — |
| `celery_outbox_send_failed` | ERROR | outbox_id, task_name, task_id, retries, exception_type, exception_message |
| `celery_outbox_max_retries_exceeded` | WARNING | outbox_id, task_name, task_id, retries, exception_type, exception_message |
| `celery_outbox_signal_error` | ERROR | signal, task_id, task_name, exception_type, exception_message |
| `celery_outbox_not_in_transaction` | WARNING | task_name, task_id |
| `celery_outbox_signatures_dropped` | WARNING | dropped, total |

### docs/observability/grafana-dashboard.json

Ready-to-import dashboard with panels:

| Panel | Query | Type |
|-------|-------|------|
| Message Throughput | `rate(celery_outbox_messages_published[5m])` | Time series |
| Failure Rate | `rate(celery_outbox_messages_failed[5m])` | Time series |
| Dead Letter Count | `celery_outbox_dead_letter_count` | Stat + Gauge |
| Queue Depth | `celery_outbox_queue_depth` | Time series |
| Oldest Pending Age | `celery_outbox_oldest_pending_age_seconds` | Stat |
| Send Latency p95 | `histogram_quantile(0.95, celery_outbox_send_latency_ms)` | Time series |
| Failures by Exception | `sum by (exception_type) (celery_outbox_messages_failed)` | Bar chart |
| Failures by Task | `topk(10, celery_outbox_messages_failed)` | Table |

### docs/observability/alert-rules.yml

```yaml
groups:
  - name: celery-outbox
    rules:
      - alert: CeleryOutboxDeadLetters
        expr: increase(celery_outbox_messages_exceeded_total[5m]) > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Dead-lettered messages detected"

      - alert: CeleryOutboxQueueBacklog
        expr: celery_outbox_queue_depth > 5000
        for: 10m
        labels:
          severity: critical

      - alert: CeleryOutboxHighFailureRate
        expr: >
          rate(celery_outbox_messages_failed[5m])
          / rate(celery_outbox_messages_published[5m]) > 0.05
        for: 5m
        labels:
          severity: warning

      - alert: CeleryOutboxStuck
        expr: celery_outbox_oldest_pending_age_seconds > 300
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Messages stuck in outbox > 5 minutes"
```

### docs/observability/log-sampling.md

Guidance for high-throughput deployments (>1000 msg/sec):
- Set DEBUG level for idle/busy events
- Consider `CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS=True`
- Use async log handlers

## README Security Section

New section after "Configuration":

```markdown
## Security Considerations

### PII in Task Arguments

Task `args` and `kwargs` are stored in the database until processed.
If your tasks receive sensitive data (emails, tokens, PII), consider:

1. **Exclude sensitive tasks** from the outbox:
   ```python
   CELERY_OUTBOX_EXCLUDE_TASKS = {'myapp.tasks.send_sms', 'payments.*'}
   ```

2. **Redact sensitive fields** before storage:
   ```python
   # myapp/security.py
   SENSITIVE_KEYS = {'email', 'phone', 'password', 'token'}

   def redact_task_data(task_name: str, args: list, kwargs: dict):
       redacted = {
           k: '[REDACTED]' if k in SENSITIVE_KEYS else v
           for k, v in kwargs.items()
       }
       return args, redacted

   # settings.py
   CELERY_OUTBOX_PII_REDACTOR = 'myapp.security.redact_task_data'
   ```

### Structlog Context Capture

When `CELERY_OUTBOX_STRUCTLOG_ENABLED=True` (default), structlog context
variables are captured and stored with each message.

**Warning:** If `CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS` is not configured,
ALL context variables are captured, which may include sensitive data like
`user_email`, `session_id`, etc.

**Recommendation:** Explicitly list safe keys:
```python
CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS = ['request_id', 'trace_id', 'user_id']
```

### Exception Tracebacks

Exception tracebacks may contain sensitive data from local variables.
To disable traceback logging:
```python
CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK = False
```

### Dead Letter Queue Retention

Failed messages in the dead letter queue contain the original task data.
Configure automatic cleanup via Celery Beat to comply with data retention
policies (GDPR, etc.):

```python
# settings.py
CELERY_OUTBOX_DLQ_RETENTION = {
    'older_than_dead': '30d',
}

# celery.py
app.conf.beat_schedule = {
    'purge-dead-letters': {
        'task': 'django_celery_outbox.tasks.purge_dead_letter',
        'schedule': crontab(hour=3, minute=0),  # daily at 3am
    },
}
```

### Metrics Cardinality

The `task_name` tag on metrics can cause cardinality explosion if you have
many unique task names. Options:

```python
# Disable task_name tags entirely
CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS = True

# Or allowlist specific tasks (others become "other")
CELERY_OUTBOX_MONITORED_TASKS = {'critical.task1', 'critical.task2'}
```
```

## Test Plan

### PII Redaction Tests (app_tests.py)

```python
def test_send_task_applies_pii_redactor(settings, m_celery_outbox):
    def redactor(name, args, kwargs):
        return args, {k: '[R]' if k == 'email' else v for k, v in kwargs.items()}

    settings.CELERY_OUTBOX_PII_REDACTOR = redactor
    app.send_task('test', kwargs={'email': 'user@example.com', 'safe': 1})

    msg = CeleryOutbox.objects.first()
    assert msg.kwargs == {'email': '[R]', 'safe': 1}

def test_send_task_no_redactor_stores_original(settings):
    settings.CELERY_OUTBOX_PII_REDACTOR = None
    app.send_task('test', kwargs={'email': 'user@example.com'})

    msg = CeleryOutbox.objects.first()
    assert msg.kwargs == {'email': 'user@example.com'}

def test_send_task_redactor_exception_propagates(settings):
    def bad_redactor(name, args, kwargs):
        raise ValueError('blocked')

    settings.CELERY_OUTBOX_PII_REDACTOR = bad_redactor
    with pytest.raises(ValueError, match='blocked'):
        app.send_task('test', kwargs={})
```

### Metrics Tests (relay_tests.py)

```python
def test_oldest_pending_age_metric_emitted(m_metrics, f_outbox_messages):
    relay._processing()
    m_metrics.gauge.assert_any_call('oldest_pending_age_seconds', pytest.approx(60, abs=5))

def test_send_latency_metric_emitted(m_metrics, f_outbox_message):
    relay._processing()
    m_metrics.timing.assert_called()
    assert m_metrics.timing.call_args[0][0] == 'send_latency_ms'

def test_exception_type_label_on_failure(m_metrics, m_send_task_raises):
    m_send_task_raises(ConnectionError('broker down'))
    relay._processing()
    m_metrics.increment.assert_called_with(
        'messages.failed',
        tags={'task_name': ANY, 'exception_type': 'connection'}
    )

def test_cardinality_control_disabled_tags(settings, m_metrics):
    settings.CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS = True
    relay._processing()
    call_tags = m_metrics.increment.call_args[1].get('tags', {})
    assert 'task_name' not in call_tags

def test_cardinality_control_monitored_tasks(settings, m_metrics):
    settings.CELERY_OUTBOX_MONITORED_TASKS = {'allowed.task'}
    relay._processing()
    call_tags = m_metrics.increment.call_args[1]['tags']
    assert call_tags['task_name'] == 'other'
```

### Exception Logging Tests (relay_tests.py)

```python
def test_exception_logging_with_traceback(settings, m_logger, m_send_task_raises):
    settings.CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK = True
    m_send_task_raises(ValueError('fail'))
    relay._processing()
    assert m_logger.error.call_args[1]['exc_info'] is True

def test_exception_logging_without_traceback(settings, m_logger, m_send_task_raises):
    settings.CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK = False
    m_send_task_raises(ValueError('fail'))
    relay._processing()
    assert 'exc_info' not in m_logger.error.call_args[1]
    assert m_logger.error.call_args[1]['exception_type'] == 'unknown'
```

## Acceptance Criteria

### Issue #24 — Critical Metrics
- [ ] `oldest_pending_age_seconds` gauge emitted each batch cycle
- [ ] `send_latency_ms` timing emitted per message
- [ ] Error counters tagged with `exception_type`
- [ ] Cardinality control via settings
- [ ] Tests

### Issue #26 — Observability Artifacts
- [ ] `docs/observability/logging-events.md` — stable event names
- [ ] `docs/observability/grafana-dashboard.json`
- [ ] `docs/observability/alert-rules.yml`
- [ ] `docs/observability/log-sampling.md`

### Issue #33 — PII Handling
- [ ] `CELERY_OUTBOX_PII_REDACTOR` hook
- [ ] `CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK` setting
- [ ] Security section in README
- [ ] DLQ retention documented with Beat example
- [ ] Tests
