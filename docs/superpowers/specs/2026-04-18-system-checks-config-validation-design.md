# System Checks For Config Validation - Design Spec

**Issue:** [#29](https://github.com/Barsoomx/django-celery-outbox/issues/29)
**Date:** 2026-04-18
**Status:** Approved

## Problem

`django-celery-outbox` currently catches some configuration problems too late:

- `CELERY_OUTBOX_APP` is only validated when `celery_outbox_relay` starts.
- `OutboxCelery.send_task()` reads `CELERY_OUTBOX_EXCLUDE_TASKS` without validating its type or members.
- Missing package migrations surface as a runtime database error on first write instead of an actionable setup error.
- Unsupported databases are only partially covered by checks.

This creates a poor production experience. Misconfiguration can sit unnoticed until the first relay start or the first task dispatch, turning an onboarding mistake into a runtime outage.

## Goals

- Surface package misconfiguration in `python manage.py check` with clear, actionable error messages.
- Reuse the same validation rules in runtime code so skipped checks do not become silent production failures.
- Keep database validation aligned with the actual database alias routed for `CeleryOutbox`.
- Preserve existing public settings names and existing valid configuration shapes.

## Non-Goals

- No new user-facing settings.
- No eager database work in `AppConfig.ready()`.
- No unrelated refactor of relay internals or task dispatch behavior.

## Options Considered

### 1. Minimal acceptance patch

Add the missing Django system checks and leave runtime config parsing mostly unchanged.

Pros:

- Smallest diff
- Lowest short-term implementation risk

Cons:

- Users who skip `manage.py check` still hit avoidable runtime failures
- `CELERY_OUTBOX_EXCLUDE_TASKS` remains a silent misconfiguration path in production code

### 2. Shared validation for checks and runtime

Add Django system checks and centralize config parsing in internal helpers that are reused by `checks.py`, `app.py`, and `celery_outbox_relay.py`.

Pros:

- One validation rule produces one behavior everywhere
- Closes the silent production failure gap
- Keeps error messages consistent across check-time and runtime

Cons:

- Slightly larger diff than a checks-only patch

### 3. Eager startup validation in `AppConfig.ready()`

Perform config and database validation directly during app startup.

Pros:

- Earliest possible failure

Cons:

- `ready()` is the wrong place for heavyweight validation and database probing
- Increases startup side effects and brittleness
- Harder to keep compatible with Django's application loading lifecycle

## Decision

Choose option 2.

The package will register Django system checks through `AppConfig.ready()`, but the validation logic itself will live in small internal helpers reused by runtime code. `manage.py check` becomes the primary early-failure path, while relay startup and task dispatch still fail clearly if checks were skipped.

## Design

### 1. Check registration

`django_celery_outbox.apps.DjangoCeleryOutboxConfig.ready()` already imports `django_celery_outbox.checks`. Keep that pattern and expand `checks.py` with focused check functions instead of one large monolithic check.

Each check returns structured Django `Error` objects with stable IDs in the `celery_outbox` namespace.

### 2. Internal validation helpers

Add a small internal module at `django_celery_outbox/_settings.py` with pure helpers:

- `load_celery_app_setting()`
- `get_exclude_tasks_setting()`
- `get_outbox_db_alias()`

Behavior:

- `load_celery_app_setting()` reads `CELERY_OUTBOX_APP`, validates that it is a dotted path, imports it, resolves the attribute, and verifies the resolved object is a `Celery` instance.
- `get_exclude_tasks_setting()` accepts `set`, `frozenset`, `list`, or `tuple` of strings and returns a normalized `set[str]`.
- `get_exclude_tasks_setting()` rejects `str`, `bytes`, non-iterables, and iterables containing non-string members.
- `get_outbox_db_alias()` resolves the database alias from `CeleryOutbox.objects.db`.

These helpers are internal implementation details, not part of the public API.

### 3. Runtime reuse

Reuse the helpers in runtime paths:

- `django_celery_outbox.management.commands.celery_outbox_relay.Command._get_celery_app()` delegates to `load_celery_app_setting()`.
- `django_celery_outbox.app.OutboxCelery.send_task()` replaces `set(getattr(settings, 'CELERY_OUTBOX_EXCLUDE_TASKS', ()))` with `get_exclude_tasks_setting()`.

Result:

- invalid `CELERY_OUTBOX_APP` still fails clearly when relay starts
- invalid `CELERY_OUTBOX_EXCLUDE_TASKS` fails clearly when `send_task()` is called
- system checks and runtime code stay in sync

### 4. System check set

#### `celery_outbox.E001` - database does not support `SKIP LOCKED`

Current behavior already checks `connection.features.has_select_for_update_skip_locked`. Keep that logic, but ensure it respects database selection rules:

- on plain `manage.py check`, inspect the routed outbox DB alias directly
- on `manage.py check --database <alias>`, only run if `<alias>` includes the outbox DB alias

Message:

- error: database does not support `SELECT FOR UPDATE SKIP LOCKED`
- hint: use PostgreSQL >= 9.5 or MySQL >= 8.0.1

#### `celery_outbox.E002` - missing `CELERY_OUTBOX_APP`

Raised when the setting is absent or empty.

Hint:

- set `CELERY_OUTBOX_APP` to the dotted path of the Celery app instance

#### `celery_outbox.E003` - invalid `CELERY_OUTBOX_APP`

Raised when the setting is present but invalid:

- not a dotted path
- module import fails
- attribute is missing
- resolved object is not a `Celery` instance

The error message should summarize the invalid value and the failure reason without dumping a long traceback.

#### `celery_outbox.E004` - invalid `CELERY_OUTBOX_EXCLUDE_TASKS`

Raised when the setting is malformed:

- scalar value like `123`
- string value like `'my.task'`
- bytes
- iterable containing non-string members

Valid values remain backward compatible:

- `set[str]`
- `frozenset[str]`
- `list[str]`
- `tuple[str, ...]`

#### `celery_outbox.E005` - package migrations not fully applied

Raised when the selected outbox database does not have all `django_celery_outbox` migrations applied.

Implementation:

- read on-disk migration names for app label `django_celery_outbox`
- read applied migrations from `MigrationRecorder(connection).applied_migrations()`
- compare the expected migration names with the applied migration names

Hint:

- run `python manage.py migrate`

This protects upgrades as well as first-time installs. Table existence alone is not sufficient because later package migrations can be missing while base tables still exist.

#### `celery_outbox.E006` - outbox schema cannot be verified

Raised when required table inspection or migration inspection cannot complete cleanly, or when required package tables are missing:

- `django_migrations` missing
- `celery_outbox` missing
- `celery_outbox_dead_letter` missing
- database inspection raises `DatabaseError`, including `OperationalError` or `ProgrammingError`

Hint:

- ensure the configured database is reachable and run `python manage.py migrate`

This prevents `manage.py check` from failing with raw database exceptions.

### 5. Database check execution semantics

This package intentionally differs slightly from Django's built-in database-tagged checks.

Observation:

- Django passes `databases=None` for plain `manage.py check`
- many built-in database checks no-op in that mode

Decision:

- django-celery-outbox database checks must still validate the routed outbox database during plain `manage.py check`

Reason:

- issue #29 explicitly requires users to catch these failures in plain `python manage.py check`
- asking users to remember `--database` would weaken the onboarding and production-safety goal

Selection rules:

- if `databases is None`, run the DB checks against the outbox DB alias
- if `databases` is provided and does not include the outbox DB alias, skip DB checks
- if `databases` includes the outbox DB alias, run DB checks against that alias only

### 6. Error handling rules

Checks should never leak raw backend exceptions unless Django itself is unable to initialize. Wrap database inspection and migration inspection in narrow exception handling and convert failures into structured `Error` results.

Runtime helper behavior:

- relay startup raises `ValueError` for invalid `CELERY_OUTBOX_APP`
- `send_task()` raises `TypeError` or `ValueError` for invalid `CELERY_OUTBOX_EXCLUDE_TASKS`

The runtime path does not need to convert every configuration error into Django check objects; it only needs to fail clearly and consistently.

## Testing

### Unit tests for helper behavior

Add coverage for:

- missing `CELERY_OUTBOX_APP`
- malformed dotted path
- nonexistent module
- missing attribute
- resolved object is not a `Celery` instance
- valid exclude-task collections: `set`, `frozenset`, `list`, `tuple`
- invalid exclude-task values: string, bytes, int, mixed-type iterables

### System check tests

Expand `django_celery_outbox/checks_tests.py` with:

- direct tests per check function and error ID
- command-level tests using Django's `call_command('check')`
- coverage for plain `check`
- coverage for `check --database default`
- coverage for the skip behavior when `--database` excludes the routed outbox alias

### Runtime regression tests

Expand:

- `django_celery_outbox/management/commands/celery_outbox_relay_tests.py`
- `django_celery_outbox/app_tests.py`

Add tests proving:

- relay command still loads a valid configured Celery app
- relay command raises clear validation errors for missing or invalid `CELERY_OUTBOX_APP`
- `OutboxCelery.send_task()` rejects malformed `CELERY_OUTBOX_EXCLUDE_TASKS` instead of silently interpreting bad values

### Database state tests

Mock or patch database introspection and migration recorder behavior so tests can cover:

- unsupported `SKIP LOCKED`
- missing migration records
- missing required tables
- inspection exceptions converted into `celery_outbox.E006`

Tests should avoid depending on a real broken schema when a mock gives a narrower and more deterministic failure mode.

## Documentation

Update:

- `docs/configuration.md`
- `docs/getting-started.md`

Changes:

- document that `CELERY_OUTBOX_EXCLUDE_TASKS` must be an iterable of task-name strings
- recommend `python manage.py check` after configuring the package
- keep database support messaging aligned with the existing SQLite-not-supported documentation

## Acceptance Criteria

- `AppConfig.ready()` registers package system checks
- `python manage.py check` reports actionable failures for invalid `CELERY_OUTBOX_APP`
- `python manage.py check` reports actionable failures for invalid `CELERY_OUTBOX_EXCLUDE_TASKS`
- `python manage.py check` reports actionable failures for missing or unapplied outbox migrations
- `python manage.py check` reports actionable failures for unsupported database backends
- runtime code reuses validation helpers so skipped checks do not become silent production failures
- tests cover direct check functions, command-level checks, and runtime regression paths
