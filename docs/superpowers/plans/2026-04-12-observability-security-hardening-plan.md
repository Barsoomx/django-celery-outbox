# Observability & Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add critical metrics, cardinality control, PII redaction hook, and observability documentation.

**Architecture:** Extend relay with new metrics (oldest_pending_age, send_latency, exception_type labels), add PII redactor hook to write path, add cardinality control for task_name tags, create observability docs.

**Tech Stack:** Python 3.10+, Django, structlog, StatsD/DogStatsd

**Spec:** `docs/superpowers/specs/2026-04-12-observability-security-hardening-design.md`

---

## File Structure

**Modify:**
- `django_celery_outbox/metrics.py` — add `_get_task_tag()` helper
- `django_celery_outbox/relay/_relay.py` — new metrics, exception type labels, traceback setting
- `django_celery_outbox/app.py` — PII redaction hook

**Create:**
- `docs/observability/logging-events.md`
- `docs/observability/grafana-dashboard.json`
- `docs/observability/alert-rules.yml`
- `docs/observability/log-sampling.md`

**Tests:**
- `django_celery_outbox/metrics_tests.py` — cardinality control tests
- `django_celery_outbox/relay/relay_tests.py` — new metrics tests (extend existing)
- `django_celery_outbox/app_tests.py` — PII redactor tests (extend existing)

---

### Task 1: Cardinality Control Helper

**Files:**
- Modify: `django_celery_outbox/metrics.py`
- Create: `django_celery_outbox/metrics_tests.py`

- [ ] **Step 1: Write failing tests for _get_task_tag**

```python
# django_celery_outbox/metrics_tests.py
import pytest

from django_celery_outbox.metrics import _get_task_tag


def test_get_task_tag_returns_task_name_by_default(settings: object) -> None:
    settings.CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS = False
    settings.CELERY_OUTBOX_MONITORED_TASKS = None

    result = _get_task_tag('myapp.tasks.send_email')

    assert result == {'task_name': 'myapp.tasks.send_email'}


def test_get_task_tag_returns_empty_when_disabled(settings: object) -> None:
    settings.CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS = True

    result = _get_task_tag('myapp.tasks.send_email')

    assert result == {}


def test_get_task_tag_returns_other_when_not_monitored(settings: object) -> None:
    settings.CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS = False
    settings.CELERY_OUTBOX_MONITORED_TASKS = {'allowed.task'}

    result = _get_task_tag('myapp.tasks.send_email')

    assert result == {'task_name': 'other'}


def test_get_task_tag_returns_task_name_when_monitored(settings: object) -> None:
    settings.CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS = False
    settings.CELERY_OUTBOX_MONITORED_TASKS = {'myapp.tasks.send_email'}

    result = _get_task_tag('myapp.tasks.send_email')

    assert result == {'task_name': 'myapp.tasks.send_email'}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/metrics_tests.py -v`
Expected: FAIL with "cannot import name '_get_task_tag'"

- [ ] **Step 3: Implement _get_task_tag**

```python
# django_celery_outbox/metrics.py
# Add after _to_tags function (line 14)

def _get_task_tag(task_name: str) -> dict[str, str]:
    if getattr(settings, 'CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS', False):
        return {}

    monitored = getattr(settings, 'CELERY_OUTBOX_MONITORED_TASKS', None)
    if monitored is not None and task_name not in monitored:
        return {'task_name': 'other'}

    return {'task_name': task_name}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/metrics_tests.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/metrics.py django_celery_outbox/metrics_tests.py
git commit -m "feat(metrics): add cardinality control for task_name tags (#24)"
```

---

### Task 2: Exception Classification Helper

**Files:**
- Modify: `django_celery_outbox/relay/_relay.py`
- Create: `django_celery_outbox/relay/relay_exception_tests.py`

- [ ] **Step 1: Write failing tests for _classify_exception**

