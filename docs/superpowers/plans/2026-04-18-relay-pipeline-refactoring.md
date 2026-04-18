# Relay Pipeline Refactoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the relay hot path into small internal collaborators without changing public APIs, settings, CLI flags, signals, or migration history.

**Architecture:** Keep `Relay` as the public orchestration class in `django_celery_outbox/relay/_relay.py`, but move publish logic, batch DB mutations, and runtime-specific helpers into three internal modules. Preserve current behavior by reusing the existing serializer, metrics module, models, and signal flow, while shifting tests away from patching `_send_task()` and other private helper methods.

**Tech Stack:** Python 3.12, Django ORM, Celery, structlog, sentry-sdk, pytest, docker compose

**Spec:** `docs/superpowers/specs/2026-04-11-audit-refactoring-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `django_celery_outbox/relay/_runtime.py` | Create | `ProcessResult`, exception classification, and traceback logging policy |
| `django_celery_outbox/relay/_publisher.py` | Create | Deserialize message options, restore headers/context, call raw `Celery.send_task()` |
| `django_celery_outbox/relay/_mutations.py` | Create | Retry updates, delete published rows, move exceeded rows to dead letter |
| `django_celery_outbox/relay/_relay.py` | Modify | Orchestrate selector, publisher, and mutation helpers while preserving behavior |
| `django_celery_outbox/relay/relay_exception_tests.py` | Modify | Runtime helper tests moved off `_relay.py` |
| `django_celery_outbox/relay/publisher_tests.py` | Create | Focused tests for publish-path behavior |
| `django_celery_outbox/relay/mutations_tests.py` | Create | Focused tests for DB mutation behavior |
| `tests/relay_tests.py` | Modify | Keep selector/orchestration coverage and stop asserting private helper implementations directly |
| `django_celery_outbox/signals_tests.py` | Modify | Retarget relay signal tests away from `_send_task` |
| `django_celery_outbox/integration_tests.py` | Modify | Retarget end-to-end publish patches to `_publisher.Celery.send_task` |
| `ARCHITECTURE.md` | Modify | Replace stale monolithic relay descriptions across all matching sections |
| `docs/architecture.md` | Modify | Update the published architecture page to match the new relay structure |

---

### Task 1: Extract Runtime Helpers From `_relay.py`

**Files:**
- Create: `django_celery_outbox/relay/_runtime.py`
- Modify: `django_celery_outbox/relay/relay_exception_tests.py`
- Modify: `django_celery_outbox/relay/_relay.py`

- [ ] **Step 1: Write the failing runtime-helper tests**

Update `django_celery_outbox/relay/relay_exception_tests.py` to import from the new module and cover both exception classification and traceback policy:

```python
from django.test import override_settings

from django_celery_outbox.relay._runtime import (
    ProcessResult,
    classify_exception,
    should_log_traceback,
)


def test_process_result_enum_members() -> None:
    assert ProcessResult.PUBLISHED.name == 'PUBLISHED'
    assert ProcessResult.FAILED.name == 'FAILED'
    assert ProcessResult.EXCEEDED.name == 'EXCEEDED'


def test_classify_exception_connection_error() -> None:
    exc = ConnectionError('broker down')
    assert classify_exception(exc) == 'connection'


def test_classify_exception_timeout_error() -> None:
    exc = TimeoutError('timed out')
    assert classify_exception(exc) == 'timeout'


def test_classify_exception_os_error() -> None:
    exc = OSError('system error')
    assert classify_exception(exc) == 'os_error'


def test_classify_exception_unknown() -> None:
    exc = ValueError('some value error')
    assert classify_exception(exc) == 'unknown'


def test_classify_exception_subclass() -> None:
    exc = BrokenPipeError('pipe broken')
    assert classify_exception(exc) == 'connection'


@override_settings(CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK=True)
def test_should_log_traceback_defaults_to_true() -> None:
    assert should_log_traceback() is True


