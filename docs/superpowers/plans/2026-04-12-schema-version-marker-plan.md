# Schema Version Marker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `schema_version` field to outbox models for future format migration support.

**Architecture:** SmallIntegerField on both CeleryOutbox and CeleryOutboxDeadLetter. Relay filters by supported version range. Versioned deserializers dispatch by version number.

**Tech Stack:** Django 4.2+, Python 3.10+, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `models.py` | Add `schema_version` field to both models |
| `migrations/0002_schema_version.py` | Migration for new field |
| `serialization.py` | Version constants, UnsupportedSchemaVersionError, versioned deserializers |
| `relay.py` | Filter by version range, pass version to deserialize, copy to dead letter |
| `app.py` | Set CURRENT_SCHEMA_VERSION on create |
| `admin.py` | Add to list_display, list_filter, readonly_fields; update retry_selected |
| `factories.py` | Add schema_version to factories |
| `*_tests.py` | Tests for all changes |
| `README.md` | Schema versioning documentation |

---

### Task 1: Add schema_version field to models

**Files:**
- Modify: `django_celery_outbox/models.py:4-36`
- Modify: `django_celery_outbox/models.py:38-61`

- [ ] **Step 1: Add schema_version to CeleryOutbox model**

```python
# models.py line 17, after structlog_context field:
    schema_version = models.SmallIntegerField(default=1)
```

Add this line after line 20 (`structlog_context = models.TextField(null=True, blank=True)`).

- [ ] **Step 2: Add schema_version to CeleryOutboxDeadLetter model**

```python
# models.py line 54, after failure_reason field:
    schema_version = models.SmallIntegerField(default=1)
```

Add this line after line 55 (`failure_reason = models.TextField(null=True, blank=True)`).

- [ ] **Step 3: Commit**

```bash
git add django_celery_outbox/models.py
git commit -m "feat(models): add schema_version field to outbox models"
```

---

### Task 2: Create migration for schema_version

**Files:**
- Create: `django_celery_outbox/migrations/0002_schema_version.py`

- [ ] **Step 1: Generate migration**

```bash
docker compose run --rm app python manage.py makemigrations django_celery_outbox --name schema_version
```

Expected: Creates `0002_schema_version.py`

- [ ] **Step 2: Verify migration content**

The migration should contain two `AddField` operations, one for each model, both with `default=1`.

- [ ] **Step 3: Commit**

```bash
git add django_celery_outbox/migrations/0002_schema_version.py
git commit -m "feat(migrations): add schema_version migration"
```

---

### Task 3: Add version constants and exception to serialization

**Files:**
- Modify: `django_celery_outbox/serialization.py:1-9`
- Test: `django_celery_outbox/serialization_tests.py`

- [ ] **Step 1: Write failing test for UnsupportedSchemaVersionError**

Add to `serialization_tests.py`:

```python
from django_celery_outbox.serialization import (
    CURRENT_SCHEMA_VERSION,
    MIN_SUPPORTED_VERSION,
    UnsupportedSchemaVersionError,
    deserialize_options,
    serialize_options,
)


def test_current_schema_version_is_one() -> None:
    assert CURRENT_SCHEMA_VERSION == 1


def test_min_supported_version_is_one() -> None:
    assert MIN_SUPPORTED_VERSION == 1


def test_unsupported_schema_version_stores_version() -> None:
    exc = UnsupportedSchemaVersionError(99)

    assert exc.version == 99
    assert 'Unsupported schema version: 99' in str(exc)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm app pytest django_celery_outbox/serialization_tests.py::test_current_schema_version_is_one -v
```

Expected: FAIL with ImportError

- [ ] **Step 3: Add constants and exception**

Add at the top of `serialization.py`, after imports (line 8):