```python
# django_celery_outbox/relay/relay_exception_tests.py
import pytest

from django_celery_outbox.relay._relay import _classify_exception


def test_classify_exception_connection_error() -> None:
    exc = ConnectionError('broker down')
    assert _classify_exception(exc) == 'connection'


def test_classify_exception_timeout_error() -> None:
    exc = TimeoutError('timed out')
    assert _classify_exception(exc) == 'timeout'


def test_classify_exception_os_error() -> None:
    exc = OSError('system error')
    assert _classify_exception(exc) == 'os_error'


def test_classify_exception_unknown() -> None:
    exc = ValueError('some value error')
    assert _classify_exception(exc) == 'unknown'


def test_classify_exception_subclass() -> None:
    exc = BrokenPipeError('pipe broken')  # subclass of ConnectionError
    assert _classify_exception(exc) == 'connection'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_exception_tests.py -v`
Expected: FAIL with "cannot import name '_classify_exception'"

- [ ] **Step 3: Implement _classify_exception**

```python
# django_celery_outbox/relay/_relay.py
# Add after ProcessResult class (line 35)

_EXCEPTION_CATEGORIES: dict[type[Exception], str] = {
    ConnectionError: 'connection',
    TimeoutError: 'timeout',
    OSError: 'os_error',
}


def _classify_exception(exc: Exception) -> str:
    for exc_class, label in _EXCEPTION_CATEGORIES.items():
        if isinstance(exc, exc_class):
            return label

    return 'unknown'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_exception_tests.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/relay/_relay.py django_celery_outbox/relay/relay_exception_tests.py
git commit -m "feat(relay): add exception classification helper (#24)"
```

---

### Task 3: Add exception_type Label to Error Metrics

**Files:**
- Modify: `django_celery_outbox/relay/_relay.py`
- Modify: `django_celery_outbox/relay/relay_tests.py`

- [ ] **Step 1: Write failing test for exception_type in metrics**

```python
# Add to django_celery_outbox/relay/relay_tests.py
from unittest.mock import ANY, MagicMock, patch


@pytest.fixture
def m_metrics() -> MagicMock:
    with patch('django_celery_outbox.relay._relay.metrics') as mock:
        yield mock


def test_failed_message_includes_exception_type_in_metrics(
    f_relay: Relay,
    f_outbox_message: CeleryOutbox,
    m_metrics: MagicMock,
) -> None:
    with patch.object(f_relay, '_send_task', side_effect=ConnectionError('broker down')):
        f_relay._processing()

    m_metrics.increment.assert_any_call(
        'messages.failed',
        tags={'task_name': f_outbox_message.task_name, 'exception_type': 'connection'},
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_tests.py::test_failed_message_includes_exception_type_in_metrics -v`
Expected: FAIL (exception_type not in tags)

- [ ] **Step 3: Import _get_task_tag and update _process_message**

```python
# django_celery_outbox/relay/_relay.py
# Update imports at top
from django_celery_outbox.metrics import _get_task_tag

# Modify _process_message method (around line 182-192)
# Replace the exception handler:
            try:
                self._send_task(msg)
            except Exception as e:
                span.set_status('internal_error')
                exc_type = _classify_exception(e)
                _logger.exception('celery_outbox_send_failed')
                if msg.retries >= self._config.max_retries - 1:
                    _logger.warning('celery_outbox_max_retries_exceeded')
                    tags = _get_task_tag(msg.task_name)
                    tags['exception_type'] = exc_type
                    metrics.increment('messages.exceeded', tags=tags)
                    return ProcessResult.EXCEEDED
                else:
                    tags = _get_task_tag(msg.task_name)
                    tags['exception_type'] = exc_type
                    metrics.increment('messages.failed', tags=tags)
                    self._send_signal_safe(outbox_message_failed, msg.task_id, msg.task_name, retries=msg.retries)
                    return ProcessResult.FAILED
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_tests.py::test_failed_message_includes_exception_type_in_metrics -v`
Expected: PASS