@override_settings(CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK=False)
def test_should_log_traceback_honors_setting() -> None:
    assert should_log_traceback() is False
```

- [ ] **Step 2: Run the runtime-helper tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_exception_tests.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'django_celery_outbox.relay._runtime'`

- [ ] **Step 3: Implement the runtime helper module and rewire `_relay.py`**

Create `django_celery_outbox/relay/_runtime.py`:

```python
from enum import Enum, auto

from django.conf import settings


class ProcessResult(Enum):
    PUBLISHED = auto()
    FAILED = auto()
    EXCEEDED = auto()


_EXCEPTION_CATEGORIES: dict[type[Exception], str] = {
    ConnectionError: 'connection',
    TimeoutError: 'timeout',
    OSError: 'os_error',
}


def classify_exception(exc: Exception) -> str:
    for exc_class, label in _EXCEPTION_CATEGORIES.items():
        if isinstance(exc, exc_class):
            return label

    return 'unknown'


def should_log_traceback() -> bool:
    return getattr(settings, 'CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK', True)
```

Update the top of `django_celery_outbox/relay/_relay.py`:

```python
from django_celery_outbox.relay._runtime import (
    ProcessResult,
    classify_exception,
    should_log_traceback,
)
```

Remove the in-file definitions of `ProcessResult`, `_EXCEPTION_CATEGORIES`, `_classify_exception()`, and `_should_log_traceback()`, then update call sites:

```python
                exc_type = classify_exception(exc)

                if should_log_traceback():
                    _logger.error('celery_outbox_send_failed', **log_kwargs, exc_info=True)
                else:
                    _logger.error('celery_outbox_send_failed', **log_kwargs)
```

- [ ] **Step 4: Run the runtime-helper tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/relay_exception_tests.py -v`
Expected: PASS

- [ ] **Step 5: Commit the runtime helper extraction**

```bash
git add django_celery_outbox/relay/_runtime.py django_celery_outbox/relay/_relay.py django_celery_outbox/relay/relay_exception_tests.py
git commit -m "refactor: extract relay runtime helpers"
```

---

### Task 2: Extract The Publish Path Into `_publisher.py`

**Files:**
- Create: `django_celery_outbox/relay/_publisher.py`
- Create: `django_celery_outbox/relay/publisher_tests.py`

- [ ] **Step 1: Write the failing publish-path tests**

Create `django_celery_outbox/relay/publisher_tests.py`:

```python
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from celery import Celery

from django_celery_outbox.models import CeleryOutbox
from django_celery_outbox.relay._publisher import RelayPublisher, parse_structlog_context


@pytest.fixture()
def m_celery_app() -> MagicMock:
    app = MagicMock(spec=Celery)
    app.send_task = MagicMock()
    return app