```python
CURRENT_SCHEMA_VERSION = 1
MIN_SUPPORTED_VERSION = 1


class UnsupportedSchemaVersionError(Exception):
    def __init__(self, version: int):
        self.version = version
        super().__init__(f'Unsupported schema version: {version}')
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose run --rm app pytest django_celery_outbox/serialization_tests.py::test_current_schema_version_is_one django_celery_outbox/serialization_tests.py::test_min_supported_version_is_one django_celery_outbox/serialization_tests.py::test_unsupported_schema_version_stores_version -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/serialization.py django_celery_outbox/serialization_tests.py
git commit -m "feat(serialization): add version constants and UnsupportedSchemaVersionError"
```

---

### Task 4: Refactor serialize_options to versioned function

**Files:**
- Modify: `django_celery_outbox/serialization.py`

- [ ] **Step 1: Rename serialize_options to _serialize_options_v1**

In `serialization.py`, rename the function at line 148:

```python
def _serialize_options_v1(
    options: dict[str, Any],
    countdown: float | None = None,
    eta: datetime | None = None,
) -> dict[str, Any]:
```

- [ ] **Step 2: Add wrapper serialize_options function**

Add after `_serialize_options_v1`:

```python
def serialize_options(
    options: dict[str, Any],
    countdown: float | None = None,
    eta: datetime | None = None,
) -> dict[str, Any]:
    return _serialize_options_v1(options, countdown, eta)
```

- [ ] **Step 3: Run existing tests to verify no regression**

```bash
docker compose run --rm app pytest django_celery_outbox/serialization_tests.py -v -k serialize
```

Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add django_celery_outbox/serialization.py
git commit -m "refactor(serialization): extract _serialize_options_v1"
```

---

### Task 5: Refactor deserialize_options to versioned function

**Files:**
- Modify: `django_celery_outbox/serialization.py`
- Test: `django_celery_outbox/serialization_tests.py`

- [ ] **Step 1: Write failing test for version parameter**

Add to `serialization_tests.py`:

```python
def test_deserialize_options_with_version_1(f_app: Celery) -> None:
    options = {'eta': '2025-01-15T12:00:00+00:00'}

    result = deserialize_options(options, f_app, schema_version=1)

    assert isinstance(result['eta'], datetime)


def test_deserialize_options_future_version_raises(f_app: Celery) -> None:
    with pytest.raises(UnsupportedSchemaVersionError) as exc_info:
        deserialize_options({}, f_app, schema_version=99)

    assert exc_info.value.version == 99


def test_deserialize_options_below_min_version_raises(f_app: Celery) -> None:
    with pytest.raises(UnsupportedSchemaVersionError) as exc_info:
        deserialize_options({}, f_app, schema_version=0)

    assert exc_info.value.version == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm app pytest django_celery_outbox/serialization_tests.py::test_deserialize_options_future_version_raises -v
```

Expected: FAIL (TypeError - missing argument)

- [ ] **Step 3: Rename deserialize_options to _deserialize_options_v1**

Rename the function (around line 185):

```python
def _deserialize_options_v1(options: dict[str, Any], app: Celery) -> dict[str, Any]:
```

- [ ] **Step 4: Add deserializers registry and new deserialize_options**

Add after `_deserialize_options_v1`:

```python
_DESERIALIZERS: dict[int, Any] = {
    1: _deserialize_options_v1,
}


def deserialize_options(options: dict[str, Any], app: Celery, schema_version: int) -> dict[str, Any]:
    if schema_version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(schema_version)

    if schema_version < MIN_SUPPORTED_VERSION:
        raise UnsupportedSchemaVersionError(schema_version)

    return _DESERIALIZERS[schema_version](options, app)
