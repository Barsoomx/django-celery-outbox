# Export Pytest Fixtures for Library Users

**Issue:** [#31](https://github.com/Barsoomx/django-celery-outbox/issues/31)
**Date:** 2026-04-18
**Status:** Approved in chat, pending written-spec review

## Context

`django-celery-outbox` already has strong internal test coverage, but downstream projects still have to re-create the same testing helpers:

- assert that `OutboxCelery.send_task()` wrote a row into `CeleryOutbox`
- synchronously flush queued rows through the relay path
- fake broker publication without standing up a real broker

The repository already contains the raw building blocks for this:

- `OutboxCelery.send_task()` writes outbox rows in production code
- `Relay._processing()` is already used in tests as a synchronous one-shot relay pass
- raw broker publication is already isolated behind `django_celery_outbox.relay._publisher.Celery.send_task` via `RelayPublisher`

What is missing is a supported, packaged pytest surface for library users.

## Goals

1. Export a packaged pytest plugin via `pytest11`.
2. Provide four user-facing fixtures/helpers required by the issue:
   - `outbox`
   - `assert_task_sent(...)`
   - `drain_outbox()`
   - `fake_relay`
3. Keep the public testing API small, typed, and independent from internal `factory_boy` factories.
4. Reuse the real outbox and relay code paths where practical, rather than inventing a test-only execution path.
5. Add concise user-facing documentation and self-tests.

## Non-Goals

This issue does not include:

- exporting `factory_boy` factories as public API
- introducing Celery eager-mode testing as a supported path
- redesigning relay internals or adding new relay extension points
- expanding `django_celery_outbox.__init__` with testing helpers
- shipping a separate `django-celery-outbox[pytest]` extra in this iteration
- supporting SQLite as a relay backend

## Decision Summary

The library will ship a pytest plugin module at:

`django_celery_outbox/fixtures.py`

and register it in:

`[project.entry-points."pytest11"]`

with an entry such as:

```toml
[project.entry-points."pytest11"]
django_celery_outbox = "django_celery_outbox.fixtures"
```

The plugin will be auto-loaded by pytest when the package is installed. The plugin surface must therefore stay very small and import cheaply.

The testing API will remain separate from the top-level package facade. `django_celery_outbox.__init__` will not re-export fixtures or testing-only types.

## Public API

### `outbox`

Purpose:
provide an empty, transactional outbox table for the current test and a typed handle to inspect it.

Behavior:

- depends on `pytest-django` transactional database support
- assumes Django settings are configured for pytest, typically via `DJANGO_SETTINGS_MODULE`
- ensures `CeleryOutbox` and `CeleryOutboxDeadLetter` are empty at fixture start
- yields the `CeleryOutbox` model class itself
- performs cleanup after the test to prevent cross-test leakage
- clears known in-process state that already exists in the current suite:
  - `_get_redactor()` cache
  - `structlog.contextvars`

Why return the model class:

- it keeps the API small
- it avoids exposing internal factories
- it gives downstream users a stable typed object without inventing a custom wrapper
- users can immediately write `outbox.objects.count()`, `outbox.objects.get()`, and `outbox.objects.filter(...)`

### `assert_task_sent(name, *, args=..., kwargs=...)`

Purpose:
assert that a task was enqueued into `CeleryOutbox`.

Semantics:

- this helper checks the outbox row, not broker publication
- `args=...` means "do not filter by args"
- `kwargs=...` means "do not filter by kwargs"
- returns the matched `CeleryOutbox` row on success
- raises `AssertionError` on:
  - no matching row
  - ambiguous matches

Failure messages must be actionable and include a concise summary of available queued messages.

### `fake_relay`

Purpose:
record relay publications without sending anything to a real broker.

Semantics:

- patches raw broker publication at `django_celery_outbox.relay._publisher.Celery.send_task`
- does not patch `OutboxCelery.send_task()`
- records every publication attempt in a typed recorder object
- does not interfere with normal relay bookkeeping, so successfully relayed rows are still deleted from the outbox

The returned recorder will expose:

- `.calls`: ordered list of recorded publish calls

Each recorded call stores the effective broker-facing data after relay restoration:

- `name`
- `args`
- `kwargs`
- `task_id`
- `headers`
- any additional send-task options used by relay

### `drain_outbox()`

Purpose:
synchronously flush the outbox through the real relay path.

Semantics:

- creates a real `Relay` using the configured Celery app from `CELERY_OUTBOX_APP`
- uses in-process relay execution rather than a CLI subprocess
- repeatedly runs a single relay processing pass until:
  - the outbox is empty, or
  - no forward progress is possible

Success condition:

- `CeleryOutbox.objects.count() == 0`

Failure condition:

- queued rows remain, but relay passes stop making progress

In that case `drain_outbox()` raises `AssertionError` with a summary explaining that the queue was not fully drained.

## Internal Design

### Module shape

`django_celery_outbox/fixtures.py` should contain:

- pytest fixture functions
- small typed helper classes and callable protocols
- only cheap imports at module import time

It must avoid importing Django models, relay classes, or settings-sensitive code eagerly at module import time. Those imports should happen lazily inside fixtures/helpers so the plugin does not break pytest startup before Django is initialized.

### Database contract

All public fixtures in this plugin will depend on transactional database access.

Reasoning:

- downstream tests will often enqueue tasks inside `transaction.atomic()`
- relay processing uses `select_for_update(skip_locked=True)`
- the supported test story must match the real outbox/relay transaction model, not a lighter fake

This design intentionally assumes `pytest-django` is installed when users consume these fixtures.

The spec also assumes that documentation will be explicit about setup:

- install `pytest` and `pytest-django`
- configure Django settings for pytest
- understand that `drain_outbox()` requires the same supported database backends as relay itself

### Relay execution path

`drain_outbox()` will not shell out to `manage.py celery_outbox_relay`.

Instead it will:

1. load the configured Celery app via the existing settings loader
2. create a `Relay` instance in-process
3. run repeated `_processing()` passes

This keeps the helper:

- fast
- deterministic
- aligned with the existing test suite
- free from subprocess complexity

### Progress detection

A single `_processing()` call is not equivalent to "drain everything":

- relay batch size may be smaller than queue depth
- selector intentionally skips messages with future `retry_after`
- selector intentionally skips unsupported schema versions
- selector intentionally skips recently in-flight rows

Therefore `drain_outbox()` needs an explicit progress algorithm.

Accepted algorithm:

1. inspect total outbox row count before a pass
2. run one relay processing pass
3. inspect total outbox row count after the pass
4. stop successfully if the queue is empty
5. continue only if total row count decreased
6. fail if rows remain and total row count did not decrease

This is intentionally strict. Changes such as updating `retry_after`, stamping `updated_at`, or moving a row into a retryable future state do not count as drain progress. The helper contract is "fully flush the queue now", not "mutate queue state and maybe flush later".

The helper must fail loudly rather than silently succeeding on a partially drained queue.

## Typing Strategy

The plugin must be PEP 561-compatible using the package's existing `py.typed` marker.

`fixtures.py` will export typed helper names for downstream annotations, for example:

- `AssertTaskSent`
- `DrainOutbox`
- `FakeRelayRecorder`
- `RecordedRelayCall`

These types exist to improve downstream test ergonomics without requiring users to read plugin internals.

`outbox` itself does not need a custom wrapper type because it returns the existing `CeleryOutbox` model class.

## Error Handling

### Plugin import safety

Because the plugin is auto-loaded through `pytest11`, import-time behavior must stay safe:

- no database access at import time
- no settings loading at import time
- no model imports that require Django app setup

### Missing or misconfigured app setting

If `drain_outbox()` cannot load `CELERY_OUTBOX_APP`, it should surface the existing actionable configuration error from the settings loader rather than wrap it in a generic fixture failure.

### Unsupported database backend

If users attempt to run `drain_outbox()` on an unsupported backend, the helper should surface the existing relay initialization error rather than introducing a second compatibility mechanism.

### No-progress drain failures

When `drain_outbox()` fails because the queue cannot be fully drained, the error message should explicitly mention likely causes:

- future `retry_after`
- stale/in-flight rows
- unsupported schema version
- broker publication failures that moved rows into retry flow

The goal is fast diagnosis, not generic "assert 1 == 0" output.

## Documentation

### README

Add a short "Testing with pytest" section to `README.md` with one canonical example:

That section must also state the prerequisites directly before or after the example:

- install `pytest` and `pytest-django`
- configure `DJANGO_SETTINGS_MODULE` for the test suite
- use a relay-supported database backend for `drain_outbox()` (`PostgreSQL >= 9.5` or `MySQL >= 8.0.1`)

```python
def test_my_code(fake_relay, assert_task_sent, drain_outbox):
    ...
    msg = assert_task_sent("my.task")
    drain_outbox()
    assert len(fake_relay.calls) == 1
    assert fake_relay.calls[0].task_id == msg.task_id
```

This section should stay concise and point users to the core fixtures without turning the README into a testing manual.

### Full docs

For this issue, a separate MkDocs page is not required. README coverage is sufficient.

## Self-Tests

The implementation must include package self-tests covering:

1. pytest plugin registration
2. subprocess smoke test proving pytest can discover/import the `pytest11` plugin without touching Django models or settings at module import time
3. `outbox` cleanup semantics
4. `assert_task_sent` success and failure cases
5. `fake_relay` recording behavior
6. `drain_outbox()` on:
   - single message
   - multiple messages
   - multiple batches
   - no-progress failure
7. typed helper imports from `django_celery_outbox.fixtures`

## Acceptance Criteria

- pytest plugin entry point is registered in `pyproject.toml`
- library users get `outbox`, `assert_task_sent`, `drain_outbox()`, and `fake_relay`
- fixtures are typed and covered by the package's existing PEP 561 distribution
- helper API does not expose `factory_boy`
- README documents the testing workflow
- self-tests cover the public fixture behavior and drain failure edge cases

## Rationale for Rejected Alternatives

### Export internal factories

Rejected because it would:

- make `factory_boy` part of the supported public surface
- expose a helper that currently hard-codes `schema_version = 1`
- encourage downstream tests to couple themselves to internal model setup details

### Add testing helpers to `django_celery_outbox.__init__`

Rejected because the top-level package facade is intentionally curated and small. Testing helpers are useful, but they should not widen the root import contract.

### Introduce a separate testing package or extra

Rejected for now because the issue asks for packaged fixtures in the library itself, and the smaller solution is sufficient.

## Implementation Notes

Implementation should stay pragmatic:

- reuse current production paths where feasible
- keep plugin imports lazy
- keep error messages explicit
- do not add optional knobs to `drain_outbox()` in this first iteration

The first version should optimize for correctness and clarity, not maximal configurability.