@pytest.mark.django_db
def test_publish_calls_raw_celery_send_task(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app)
    eta_dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    msg = CeleryOutbox.objects.create(
        task_id='abc-123',
        task_name='myapp.tasks.do_stuff',
        args=[1, 2],
        kwargs={'key': 'val'},
        options={'eta': eta_dt.isoformat(), 'priority': 9},
        sentry_trace_id='trace-id-1',
        sentry_baggage='baggage-1',
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task') as m_send:
        publisher.publish(msg)

    _, kwargs = m_send.call_args
    assert kwargs['name'] == 'myapp.tasks.do_stuff'
    assert kwargs['args'] == [1, 2]
    assert kwargs['kwargs'] == {'key': 'val'}
    assert kwargs['task_id'] == 'abc-123'
    assert kwargs['eta'] == eta_dt
    assert kwargs['priority'] == 9
    assert kwargs['headers']['sentry-trace'] == 'trace-id-1'
    assert kwargs['headers']['baggage'] == 'baggage-1'


@pytest.mark.django_db
def test_publish_binds_structlog_context(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app)
    msg = CeleryOutbox.objects.create(
        task_id='ctx-123',
        task_name='myapp.tasks.ctx',
        options={},
        structlog_context=json.dumps({'request_id': 'req-1'}),
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
        with patch('django_celery_outbox.relay._publisher.structlog.contextvars.bound_contextvars') as m_bound:
            publisher.publish(msg)

    m_bound.assert_called_once_with(request_id='req-1')


@pytest.mark.django_db
def test_publish_tolerates_headers_none(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app)
    msg = CeleryOutbox.objects.create(
        task_id='headers-none',
        task_name='myapp.tasks.headers',
        options={'headers': None},
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task') as m_send:
        publisher.publish(msg)

    _, kwargs = m_send.call_args
    assert kwargs['headers'] == {}


@pytest.mark.django_db
def test_publish_without_sentry_context_does_not_add_headers(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app)
    msg = CeleryOutbox.objects.create(
        task_id='no-sentry',
        task_name='myapp.tasks.no_sentry',
        options={},
        sentry_trace_id=None,
        sentry_baggage=None,
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task') as m_send:
        publisher.publish(msg)

    _, kwargs = m_send.call_args
    assert kwargs['headers'] == {}


@pytest.mark.django_db
def test_publish_propagates_extra_options(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app)
    msg = CeleryOutbox.objects.create(
        task_id='extra-opts',
        task_name='myapp.tasks.extra',
        options={'priority': 9, 'routing_key': 'high'},
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task') as m_send:
        publisher.publish(msg)

    _, kwargs = m_send.call_args
    assert kwargs['priority'] == 9
    assert kwargs['routing_key'] == 'high'


@pytest.mark.django_db
def test_publish_passes_schema_version_to_deserializer(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app)
    msg = CeleryOutbox.objects.create(
        task_id='schema-v2',
        task_name='myapp.tasks.schema',
        options={'priority': 9},
        schema_version=2,
    )

    with patch('django_celery_outbox.relay._publisher.deserialize_options', return_value={'priority': 9}) as m_deserialize:
        with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
            publisher.publish(msg)

    m_deserialize.assert_called_once_with(msg.options, m_celery_app, 2)


def test_parse_structlog_context_valid_json() -> None:
    assert parse_structlog_context('{"k": "v"}') == {'k': 'v'}


def test_parse_structlog_context_empty_string_returns_empty_dict() -> None:
    assert parse_structlog_context('') == {}


def test_parse_structlog_context_invalid_json_returns_empty_dict() -> None:
    assert parse_structlog_context('invalid') == {}


def test_parse_structlog_context_none_returns_empty_dict() -> None:
    assert parse_structlog_context(None) == {}


def test_parse_structlog_context_non_object_json_returns_empty_dict() -> None:
    assert parse_structlog_context('[]') == {}
```

- [ ] **Step 2: Run the publish-path tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/publisher_tests.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'django_celery_outbox.relay._publisher'`

- [ ] **Step 3: Implement `RelayPublisher`**

Create `django_celery_outbox/relay/_publisher.py`:

```python
import json
from typing import Any

import structlog
from celery import Celery

from django_celery_outbox.models import CeleryOutbox
from django_celery_outbox.serialization import deserialize_options


def parse_structlog_context(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}

    return parsed if isinstance(parsed, dict) else {}


class RelayPublisher:
    def __init__(self, app: Celery) -> None:
        self._app = app

    def publish(self, msg: CeleryOutbox) -> None:
        options = deserialize_options(msg.options, self._app, msg.schema_version)

        headers = options.pop('headers', {}) or {}
        if msg.sentry_trace_id:
            headers['sentry-trace'] = msg.sentry_trace_id
        if msg.sentry_baggage:
            headers['baggage'] = msg.sentry_baggage

        eta = options.pop('eta', None)
        ctx = parse_structlog_context(msg.structlog_context)

        with structlog.contextvars.bound_contextvars(**ctx):
            Celery.send_task(
                self._app,
                name=msg.task_name,
                args=msg.args,
                kwargs=msg.kwargs,
                task_id=msg.task_id,
                eta=eta,
                headers=headers,
                **options,
            )
```

- [ ] **Step 4: Run the publish-path tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/publisher_tests.py -v`
Expected: PASS

- [ ] **Step 5: Commit the publish-path extraction**

```bash
git add django_celery_outbox/relay/_publisher.py django_celery_outbox/relay/publisher_tests.py
git commit -m "refactor: extract relay publisher"
```

---

### Task 3: Extract Batch Mutations Into `_mutations.py`

**Files:**
- Create: `django_celery_outbox/relay/_mutations.py`
- Create: `django_celery_outbox/relay/mutations_tests.py`

- [ ] **Step 1: Write the failing mutation tests**

Create `django_celery_outbox/relay/mutations_tests.py`:

```python
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter
from django_celery_outbox.relay._mutations import RelayMutations


@pytest.mark.django_db
def test_update_failed_increments_retries_and_sets_retry_after() -> None:
    mutations = RelayMutations(backoff_time=120)
    before = timezone.now()
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=1,
        updated_at=None,
    )

    with patch('django_celery_outbox.relay._mutations.random.uniform', return_value=0):
        mutations.update_failed([(msg.id, 1)])

    msg.refresh_from_db()
    assert msg.retries == 2
    assert msg.updated_at is not None
    assert msg.retry_after is not None
    assert msg.retry_after >= before + timedelta(seconds=239)


@pytest.mark.django_db
def test_update_failed_applies_per_message_jitter_for_same_retry_count() -> None:
    mutations = RelayMutations(backoff_time=120)
    msg1 = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=0,
        updated_at=None,
    )
    msg2 = CeleryOutbox.objects.create(
        task_id='task-2',
        task_name='some.task',
        retries=0,
        updated_at=None,
    )

    with patch('django_celery_outbox.relay._mutations.random.uniform', side_effect=[0, 12]):
        mutations.update_failed([(msg1.id, 0), (msg2.id, 0)])

    msg1.refresh_from_db()
    msg2.refresh_from_db()

    assert msg1.retries == 1
    assert msg2.retries == 1
    assert msg1.retry_after is not None
    assert msg2.retry_after is not None
    assert msg2.retry_after > msg1.retry_after + timedelta(seconds=11)


@pytest.mark.django_db
def test_delete_published_removes_only_requested_rows() -> None:
    mutations = RelayMutations(backoff_time=120)
    msg1 = CeleryOutbox.objects.create(task_id='task-1', task_name='some.task')
    msg2 = CeleryOutbox.objects.create(task_id='task-2', task_name='some.task')

    mutations.delete_published([msg1.id])

    assert not CeleryOutbox.objects.filter(pk=msg1.id).exists()
    assert CeleryOutbox.objects.filter(pk=msg2.id).exists()


@pytest.mark.django_db
def test_delete_published_noops_for_empty_list() -> None:
    mutations = RelayMutations(backoff_time=120)
    msg = CeleryOutbox.objects.create(task_id='task-1', task_name='some.task')

    mutations.delete_published([])

    assert CeleryOutbox.objects.filter(pk=msg.id).exists()


@pytest.mark.django_db
def test_move_exceeded_to_dead_letter_preserves_message_fields() -> None:
    mutations = RelayMutations(backoff_time=120)
    msg = CeleryOutbox.objects.create(
        task_id='task-dead',
        task_name='some.task',
        args=[1],
        kwargs={'a': 1},
        redacted_args=['x'],
        redacted_kwargs={'a': 'x'},
        options={'priority': 9},
        retries=5,
        schema_version=2,
        sentry_trace_id='trace',
        sentry_baggage='baggage',
        structlog_context='{\"request_id\": \"req-1\"}',
    )

    mutations.move_exceeded_to_dead_letter([msg])

    dead = CeleryOutboxDeadLetter.objects.get(task_id='task-dead')
    assert dead.task_name == 'some.task'
    assert dead.args == [1]
    assert dead.kwargs == {'a': 1}
    assert dead.redacted_args == ['x']
    assert dead.redacted_kwargs == {'a': 'x'}
    assert dead.options == {'priority': 9}
    assert dead.schema_version == 2
    assert dead.failure_reason == 'max retries exceeded'
    assert not CeleryOutbox.objects.filter(pk=msg.id).exists()


@pytest.mark.django_db
def test_move_exceeded_to_dead_letter_noops_for_empty_list() -> None:
    mutations = RelayMutations(backoff_time=120)

    mutations.move_exceeded_to_dead_letter([])

    assert CeleryOutboxDeadLetter.objects.count() == 0
```

- [ ] **Step 2: Run the mutation tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/mutations_tests.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'django_celery_outbox.relay._mutations'`

- [ ] **Step 3: Implement `RelayMutations`**

Create `django_celery_outbox/relay/_mutations.py`:

```python
import random
from datetime import timedelta

from django.db.models import Case, DateTimeField, DurationField, ExpressionWrapper, F, Value, When
from django.db.models.functions import Now

from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter


class RelayMutations:
    def __init__(self, backoff_time: int) -> None:
        self._backoff_time = backoff_time

    def update_failed(self, failed_messages: list[tuple[int, int]]) -> None:
        if not failed_messages:
            return

        retry_after_cases: list[When] = []
        message_ids: list[int] = []

        for msg_id, retries in failed_messages:
            jitter = random.uniform(0, self._backoff_time * 0.1)  # noqa: S311
            delay = timedelta(seconds=self._backoff_time * (2**retries) + jitter)
            message_ids.append(msg_id)
            retry_after_cases.append(
                When(
                    pk=msg_id,
                    then=ExpressionWrapper(
                        Now() + Value(delay, output_field=DurationField()),
                        output_field=DateTimeField(),
                    ),
                )
            )

        CeleryOutbox.objects.filter(pk__in=message_ids).update(
            retries=F('retries') + 1,
            updated_at=Now(),
            retry_after=Case(*retry_after_cases, output_field=DateTimeField()),
        )

    def delete_published(self, message_ids: list[int]) -> None:
        if not message_ids:
            return

        CeleryOutbox.objects.filter(pk__in=message_ids).delete()

    def move_exceeded_to_dead_letter(self, exceeded_messages: list[CeleryOutbox]) -> None:
        if not exceeded_messages:
            return

        dead_letters = [
            CeleryOutboxDeadLetter(
                created_at=msg.created_at,
                retries=msg.retries,
                task_id=msg.task_id,
                task_name=msg.task_name,
                args=msg.args,
                kwargs=msg.kwargs,
                redacted_args=msg.redacted_args,
                redacted_kwargs=msg.redacted_kwargs,
                options=msg.options,
                sentry_trace_id=msg.sentry_trace_id,
                sentry_baggage=msg.sentry_baggage,
                structlog_context=msg.structlog_context,
                schema_version=msg.schema_version,
                failure_reason='max retries exceeded',
            )
            for msg in exceeded_messages
        ]

        CeleryOutboxDeadLetter.objects.bulk_create(dead_letters)
        CeleryOutbox.objects.filter(pk__in=[msg.id for msg in exceeded_messages]).delete()
```

- [ ] **Step 4: Run the mutation tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/relay/mutations_tests.py -v`
Expected: PASS

- [ ] **Step 5: Commit the mutation extraction**

```bash
git add django_celery_outbox/relay/_mutations.py django_celery_outbox/relay/mutations_tests.py
git commit -m "refactor: extract relay batch mutations"
```

---

### Task 4: Rewire `Relay` To Orchestrate The New Collaborators

**Files:**
- Modify: `django_celery_outbox/relay/_relay.py`
- Modify: `tests/relay_tests.py`
- Modify: `django_celery_outbox/signals_tests.py`
- Modify: `django_celery_outbox/integration_tests.py`

- [ ] **Step 1: Rewrite orchestration tests around collaborators instead of private helper bodies**

Update the most coupled tests in `tests/relay_tests.py`:

```python
from django_celery_outbox.relay._mutations import RelayMutations
from django_celery_outbox.relay._publisher import RelayPublisher
```

Replace direct `_send_task()` patching in the processing tests:

```python
@pytest.mark.django_db
def test_process_messages_success(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=0,
    )

    with patch.object(f_relay._publisher, 'publish'):
        published, failed, exceeded = f_relay._process_messages([msg])

    assert published == [msg.id]
    assert failed == []
    assert exceeded == []


@pytest.mark.django_db
def test_process_messages_send_failure(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=0,
    )

    with patch.object(f_relay._publisher, 'publish', side_effect=RuntimeError('broker down')):
        published, failed, exceeded = f_relay._process_messages([msg])

    assert published == []
    assert failed == [(msg.id, 0)]
    assert exceeded == []


@pytest.mark.django_db
def test_process_messages_failure_at_max_retries(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=2,
    )

    with patch.object(f_relay._publisher, 'publish', side_effect=RuntimeError('fail')):
        published, failed, exceeded = f_relay._process_messages([msg])

    assert published == []
    assert failed == []
    assert [message.id for message in exceeded] == [msg.id]
```

Delete the direct unit tests for `_send_task()`, `_parse_structlog_context()`, `_update_failed()`, `_delete_done()`, and `_move_to_dead_letter()` from `tests/relay_tests.py`; before deleting them, make sure their coverage is preserved in `publisher_tests.py`, `mutations_tests.py`, and `relay_exception_tests.py`:

- keep empty-string, invalid, `None`, and non-object JSON coverage for `parse_structlog_context()`
- keep no-op coverage for `update_failed([])` and `delete_published([])`
- keep missing-sentry-header and arbitrary-option propagation coverage in `publisher_tests.py`
- keep schema-version pass-through coverage for `deserialize_options()`

Update `django_celery_outbox/signals_tests.py` to patch `f_relay._publisher.publish` instead of `f_relay._send_task` where `_process_messages()` is the seam under test.

```python
@pytest.mark.django_db
def test_outbox_message_sent_fires_on_successful_relay(f_relay: Relay) -> None:
    msg = CeleryOutboxFactory.create(
        task_id='sent-task-1',
        task_name='some.task',
        options={},
        retries=0,
    )

    received = []

    def handler(sender: type, **kwargs: object) -> None:
        received.append(kwargs)

    outbox_message_sent.connect(handler)
    try:
        with patch.object(f_relay._publisher, 'publish'):
            f_relay._process_messages([msg])
    finally:
        outbox_message_sent.disconnect(handler)

    assert len(received) == 1
    assert received[0]['task_id'] == 'sent-task-1'
```

Update `django_celery_outbox/integration_tests.py` low-level send patches from `django_celery_outbox.relay._relay.Celery.send_task` to `django_celery_outbox.relay._publisher.Celery.send_task`.

```python
@pytest.fixture()
def m_celery_send() -> Generator[MagicMock]:
    with patch('django_celery_outbox.relay._publisher.Celery.send_task') as mock:
        yield mock
```

- [ ] **Step 2: Run the relay orchestration tests to verify they fail**

Run: `docker compose run --rm app pytest tests/relay_tests.py::test_process_messages_success tests/relay_tests.py::test_process_messages_send_failure tests/relay_tests.py::test_process_messages_failure_at_max_retries tests/relay_tests.py::test_processing_full_cycle django_celery_outbox/signals_tests.py::test_outbox_message_sent_fires_on_successful_relay -v`
Expected: FAIL because `Relay` does not yet have `_publisher`/`_mutations` collaborators and `exceeded` still returns IDs

- [ ] **Step 3: Refactor `_relay.py` into an orchestration layer**

Update `django_celery_outbox/relay/_relay.py` imports:

```python
from django_celery_outbox.relay._mutations import RelayMutations
from django_celery_outbox.relay._publisher import RelayPublisher
from django_celery_outbox.relay._runtime import (
    ProcessResult,
    classify_exception,
    should_log_traceback,
)
```

Update `Relay.__init__()` to create collaborator instances:

```python
        self._app = app
        self._config = config
        self._selector = selector or MessageSelector(
            batch_size=config.batch_size,
            stale_timeout=timedelta(seconds=config.stale_timeout_seconds),
        )
        self._publisher = RelayPublisher(app=app)
        self._mutations = RelayMutations(backoff_time=config.backoff_time)
        self._running = True
```

Change the processing flow to delegate DB mutations:

```python
            published, failed, exceeded = self._process_messages(messages)

            close_old_connections()

            with transaction.atomic():
                self._mutations.update_failed(failed)
                self._mutations.delete_published(published)
                self._mutations.move_exceeded_to_dead_letter(exceeded)

                for msg in exceeded:
                    self._send_signal_safe(
                        outbox_message_dead_lettered,
                        msg.task_id,
                        msg.task_name,
                        task_ids=[msg.task_id],
                        task_names=[msg.task_name],
                    )
```

Change `_process_messages()` and `_process_message()` to use the publisher and return loaded exceeded messages:

```python
    def _process_messages(
        self,
        messages: list[CeleryOutbox],
    ) -> tuple[list[int], list[tuple[int, int]], list[CeleryOutbox]]:
        published: list[int] = []
        failed: list[tuple[int, int]] = []
        exceeded: list[CeleryOutbox] = []
```

```python
                self._publisher.publish(msg)
            except Exception as exc:
                span.set_status('internal_error')
                exc_type = classify_exception(exc)
```

```python
                    return ProcessResult.EXCEEDED
                tags = get_task_tag(msg.task_name)
                tags['exception_type'] = exc_type
                metrics.increment('messages.failed', tags=tags)
                self._send_signal_safe(outbox_message_failed, msg.task_id, msg.task_name, retries=msg.retries)
                return ProcessResult.FAILED
```

Delete the in-file implementations of `_send_task()`, `_parse_structlog_context()`, `_update_failed()`, `_delete_done()`, and `_move_to_dead_letter()`.

Update remaining patch targets in `tests/relay_tests.py`, `django_celery_outbox/signals_tests.py`, and `django_celery_outbox/integration_tests.py` from `_relay.Celery.send_task` to `_publisher.Celery.send_task` where the real publish path is exercised:

```python
with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
    ...
```

- [ ] **Step 4: Run the relay test slices to verify they pass**

Run: `docker compose run --rm app pytest tests/relay_tests.py django_celery_outbox/signals_tests.py django_celery_outbox/integration_tests.py django_celery_outbox/relay/relay_exception_tests.py django_celery_outbox/relay/publisher_tests.py django_celery_outbox/relay/mutations_tests.py -v`
Expected: PASS

- [ ] **Step 5: Commit the relay orchestration refactor**

```bash
git add django_celery_outbox/relay/_relay.py tests/relay_tests.py django_celery_outbox/signals_tests.py django_celery_outbox/integration_tests.py
git commit -m "refactor: make relay an orchestration layer"
```

---

### Task 5: Refresh Architecture Docs And Run Full Verification

**Files:**
- Modify: `ARCHITECTURE.md`
- Modify: `docs/architecture.md`

- [ ] **Step 1: Write the failing documentation expectations by identifying stale relay wording**

Search for the stale relay descriptions:

```bash
rg -n '_send_task|_update_failed|_move_to_dead_letter|_processing|relay\.py|Relay \(`relay\.py`\)' ARCHITECTURE.md docs/architecture.md
```

Expected: matches show both documents still describe a monolithic relay implementation and private helper methods that will no longer exist.

- [ ] **Step 2: Update the relay architecture section**

Replace every stale relay section in `ARCHITECTURE.md` and `docs/architecture.md` so they describe the new internal collaborators:

```markdown
### 3. Relay (`relay/_relay.py`)

`Relay` remains the public daemon/orchestration class, but the hot path is split into
small internal collaborators:

- `MessageSelector` selects pending rows and marks them in-flight
- `RelayPublisher` restores options, headers, and structlog context, then calls raw `Celery.send_task()`
- `RelayMutations` applies retry updates, deletes published rows, and moves exceeded rows to dead letter
- `_runtime.py` holds exception classification and traceback logging policy

#### Processing Loop

relay.start()
    -> _setup_signals()
    -> _setup_delayed_delivery()
    -> while _running:
         -> _processing()
             -> selector.run()
             -> _process_messages()
                 -> publisher.publish(msg)
             -> mutations.update_failed(failed)
             -> mutations.delete_published(published)
             -> mutations.move_exceeded_to_dead_letter(exceeded)
             -> batch metrics / liveness / idle decision
```

Keep the rest of the document behavior-focused: selection semantics, retry semantics, dead-letter semantics, and emitted metrics all remain unchanged.

- [ ] **Step 3: Run focused verification for docs and relay paths**

Run these commands:

```bash
rg -n '_send_task|_update_failed|_move_to_dead_letter|relay\.py' ARCHITECTURE.md docs/architecture.md
docker compose run --rm app pytest tests/relay_tests.py django_celery_outbox/signals_tests.py django_celery_outbox/integration_tests.py django_celery_outbox/relay -v
```

Expected:
- `rg`: no stale helper/module hits remain in the updated architecture docs
- `pytest`: PASS

- [ ] **Step 4: Run the full project verification**

Run these commands:

```bash
docker compose run --rm app pytest -v
DB_ENGINE=mysql DB_HOST=127.0.0.1 DB_NAME=test_db DB_USER=root DB_PASSWORD=root DB_PORT=3306 .venv-wsl/bin/pytest tests/relay_tests.py django_celery_outbox/signals_tests.py django_celery_outbox/integration_tests.py -v
docker compose run --rm app ruff check .
docker compose run --rm app mypy -p django_celery_outbox --config-file=pyproject.toml
```

Expected:
- `pytest`: PASS
- targeted MySQL relay/integration slice: PASS, or the same slice passes in CI matrix if local MySQL is unavailable
- `ruff check`: `All checks passed!`
- `mypy`: `Success: no issues found`

- [ ] **Step 5: Commit the documentation and verification pass**

```bash
git add ARCHITECTURE.md docs/architecture.md
git commit -m "docs: describe relay collaborators"
```

---

## Self-Review

### Spec Coverage

- Internal relay decomposition: covered by Tasks 1-4
- Preserve public API and behavior: enforced in Task 4 and verified in Tasks 4-5
- Reduce private-method patching: covered by Tasks 2-4
- Update architecture docs: covered by Task 5
- Avoid package-wide redesign, migration changes, and benchmark framework: intentionally omitted from the plan

### Placeholder Scan

- No `TBD`, `TODO`, or "implement later" placeholders remain
- Every task has exact file paths, concrete tests, run commands, and commit commands

### Type Consistency

- `RelayPublisher.publish(msg: CeleryOutbox) -> None` is used consistently in tests and orchestration
- `RelayMutations.update_failed(failed: list[tuple[int, int]]) -> None` is used consistently in tests and orchestration
- `_process_messages()` returns `list[CeleryOutbox]` for exceeded messages consistently after Task 4