```

- [ ] **Step 5: Update all existing tests to pass schema_version=1**

Find all calls to `deserialize_options` in `serialization_tests.py` and add `schema_version=1`:

```python
# Example: line 411
result = deserialize_options(options, f_app, schema_version=1)
```

Update these tests:
- `test_deserialize_options_eta_string_to_datetime`
- `test_deserialize_options_expires_string_to_datetime`
- `test_deserialize_options_expires_int_stays_int`
- `test_deserialize_options_link_list_of_dicts_to_signatures`
- `test_deserialize_options_link_error_list_of_dicts_to_signatures`
- `test_deserialize_options_chain_list_to_signatures`
- `test_deserialize_options_chord_dict_to_signature`
- `test_deserialize_options_regular_keys_passed_through`
- `test_deserialize_options_does_not_mutate_original`
- `test_deserialize_options_empty_options`
- `test_deserialize_options_link_non_list_not_converted`
- `test_deserialize_options_chord_non_dict_not_converted`
- `test_deserialize_options_link_error_non_list_not_converted`
- `test_deserialize_options_chain_non_list_not_converted`
- `test_deserialize_options_invalid_eta_raises`

- [ ] **Step 6: Run all serialization tests**

```bash
docker compose run --rm app pytest django_celery_outbox/serialization_tests.py -v
```

Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add django_celery_outbox/serialization.py django_celery_outbox/serialization_tests.py
git commit -m "feat(serialization): add versioned deserialize_options with schema_version parameter"
```

---

### Task 6: Update relay to filter by schema_version

**Files:**
- Modify: `django_celery_outbox/relay.py:145-156` (_select_messages)
- Test: `django_celery_outbox/relay_tests.py`

- [ ] **Step 1: Write failing test for skipping future versions**

Add to `relay_tests.py`:

```python
@pytest.mark.django_db
def test_select_messages_skips_future_versions(f_app: Celery) -> None:
    msg_v1 = CeleryOutbox.objects.create(
        task_id='task-v1',
        task_name='app.task',
        schema_version=1,
    )
    CeleryOutbox.objects.create(
        task_id='task-v2',
        task_name='app.task',
        schema_version=2,
    )

    relay = Relay(f_app)
    messages = relay._select_messages()

    assert len(messages) == 1
    assert messages[0].id == msg_v1.id
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm app pytest django_celery_outbox/relay_tests.py::test_select_messages_skips_future_versions -v
```

Expected: FAIL (returns 2 messages)

- [ ] **Step 3: Add version import to relay.py**

Add to imports in `relay.py`:

```python
from django_celery_outbox.serialization import (
    CURRENT_SCHEMA_VERSION,
    MIN_SUPPORTED_VERSION,
    deserialize_options,
)
```

- [ ] **Step 4: Update _select_messages filter**

Modify `_select_messages` method to add version filter:

```python
def _select_messages(self) -> list[CeleryOutbox]:
    queryset = (
        CeleryOutbox.objects.select_for_update(
            skip_locked=True,
        )
        .filter(
            Q(updated_at__isnull=True) | Q(retry_after__lte=Now()) | Q(updated_at__lte=Now() - _STALE_TIMEOUT, retry_after__isnull=True),
            schema_version__gte=MIN_SUPPORTED_VERSION,
            schema_version__lte=CURRENT_SCHEMA_VERSION,
        )
        .order_by('id')[: self._batch_size]
    )

    return list(queryset)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
docker compose run --rm app pytest django_celery_outbox/relay_tests.py::test_select_messages_skips_future_versions -v
```

Expected: PASS

- [ ] **Step 6: Write test for skipping deprecated versions**

Add to `relay_tests.py`:

```python
@pytest.mark.django_db
def test_select_messages_skips_deprecated_versions(f_app: Celery) -> None:
    CeleryOutbox.objects.create(
        task_id='task-v0',
        task_name='app.task',
        schema_version=0,
    )
    msg_v1 = CeleryOutbox.objects.create(
        task_id='task-v1',
        task_name='app.task',
        schema_version=1,
    )

    relay = Relay(f_app)
    messages = relay._select_messages()

    assert len(messages) == 1
    assert messages[0].id == msg_v1.id
```