- [ ] **Step 5: Run full relay test suite**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add django_celery_outbox/relay/_relay.py django_celery_outbox/relay/relay_tests.py
git commit -m "feat(relay): add exception_type label to error metrics (#24)"
```

---

### Task 4: Update Published Metrics with Cardinality Control

**Files:**
- Modify: `django_celery_outbox/relay/_relay.py`
- Modify: `django_celery_outbox/relay/relay_tests.py`

- [ ] **Step 1: Write failing test for cardinality control on published**

```python
# Add to django_celery_outbox/relay/relay_tests.py

def test_published_message_uses_cardinality_control(
    settings: object,
    f_relay: Relay,
    f_outbox_message: CeleryOutbox,
    m_metrics: MagicMock,
) -> None:
    settings.CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS = True

    f_relay._processing()

    # Should have no task_name tag
    published_call = [c for c in m_metrics.increment.call_args_list if c[0][0] == 'messages.published']
    assert len(published_call) == 1
    assert published_call[0][1].get('tags', {}) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_tests.py::test_published_message_uses_cardinality_control -v`
Expected: FAIL (tags still has task_name)

- [ ] **Step 3: Update success path metrics**

```python
# django_celery_outbox/relay/_relay.py
# Modify line 195 (success branch in _process_message)
            else:
                span.set_status('ok')
                tags = _get_task_tag(msg.task_name)
                metrics.increment('messages.published', tags=tags)
                self._send_signal_safe(outbox_message_sent, msg.task_id, msg.task_name)
                return ProcessResult.PUBLISHED
```

- [ ] **Step 4: Update pre-send exceeded check (line 173)**

```python
# django_celery_outbox/relay/_relay.py
# Modify line 173
        if msg.retries >= self._config.max_retries:
            _logger.warning('celery_outbox_max_retries_exceeded')
            tags = _get_task_tag(msg.task_name)
            metrics.increment('messages.exceeded', tags=tags)
            return ProcessResult.EXCEEDED
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_tests.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add django_celery_outbox/relay/_relay.py django_celery_outbox/relay/relay_tests.py
git commit -m "feat(relay): apply cardinality control to all metrics (#24)"
```

---

### Task 5: Add oldest_pending_age_seconds Metric

**Files:**
- Modify: `django_celery_outbox/relay/_relay.py`
- Modify: `django_celery_outbox/relay/relay_tests.py`

- [ ] **Step 1: Write failing test for oldest_pending_age_seconds**

```python
# Add to django_celery_outbox/relay/relay_tests.py
from datetime import timedelta
from django.utils import timezone


def test_oldest_pending_age_seconds_emitted(
    f_relay: Relay,
    m_metrics: MagicMock,
) -> None:
    # Create message 60 seconds old
    CeleryOutbox.objects.create(
        task_id='test-id',
        task_name='test.task',
        args=[],
        kwargs={},
        options={},
        created_at=timezone.now() - timedelta(seconds=60),
    )

    f_relay._processing()

    gauge_calls = [c for c in m_metrics.gauge.call_args_list if c[0][0] == 'oldest_pending_age_seconds']
    assert len(gauge_calls) == 1
    # Should be approximately 60 seconds
    assert 55 < gauge_calls[0][0][1] < 65


def test_oldest_pending_age_seconds_zero_when_empty(
    f_relay: Relay,
    m_metrics: MagicMock,
) -> None:
    f_relay._processing()

    gauge_calls = [c for c in m_metrics.gauge.call_args_list if c[0][0] == 'oldest_pending_age_seconds']
    assert len(gauge_calls) == 1
    assert gauge_calls[0][0][1] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_tests.py::test_oldest_pending_age_seconds_emitted -v`
Expected: FAIL (no oldest_pending_age_seconds gauge call)

- [ ] **Step 3: Add oldest_pending_age_seconds to _processing**

```python
# django_celery_outbox/relay/_relay.py
# Add import at top
from django.utils import timezone

