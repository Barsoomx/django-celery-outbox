# Testing with pytest

`django-celery-outbox` ships a pytest plugin that exposes test helpers for the outbox and relay flow.

When the package is installed, pytest discovers the plugin through `pytest11`. The fixtures are available without adding `pytest_plugins` in your test suite.
The shipped fixtures delegate to an internal package-owned support module, but downstream test suites should still import and use the fixtures themselves rather than private helpers.

If your test environment disables plugin autoload, for example with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, pytest will not load the plugin automatically. In that case, explicitly register `django_celery_outbox.fixtures` in your test configuration.

## Installation

Install pytest support alongside the library:

```bash
pip install django-celery-outbox pytest pytest-django
```

Configure Django settings for pytest, for example:

```ini
[pytest]
DJANGO_SETTINGS_MODULE = myproject.settings
```

The fixtures assume `pytest-django` is installed and Django settings are configured before tests run.
If you use `drain_outbox()` or `fake_relay`, your test settings must also define `CELERY_OUTBOX_APP`, because both helpers resolve the configured Celery app used by the relay publish path.

## Quick Example

```python
def test_my_code(fake_relay, assert_task_sent, drain_outbox):
    enqueue_my_task()

    msg = assert_task_sent('my.task')
    drain_outbox()

    assert len(fake_relay.calls) == 1
    assert fake_relay.calls[0].task_id == msg.task_id
```

## Fixture Overview

### `outbox`

Returns the `CeleryOutbox` model class for direct assertions.
The fixture also enables transactional database access for the test.

Before each test it:

- clears pending outbox rows
- clears dead-letter rows
- clears cached redaction state
- clears structlog contextvars

After each test it performs the same cleanup again.

Typical usage:

```python
def test_enqueues_message(outbox):
    enqueue_my_task()
    assert outbox.objects.count() == 1
```

### `assert_task_sent`

Asserts that exactly one queued outbox row matches the given task name and optional payload filters.

Arguments:

- `name`: required task name
- `args`: optional expected positional args
- `kwargs`: optional expected keyword args

Tuple args are normalized to the list representation stored in the database.

If no row matches, or more than one row matches, the helper raises `AssertionError` with a summary of currently queued tasks.

Typical usage:

```python
def test_enqueues_expected_payload(assert_task_sent):
    enqueue_my_task()

    msg = assert_task_sent(
        'my.task',
        args=(1, 2),
        kwargs={'flag': True},
    )

    assert msg.task_id is not None
```

### `fake_relay`

Intercepts broker publishes and records them in memory instead of sending them to the real broker.

The fixture returns a `FakeRelayRecorder` with a `calls` list of `RecordedRelayCall` objects. Each recorded call includes:

- `name`
- `args`
- `kwargs`
- `task_id`
- `headers`
- `options`

This is useful when you want to verify what the relay would publish after draining the outbox.
`fake_relay` resolves `CELERY_OUTBOX_APP` to distinguish relay publishes from unrelated direct Celery sends, so tests using it must configure that setting.

### `drain_outbox()`

Synchronously runs the real relay path until the outbox is empty or no progress can be made.

This is intentionally strict:

- if the queue drains completely, it returns `None`
- if one relay pass reduces the queue but does not empty it, it keeps going
- if a relay pass makes no progress, it raises `AssertionError`

The no-progress error usually means one of these:

- rows are scheduled for a future `retry_after`
- rows are stuck in-flight
- rows use an unsupported schema version
- broker sends are failing and retries are being scheduled

Typical usage:

```python
def test_relay_flow(fake_relay, drain_outbox):
    enqueue_my_task()

    drain_outbox()

    assert len(fake_relay.calls) == 1
    assert fake_relay.calls[0].name == 'my.task'
```

## Backend Requirements

`drain_outbox()` uses the real relay implementation, so it requires the same supported database backends as the relay itself:

- PostgreSQL >= 9.5
- MySQL >= 8.0.1

SQLite is not supported for real relay execution.

## Recommended Test Pattern

For end-to-end application tests:

1. trigger code that queues an outbox message
2. use `assert_task_sent()` to verify the queued row
3. call `drain_outbox()`
4. assert on `fake_relay.calls`

That pattern verifies both stages:

- your application queued the right task
- the relay would publish the expected broker payload