- [ ] **Step 7: Run test to verify it passes**

```bash
docker compose run --rm app pytest django_celery_outbox/relay_tests.py::test_select_messages_skips_deprecated_versions -v
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add django_celery_outbox/relay.py django_celery_outbox/relay_tests.py
git commit -m "feat(relay): filter messages by supported schema_version range"
```

---

### Task 7: Update relay _send_task to pass schema_version

**Files:**
- Modify: `django_celery_outbox/relay.py:217-240` (_send_task)

- [ ] **Step 1: Update _send_task to pass schema_version**

Modify `_send_task` method:

```python
def _send_task(self, msg: CeleryOutbox) -> None:
    options = deserialize_options(msg.options, self._app, msg.schema_version)
```

- [ ] **Step 2: Run existing relay tests to verify no regression**

```bash
docker compose run --rm app pytest django_celery_outbox/relay_tests.py -v
```

Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add django_celery_outbox/relay.py
git commit -m "feat(relay): pass schema_version to deserialize_options"
```

---

### Task 8: Update relay _move_to_dead_letter to preserve schema_version

**Files:**
- Modify: `django_celery_outbox/relay.py:290-323` (_move_to_dead_letter)
- Test: `django_celery_outbox/relay_tests.py`

- [ ] **Step 1: Write failing test**

Add to `relay_tests.py`:

```python
@pytest.mark.django_db
def test_dead_letter_preserves_schema_version(f_app: Celery) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='app.task',
        retries=5,
        schema_version=1,
    )

    relay = Relay(f_app, max_retries=5)
    relay._move_to_dead_letter([msg.id])

    dead = CeleryOutboxDeadLetter.objects.get(task_id='task-1')
    assert dead.schema_version == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm app pytest django_celery_outbox/relay_tests.py::test_dead_letter_preserves_schema_version -v
```

Expected: FAIL (AttributeError or AssertionError)

- [ ] **Step 3: Update _move_to_dead_letter**

Add `schema_version` to dead letter creation:

```python
dead_letters.append(
    CeleryOutboxDeadLetter(
        created_at=msg.created_at,
        retries=msg.retries,
        task_id=msg.task_id,
        task_name=msg.task_name,
        args=msg.args,
        kwargs=msg.kwargs,
        options=msg.options,
        sentry_trace_id=msg.sentry_trace_id,
        sentry_baggage=msg.sentry_baggage,
        structlog_context=msg.structlog_context,
        schema_version=msg.schema_version,
        failure_reason='max retries exceeded',
    )
)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
docker compose run --rm app pytest django_celery_outbox/relay_tests.py::test_dead_letter_preserves_schema_version -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/relay.py django_celery_outbox/relay_tests.py
git commit -m "feat(relay): preserve schema_version when moving to dead letter"
```

---

### Task 9: Update app.py to set CURRENT_SCHEMA_VERSION

**Files:**
- Modify: `django_celery_outbox/app.py`

- [ ] **Step 1: Add import**

Add to imports:

```python
from django_celery_outbox.serialization import CURRENT_SCHEMA_VERSION, serialize_options
```

Remove old import of just `serialize_options`.

- [ ] **Step 2: Update CeleryOutbox.objects.create call**

Add `schema_version` to the create call (around line 153):

```python
CeleryOutbox.objects.create(
    task_id=task_id,
    task_name=name,
    args=list(args) if args else [],
    kwargs=dict(kwargs) if kwargs else {},
    options=serialized_options,
    schema_version=CURRENT_SCHEMA_VERSION,
    sentry_trace_id=sentry_sdk.get_traceparent(),
    sentry_baggage=sentry_sdk.get_baggage(),
    structlog_context=get_structlog_context_json(),
)
```

- [ ] **Step 3: Run app tests to verify no regression**

```bash
docker compose run --rm app pytest django_celery_outbox/app_tests.py -v
```

Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add django_celery_outbox/app.py
git commit -m "feat(app): set schema_version on outbox message creation"
```