# Add after line 123 (after batch.duration_ms timing)
        # Oldest pending age metric
        oldest = (
            CeleryOutbox.objects
            .filter(updated_at__isnull=True)
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_tests.py::test_oldest_pending_age_seconds -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/relay/_relay.py django_celery_outbox/relay/relay_tests.py
git commit -m "feat(relay): add oldest_pending_age_seconds gauge metric (#24)"
```

---

### Task 6: Add send_latency_ms Metric

**Files:**
- Modify: `django_celery_outbox/relay/_relay.py`
- Modify: `django_celery_outbox/relay/relay_tests.py`

- [ ] **Step 1: Write failing test for send_latency_ms**

```python
# Add to django_celery_outbox/relay/relay_tests.py
import time as time_module


def test_send_latency_ms_emitted_on_success(
    f_relay: Relay,
    m_metrics: MagicMock,
) -> None:
    # Create message 2 seconds old
    CeleryOutbox.objects.create(
        task_id='test-id',
        task_name='test.task',
        args=[],
        kwargs={},
        options={},
        created_at=timezone.now() - timedelta(seconds=2),
    )

    f_relay._processing()

    timing_calls = [c for c in m_metrics.timing.call_args_list if c[0][0] == 'send_latency_ms']
    assert len(timing_calls) == 1
    # Should be approximately 2000ms
    assert 1900 < timing_calls[0][0][1] < 2500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_tests.py::test_send_latency_ms_emitted_on_success -v`
Expected: FAIL (no send_latency_ms timing call)

- [ ] **Step 3: Add send_latency_ms to success path**

```python
# django_celery_outbox/relay/_relay.py
# Add import at top
import time

# Modify success branch in _process_message (around line 193-197)
            else:
                span.set_status('ok')
                # Send latency: created_at -> now
                latency_ms = (time.time() - msg.created_at.timestamp()) * 1000
                tags = _get_task_tag(msg.task_name)
                metrics.timing('send_latency_ms', latency_ms, tags=tags)
                metrics.increment('messages.published', tags=tags)
                self._send_signal_safe(outbox_message_sent, msg.task_id, msg.task_name)
                return ProcessResult.PUBLISHED
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_tests.py::test_send_latency_ms_emitted_on_success -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/relay/_relay.py django_celery_outbox/relay/relay_tests.py
git commit -m "feat(relay): add send_latency_ms timing metric (#24)"
```

---

### Task 7: Configurable Exception Traceback Logging

**Files:**
- Modify: `django_celery_outbox/relay/_relay.py`
- Modify: `django_celery_outbox/relay/relay_tests.py`

- [ ] **Step 1: Write failing tests for traceback setting**

```python
# Add to django_celery_outbox/relay/relay_tests.py

def test_exception_logging_includes_traceback_by_default(
    settings: object,
    f_relay: Relay,
    f_outbox_message: CeleryOutbox,
) -> None:
    settings.CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK = True

    with patch.object(f_relay, '_send_task', side_effect=ValueError('test error')):
        with patch('django_celery_outbox.relay._relay._logger') as m_logger:
            f_relay._processing()

            error_calls = [c for c in m_logger.error.call_args_list if c[0][0] == 'celery_outbox_send_failed']
            assert len(error_calls) == 1
            assert error_calls[0][1].get('exc_info') is True


def test_exception_logging_excludes_traceback_when_disabled(
    settings: object,
    f_relay: Relay,
    f_outbox_message: CeleryOutbox,
) -> None:
    settings.CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK = False

    with patch.object(f_relay, '_send_task', side_effect=ValueError('test error')):
        with patch('django_celery_outbox.relay._relay._logger') as m_logger:
            f_relay._processing()

            error_calls = [c for c in m_logger.error.call_args_list if c[0][0] == 'celery_outbox_send_failed']
            assert len(error_calls) == 1
            assert 'exc_info' not in error_calls[0][1]
            assert error_calls[0][1]['exception_type'] == 'unknown'
            assert error_calls[0][1]['exception_message'] == 'test error'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_tests.py::test_exception_logging_excludes_traceback_when_disabled -v`
Expected: FAIL

- [ ] **Step 3: Add _should_log_traceback and update exception handler**

```python
# django_celery_outbox/relay/_relay.py
# Add after _classify_exception function

def _should_log_traceback() -> bool:
    return getattr(settings, 'CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK', True)


# Modify exception handler in _process_message
            try:
                self._send_task(msg)
            except Exception as e:
                span.set_status('internal_error')
                exc_type = _classify_exception(e)

                log_kwargs = {
                    'exception_type': exc_type,
                    'exception_message': str(e),
                }

                if _should_log_traceback():
                    _logger.error('celery_outbox_send_failed', **log_kwargs, exc_info=True)
                else:
                    _logger.error('celery_outbox_send_failed', **log_kwargs)

                if msg.retries >= self._config.max_retries - 1:
                    _logger.warning('celery_outbox_max_retries_exceeded')
                    tags = _get_task_tag(msg.task_name)
                    tags['exception_type'] = exc_type
                    metrics.increment('messages.exceeded', tags=tags)
                    return ProcessResult.EXCEEDED
                else:
                    tags = _get_task_tag(msg.task_name)
                    tags['exception_type'] = exc_type
                    metrics.increment('messages.failed', tags=tags)
                    self._send_signal_safe(outbox_message_failed, msg.task_id, msg.task_name, retries=msg.retries)
                    return ProcessResult.FAILED
```

- [ ] **Step 4: Add settings import**

```python
# django_celery_outbox/relay/_relay.py
# Add to imports at top
from django.conf import settings
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_tests.py::test_exception_logging -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run full test suite**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/ -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add django_celery_outbox/relay/_relay.py django_celery_outbox/relay/relay_tests.py
git commit -m "feat(relay): add configurable exception traceback logging (#33)"
```

---

### Task 8: PII Redaction Hook

**Files:**
- Modify: `django_celery_outbox/app.py`
- Modify: `django_celery_outbox/app_tests.py`

- [ ] **Step 1: Write failing tests for PII redactor**

```python
# Add to django_celery_outbox/app_tests.py
from typing import Callable
from django_celery_outbox.models import CeleryOutbox


def test_send_task_applies_pii_redactor(
    settings: object,
    f_outbox_celery: OutboxCelery,
) -> None:
    def redactor(name: str, args: list, kwargs: dict) -> tuple[list, dict]:
        redacted_kwargs = {k: '[REDACTED]' if k == 'email' else v for k, v in kwargs.items()}
        return args, redacted_kwargs

    settings.CELERY_OUTBOX_PII_REDACTOR = redactor

    f_outbox_celery.send_task('test.task', kwargs={'email': 'user@example.com', 'safe': 1})

    msg = CeleryOutbox.objects.first()
    assert msg.kwargs == {'email': '[REDACTED]', 'safe': 1}


def test_send_task_no_redactor_stores_original(
    settings: object,
    f_outbox_celery: OutboxCelery,
) -> None:
    settings.CELERY_OUTBOX_PII_REDACTOR = None

    f_outbox_celery.send_task('test.task', kwargs={'email': 'user@example.com'})

    msg = CeleryOutbox.objects.first()
    assert msg.kwargs == {'email': 'user@example.com'}


def test_send_task_redactor_exception_propagates(
    settings: object,
    f_outbox_celery: OutboxCelery,
) -> None:
    def bad_redactor(name: str, args: list, kwargs: dict) -> tuple[list, dict]:
        raise ValueError('blocked')

    settings.CELERY_OUTBOX_PII_REDACTOR = bad_redactor

    with pytest.raises(ValueError, match='blocked'):
        f_outbox_celery.send_task('test.task', kwargs={})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/app_tests.py::test_send_task_applies_pii_redactor -v`
Expected: FAIL (redactor not applied)

- [ ] **Step 3: Add _get_redactor and _redact_task_data functions**

```python
# django_celery_outbox/app.py
# Add after imports (around line 15)
from functools import lru_cache
from typing import Callable
from django.utils.module_loading import import_string


@lru_cache(maxsize=1)
def _get_redactor() -> Callable[[str, list, dict], tuple[list, dict]] | None:
    redactor = getattr(settings, 'CELERY_OUTBOX_PII_REDACTOR', None)
    if not redactor:
        return None

    if isinstance(redactor, str):
        return import_string(redactor)

    return redactor


def _redact_task_data(
    task_name: str,
    args: list,
    kwargs: dict,
) -> tuple[list, dict]:
    redactor = _get_redactor()
    if redactor is None:
        return args, kwargs

    return redactor(task_name, args, kwargs)
```

- [ ] **Step 4: Apply redaction in send_task**

```python
# django_celery_outbox/app.py
# Modify send_task method, after line 135 (before serialize_options)
# Insert after all_options = _collect_options(...)

        # Apply PII redaction
        args_list = list(args) if args else []
        kwargs_dict = dict(kwargs) if kwargs else {}
        args_list, kwargs_dict = _redact_task_data(name, args_list, kwargs_dict)

# Then modify CeleryOutbox.objects.create to use args_list and kwargs_dict
            CeleryOutbox.objects.create(
                task_id=task_id,
                task_name=name,
                args=args_list,
                kwargs=kwargs_dict,
                options=serialized_options,
                # ... rest unchanged
            )
```

- [ ] **Step 5: Clear lru_cache in tests**

```python
# Add to conftest.py or app_tests.py
@pytest.fixture(autouse=True)
def clear_redactor_cache() -> None:
    from django_celery_outbox.app import _get_redactor
    _get_redactor.cache_clear()
    yield
    _get_redactor.cache_clear()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/app_tests.py::test_send_task_applies_pii_redactor django_celery_outbox/app_tests.py::test_send_task_no_redactor_stores_original django_celery_outbox/app_tests.py::test_send_task_redactor_exception_propagates -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Run full app test suite**

Run: `docker compose run --rm app pytest django_celery_outbox/app_tests.py -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add django_celery_outbox/app.py django_celery_outbox/app_tests.py
git commit -m "feat(app): add PII redaction hook for task args/kwargs (#33)"
```

---

### Task 9: Create logging-events.md Documentation

**Files:**
- Create: `docs/observability/logging-events.md`

- [ ] **Step 1: Create docs/observability directory**

```bash
mkdir -p docs/observability
```

- [ ] **Step 2: Write logging-events.md**

```markdown
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

Same fields as `celery_outbox_send_failed`.

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
```

- [ ] **Step 3: Commit**

```bash
git add docs/observability/logging-events.md
git commit -m "docs(observability): add logging events reference (#26)"
```

---

### Task 10: Create Grafana Dashboard JSON

**Files:**
- Create: `docs/observability/grafana-dashboard.json`

- [ ] **Step 1: Write grafana-dashboard.json**

```json
{
  "annotations": {
    "list": []
  },
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 0,
  "links": [],
  "liveNow": false,
  "panels": [
    {
      "datasource": "${datasource}",
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "mappings": [],
          "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": null}]}
        }
      },
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "id": 1,
      "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
      "targets": [
        {
          "expr": "rate(celery_outbox_messages_published_total[5m])",
          "legendFormat": "{{task_name}}"
        }
      ],
      "title": "Message Throughput (published/5m)",
      "type": "timeseries"
    },
    {
      "datasource": "${datasource}",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "id": 2,
      "targets": [
        {
          "expr": "rate(celery_outbox_messages_failed_total[5m])",
          "legendFormat": "{{task_name}}"
        }
      ],
      "title": "Failure Rate (failed/5m)",
      "type": "timeseries"
    },
    {
      "datasource": "${datasource}",
      "gridPos": {"h": 8, "w": 6, "x": 0, "y": 8},
      "id": 3,
      "targets": [
        {"expr": "celery_outbox_dead_letter_count"}
      ],
      "title": "Dead Letter Count",
      "type": "stat"
    },
    {
      "datasource": "${datasource}",
      "gridPos": {"h": 8, "w": 6, "x": 6, "y": 8},
      "id": 4,
      "targets": [
        {"expr": "celery_outbox_queue_depth"}
      ],
      "title": "Queue Depth",
      "type": "timeseries"
    },
    {
      "datasource": "${datasource}",
      "gridPos": {"h": 8, "w": 6, "x": 12, "y": 8},
      "id": 5,
      "targets": [
        {"expr": "celery_outbox_oldest_pending_age_seconds"}
      ],
      "title": "Oldest Pending Age (seconds)",
      "type": "stat"
    },
    {
      "datasource": "${datasource}",
      "gridPos": {"h": 8, "w": 6, "x": 18, "y": 8},
      "id": 6,
      "targets": [
        {"expr": "histogram_quantile(0.95, rate(celery_outbox_send_latency_ms_bucket[5m]))"}
      ],
      "title": "Send Latency p95 (ms)",
      "type": "timeseries"
    },
    {
      "datasource": "${datasource}",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 16},
      "id": 7,
      "targets": [
        {
          "expr": "sum by (exception_type) (rate(celery_outbox_messages_failed_total[5m]))",
          "legendFormat": "{{exception_type}}"
        }
      ],
      "title": "Failures by Exception Type",
      "type": "barchart"
    },
    {
      "datasource": "${datasource}",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 16},
      "id": 8,
      "targets": [
        {
          "expr": "topk(10, sum by (task_name) (celery_outbox_messages_failed_total))",
          "legendFormat": "{{task_name}}"
        }
      ],
      "title": "Top 10 Failing Tasks",
      "type": "table"
    }
  ],
  "schemaVersion": 38,
  "tags": ["celery", "outbox", "production"],
  "templating": {
    "list": [
      {
        "current": {},
        "hide": 0,
        "includeAll": false,
        "name": "datasource",
        "options": [],
        "query": "prometheus",
        "refresh": 1,
        "type": "datasource"
      }
    ]
  },
  "time": {"from": "now-1h", "to": "now"},
  "title": "Celery Outbox Relay",
  "uid": "celery-outbox-relay"
}
```

- [ ] **Step 2: Commit**

```bash
git add docs/observability/grafana-dashboard.json
git commit -m "docs(observability): add Grafana dashboard template (#26)"
```

---

### Task 11: Create Alert Rules YAML

**Files:**
- Create: `docs/observability/alert-rules.yml`

- [ ] **Step 1: Write alert-rules.yml**

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
          description: "{{ $value }} messages exceeded max retries in the last 5 minutes"

      - alert: CeleryOutboxQueueBacklog
        expr: celery_outbox_queue_depth > 5000
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Outbox queue depth > 5000"
          description: "Queue depth is {{ $value }}, relay may be stalled"

      - alert: CeleryOutboxHighFailureRate
        expr: |
          rate(celery_outbox_messages_failed_total[5m])
          / rate(celery_outbox_messages_published_total[5m]) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Message failure rate > 5%"
          description: "Failure rate is {{ $value | humanizePercentage }}"

      - alert: CeleryOutboxStuck
        expr: celery_outbox_oldest_pending_age_seconds > 300
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Messages stuck in outbox > 5 minutes"
          description: "Oldest pending message is {{ $value | humanizeDuration }} old"

      - alert: CeleryOutboxRelayDown
        expr: up{job="celery-outbox-relay"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Celery outbox relay is down"
          description: "No metrics received from relay for 2 minutes"
```

- [ ] **Step 2: Commit**

```bash
git add docs/observability/alert-rules.yml
git commit -m "docs(observability): add Prometheus alert rules (#26)"
```

---

### Task 12: Create Log Sampling Guide

**Files:**
- Create: `docs/observability/log-sampling.md`

- [ ] **Step 1: Write log-sampling.md**

```markdown
# Log Sampling for High-Throughput Deployments

At >1000 messages/second, logging can become a bottleneck. This guide covers optimization strategies.

## Log Volume Analysis

| Event | Frequency | Typical Volume | Recommendation |
|-------|-----------|----------------|----------------|
| `celery_outbox_batch_processed` | Per cycle | ~1-2/sec | Log all |
| `celery_outbox_relay_idle` | When idle | ~1-10/sec | Set DEBUG level |
| `celery_outbox_relay_busy` | When busy | ~1-10/sec | Set DEBUG level |
| `celery_outbox_send_failed` | Per failure | Variable | Log all (important) |
| `celery_outbox_max_retries_exceeded` | Rare | ~0.001/sec | Log all (critical) |

## Recommendations

### 1. Filter DEBUG Events

Configure structlog to filter DEBUG level in production:

```python
LOGGING = {
    'loggers': {
        'django_celery_outbox.relay': {
            'level': 'INFO',  # Skip DEBUG events
        },
    },
}
```

### 2. Disable Task Name Tags

For high cardinality scenarios (>100 unique task names):

```python
CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS = True
```

Or use an allowlist:

```python
CELERY_OUTBOX_MONITORED_TASKS = {'critical.task1', 'critical.task2'}
```

### 3. Use Async Log Handlers

Configure structlog with async handlers to prevent blocking:

```python
import structlog
from structlog.stdlib import AsyncBoundLogger

structlog.configure(
    wrapper_class=AsyncBoundLogger,
    # ...
)
```

### 4. Sample Non-Critical Logs

For very high volume, consider sampling in your log processor:

```python
import random

def sample_processor(logger, method_name, event_dict):
    if event_dict.get('event') in ('celery_outbox_relay_idle', 'celery_outbox_relay_busy'):
        if random.random() > 0.1:  # 10% sample rate
            raise structlog.DropEvent
    return event_dict
```

## Monitoring Log Volume

Track log volume with StatsD:

```python
# In structlog processor
def count_logs(logger, method_name, event_dict):
    from django_celery_outbox import metrics
    metrics.increment('log.events', tags={'event': event_dict.get('event', 'unknown')})
    return event_dict
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/observability/log-sampling.md
git commit -m "docs(observability): add log sampling guide (#26)"
```

---

### Task 13: Add Security Section to README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Locate Configuration section in README**

Read README.md to find the Configuration section location.

- [ ] **Step 2: Add Security Considerations section after Configuration**

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
        'schedule': crontab(hour=3, minute=0),
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

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): add security considerations section (#33)"
```

---

### Task 14: Run Full Test Suite and Final Verification

**Files:**
- All modified files

- [ ] **Step 1: Run full test suite**

```bash
docker compose run --rm app pytest -v
```

Expected: All tests PASS

- [ ] **Step 2: Run mypy type checking**

```bash
docker compose run --rm app mypy django_celery_outbox
```

Expected: No errors

- [ ] **Step 3: Run ruff linting**

```bash
docker compose run --rm app ruff check django_celery_outbox
```

Expected: No errors

- [ ] **Step 4: Create final commit if any fixes needed**

```bash
git add -A
git commit -m "chore: fix linting and type errors"
```

- [ ] **Step 5: Push branch**

```bash
git push -u origin observability-security-hardening
```