---

### Task 10: Update admin list_display, list_filter, readonly_fields

**Files:**
- Modify: `django_celery_outbox/admin.py`
- Test: `django_celery_outbox/admin_tests.py`

- [ ] **Step 1: Update test expectations**

Update `test_list_display` in `admin_tests.py`:

```python
def test_list_display() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    expected = ['id', 'task_name', 'task_id', 'retries', 'schema_version', 'created_at', 'updated_at']
    assert admin_instance.list_display == expected
```

Update `test_list_filter`:

```python
def test_list_filter() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    assert admin_instance.list_filter == ['task_name', 'retries', 'schema_version']
```

Update `test_readonly_fields`:

```python
def test_readonly_fields() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    expected = [
        'id',
        'task_name',
        'task_id',
        'args',
        'kwargs',
        'options',
        'retries',
        'schema_version',
        'created_at',
        'updated_at',
        'retry_after',
        'sentry_trace_id',
        'sentry_baggage',
        'structlog_context',
    ]
    assert admin_instance.readonly_fields == expected
```

Update `test_dead_letter_list_display`:

```python
def test_dead_letter_list_display() -> None:
    admin_instance = admin.site._registry[CeleryOutboxDeadLetter]

    expected = ['id', 'task_name', 'task_id', 'retries', 'schema_version', 'created_at', 'dead_at']
    assert admin_instance.list_display == expected
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm app pytest django_celery_outbox/admin_tests.py::test_list_display django_celery_outbox/admin_tests.py::test_list_filter django_celery_outbox/admin_tests.py::test_readonly_fields django_celery_outbox/admin_tests.py::test_dead_letter_list_display -v
```

Expected: FAIL

- [ ] **Step 3: Update CeleryOutboxAdmin in admin.py**

```python
list_display = [
    'id',
    'task_name',
    'task_id',
    'retries',
    'schema_version',
    'created_at',
    'updated_at',
]
list_filter = ['task_name', 'retries', 'schema_version']
```

Add `'schema_version'` to `readonly_fields` after `'retries'`.

- [ ] **Step 4: Update CeleryOutboxDeadLetterAdmin in admin.py**

```python
list_display = [
    'id',
    'task_name',
    'task_id',
    'retries',
    'schema_version',
    'created_at',
    'dead_at',
]
list_filter = ['task_name', 'dead_at', 'schema_version']
```

Add `'schema_version'` to `readonly_fields` after `'retries'`.

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker compose run --rm app pytest django_celery_outbox/admin_tests.py::test_list_display django_celery_outbox/admin_tests.py::test_list_filter django_celery_outbox/admin_tests.py::test_readonly_fields django_celery_outbox/admin_tests.py::test_dead_letter_list_display -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add django_celery_outbox/admin.py django_celery_outbox/admin_tests.py
git commit -m "feat(admin): add schema_version to list_display, list_filter, readonly_fields"
```

---

### Task 11: Update admin retry_selected to preserve schema_version

**Files:**
- Modify: `django_celery_outbox/admin.py:112-135` (retry_selected)
- Test: `django_celery_outbox/admin_tests.py`

- [ ] **Step 1: Write failing test**

Add to `admin_tests.py`:

```python
@pytest.mark.django_db
def test_dead_letter_retry_selected_preserves_schema_version() -> None:
    dead = CeleryOutboxDeadLetterFactory.create(
        task_id='task-with-version',
        task_name='app.tasks.versioned',
        schema_version=1,
    )

    admin_instance: CeleryOutboxDeadLetterAdmin = admin.site._registry[CeleryOutboxDeadLetter]  # type: ignore[assignment]
    queryset = CeleryOutboxDeadLetter.objects.filter(pk=dead.pk)
    m_request = MagicMock()

    admin_instance.retry_selected(m_request, queryset)

    outbox = CeleryOutbox.objects.get(task_id='task-with-version')
    assert outbox.schema_version == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm app pytest django_celery_outbox/admin_tests.py::test_dead_letter_retry_selected_preserves_schema_version -v
```

Expected: FAIL

- [ ] **Step 3: Update retry_selected action**

Add `schema_version` to CeleryOutbox creation in `retry_selected`:

```python
outbox_messages = [
    CeleryOutbox(
        task_id=dl.task_id,
        task_name=dl.task_name,
        args=dl.args,
        kwargs=dl.kwargs,
        options=dl.options,
        schema_version=dl.schema_version,
        sentry_trace_id=dl.sentry_trace_id,
        sentry_baggage=dl.sentry_baggage,
        structlog_context=dl.structlog_context,
    )
    for dl in queryset
]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
docker compose run --rm app pytest django_celery_outbox/admin_tests.py::test_dead_letter_retry_selected_preserves_schema_version -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/admin.py django_celery_outbox/admin_tests.py
git commit -m "feat(admin): preserve schema_version in retry_selected action"
```

---

### Task 12: Update factories

**Files:**
- Modify: `django_celery_outbox/factories.py`

- [ ] **Step 1: Add schema_version to CeleryOutboxFactory**

```python
class CeleryOutboxFactory(factory.django.DjangoModelFactory):
    task_id = factory.Sequence(lambda n: f'task-{n}')
    task_name = factory.Sequence(lambda n: f'app.tasks.task_{n}')
    schema_version = 1

    class Meta:
        model = CeleryOutbox
```

- [ ] **Step 2: Add schema_version to CeleryOutboxDeadLetterFactory**

```python
class CeleryOutboxDeadLetterFactory(factory.django.DjangoModelFactory):
    task_id = factory.Sequence(lambda n: f'dead-task-{n}')
    task_name = factory.Sequence(lambda n: f'app.tasks.dead_task_{n}')
    created_at = factory.LazyFunction(timezone.now)
    schema_version = 1

    class Meta:
        model = CeleryOutboxDeadLetter
```

- [ ] **Step 3: Run all tests to verify no regression**

```bash
docker compose run --rm app pytest -v
```

Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add django_celery_outbox/factories.py
git commit -m "feat(factories): add schema_version field"
```

---

### Task 13: Add README documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Schema Versioning section**

Add after the "Multi-database aware" bullet in Features section:

```markdown
- Schema versioning for safe format migrations
```

Add new section before "License":

```markdown
## Schema Versioning

The outbox uses a `schema_version` field to enable safe format migrations across library upgrades.

### Upgrade Policy

- **N-1 compatibility**: Each version supports deserializing the current and previous schema versions
- **Rolling deployments**: Old relay instances skip messages with newer schema versions (picked up by updated relays)
- **Deprecated versions**: Messages below minimum supported version are skipped

### Behavior

| Relay Version | Message Version | Action |
|--------------|-----------------|--------|
| 1 | 1 | Process normally |
| 2 | 1 | Process (N-1 support) |
| 2 | 2 | Process normally |
| 1 | 2 | Skip (future version) |

### Dead Letter Considerations

Dead-lettered messages retain their original `schema_version`. Before major upgrades that drop version support, review and process dead-lettered messages or they may become unprocessable.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add schema versioning documentation"
```

---

### Task 14: Run full test suite and verify

**Files:**
- All test files

- [ ] **Step 1: Run full test suite**

```bash
docker compose run --rm app pytest -v
```

Expected: All tests PASS

- [ ] **Step 2: Run type checking**

```bash
docker compose run --rm app mypy django_celery_outbox
```

Expected: No errors

- [ ] **Step 3: Run linting**

```bash
docker compose run --rm app ruff check django_celery_outbox
```

Expected: No errors

- [ ] **Step 4: Final commit if any fixes needed**

If any fixes were needed, commit them.
