# System Checks For Config Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface django-celery-outbox misconfiguration in `python manage.py check` and reuse the same validation rules at runtime so skipped checks do not become silent production failures.

**Architecture:** Add a small internal settings-validation module, reuse it in `OutboxCelery.send_task()` and the relay command, and expand `checks.py` with focused config and database checks. Cover the change with direct unit tests plus command-level `call_command('check')` tests that verify plain and database-scoped behavior.

**Tech Stack:** Django system checks, Django migrations loader/recorder, Celery, pytest, docker compose

**Spec:** `docs/superpowers/specs/2026-04-18-system-checks-config-validation-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `django_celery_outbox/_settings.py` | Create | Shared validation helpers for `CELERY_OUTBOX_APP`, `CELERY_OUTBOX_EXCLUDE_TASKS`, and outbox DB alias resolution |
| `django_celery_outbox/settings_tests.py` | Create | Unit tests for settings helper success and failure paths |
| `django_celery_outbox/app.py` | Modify | Reuse exclude-task validation helper in `OutboxCelery.send_task()` |
| `django_celery_outbox/app_tests.py` | Modify | Runtime regression tests for malformed `CELERY_OUTBOX_EXCLUDE_TASKS` |
| `django_celery_outbox/management/commands/celery_outbox_relay.py` | Modify | Reuse shared Celery app loader |
| `django_celery_outbox/management/commands/celery_outbox_relay_tests.py` | Modify | Runtime regression tests for valid and invalid `CELERY_OUTBOX_APP` |
| `django_celery_outbox/checks.py` | Modify | Add config checks, migration/schema checks, DB alias selection, and error conversion |
| `django_celery_outbox/checks_tests.py` | Modify | Direct check tests and `call_command('check')` integration coverage |
| `README.md` | Modify | Add `python manage.py check` to the quick-start flow |
| `docs/configuration.md` | Modify | Document accepted `CELERY_OUTBOX_EXCLUDE_TASKS` container types and validation behavior |
| `docs/getting-started.md` | Modify | Add `python manage.py check` to the setup flow before the relay starts |
| `docs/usage/excluded-tasks.md` | Modify | Clarify accepted exclude-task setting types and invalid string/scalar cases |

---

### Task 1: Add Shared Settings Validation Helpers

**Files:**
- Create: `django_celery_outbox/_settings.py`
- Create: `django_celery_outbox/settings_tests.py`

- [ ] **Step 1: Write the failing helper tests**

Create `django_celery_outbox/settings_tests.py`:

```python
from celery import Celery
import pytest
from django.test import override_settings

from django_celery_outbox._settings import (
    get_exclude_tasks_setting,
    get_outbox_db_alias,
    load_celery_app_setting,
)

valid_celery_app = Celery('settings-tests')
not_a_celery_app = object()


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.settings_tests.valid_celery_app')
def test_load_celery_app_setting_returns_celery_instance() -> None:
    assert load_celery_app_setting() is valid_celery_app


def test_load_celery_app_setting_requires_value() -> None:
    with pytest.raises(ValueError, match='CELERY_OUTBOX_APP setting is required'):
        load_celery_app_setting()


@override_settings(CELERY_OUTBOX_APP='no_dot_in_path')
def test_load_celery_app_setting_requires_dotted_path() -> None:
    with pytest.raises(ValueError, match='must be a dotted path'):
        load_celery_app_setting()


@override_settings(CELERY_OUTBOX_APP='nonexistent.module.app')
def test_load_celery_app_setting_wraps_import_errors() -> None:
    with pytest.raises(ValueError, match='module could not be imported'):
        load_celery_app_setting()


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.settings_tests.not_a_celery_app')
def test_load_celery_app_setting_requires_celery_instance() -> None:
    with pytest.raises(ValueError, match='must point to a Celery instance'):
        load_celery_app_setting()


@override_settings(CELERY_OUTBOX_EXCLUDE_TASKS=('task.a', 'task.b'))
def test_get_exclude_tasks_setting_normalizes_iterables() -> None:
    assert get_exclude_tasks_setting() == {'task.a', 'task.b'}


@override_settings(CELERY_OUTBOX_EXCLUDE_TASKS='task.a')
def test_get_exclude_tasks_setting_rejects_strings() -> None:
    with pytest.raises(TypeError, match='set, frozenset, list, or tuple of strings'):
        get_exclude_tasks_setting()


@override_settings(CELERY_OUTBOX_EXCLUDE_TASKS=('task.a', 1))
def test_get_exclude_tasks_setting_rejects_non_string_members() -> None:
    with pytest.raises(TypeError, match='must contain only strings'):
        get_exclude_tasks_setting()


def test_get_outbox_db_alias_returns_model_database_alias() -> None:
    assert get_outbox_db_alias() == 'default'
```

- [ ] **Step 2: Run the helper tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/settings_tests.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'django_celery_outbox._settings'`

- [ ] **Step 3: Implement the shared helper module**

Create `django_celery_outbox/_settings.py`:

```python
import importlib

from celery import Celery
from django.conf import settings

from django_celery_outbox.models import CeleryOutbox


def load_celery_app_setting() -> Celery:
    app_path = getattr(settings, 'CELERY_OUTBOX_APP', None)
    if not app_path:
        raise ValueError(
            'CELERY_OUTBOX_APP setting is required. '
            'Set it to the dotted path of your Celery app instance, e.g. '
            '"myproject.celery_app.app".'
        )
    if not isinstance(app_path, str):
        raise ValueError(
            f'CELERY_OUTBOX_APP must be a dotted path string, got {type(app_path).__name__}.'
        )

    try:
        module_path, attr_name = app_path.rsplit('.', 1)
    except ValueError as exc:
        raise ValueError(
            f'CELERY_OUTBOX_APP must be a dotted path '
            f'(e.g. "myproject.celery_app.app"), got: "{app_path}"'
        ) from exc

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ValueError(
            f'CELERY_OUTBOX_APP module could not be imported: "{module_path}".'
        ) from exc

    try:
        app = getattr(module, attr_name)
    except AttributeError as exc:
        raise ValueError(
            f'CELERY_OUTBOX_APP attribute "{attr_name}" was not found in "{module_path}".'
        ) from exc

    if not isinstance(app, Celery):
        raise ValueError(
            f'CELERY_OUTBOX_APP must point to a Celery instance, got {type(app).__name__}.'
        )

    return app


def get_exclude_tasks_setting() -> set[str]:
    value = getattr(settings, 'CELERY_OUTBOX_EXCLUDE_TASKS', ())
    if isinstance(value, (str, bytes)) or not isinstance(value, (set, frozenset, list, tuple)):
        raise TypeError(
            'CELERY_OUTBOX_EXCLUDE_TASKS must be a set, frozenset, list, or tuple of strings.'
        )

    invalid_members = [item for item in value if not isinstance(item, str)]
    if invalid_members:
        raise TypeError(
            'CELERY_OUTBOX_EXCLUDE_TASKS must contain only strings.'
        )

    return set(value)


def get_outbox_db_alias() -> str:
    return CeleryOutbox.objects.db
```

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/settings_tests.py -v`
Expected: PASS

- [ ] **Step 5: Commit the helper module**

```bash
git add django_celery_outbox/_settings.py django_celery_outbox/settings_tests.py
git commit -m "feat: add shared settings validation helpers"
```

---

### Task 2: Reuse Shared Validation In Runtime Paths

**Files:**
- Modify: `django_celery_outbox/app.py`
- Modify: `django_celery_outbox/app_tests.py`
- Modify: `django_celery_outbox/management/commands/celery_outbox_relay.py`
- Modify: `django_celery_outbox/management/commands/celery_outbox_relay_tests.py`

- [ ] **Step 1: Write the failing runtime regression tests**

Update `django_celery_outbox/management/commands/celery_outbox_relay_tests.py`:

```python
from unittest.mock import MagicMock, patch

from celery import Celery
import pytest
from django.test import override_settings

from django_celery_outbox.management.commands.celery_outbox_relay import Command
from django_celery_outbox.relay import RelayConfig

valid_celery_app = Celery('relay-tests')
not_a_celery_app = object()


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.management.commands.celery_outbox_relay_tests.valid_celery_app')
def test_get_celery_app_loads_module_by_path() -> None:
    result = Command._get_celery_app()

    assert result is valid_celery_app


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.management.commands.celery_outbox_relay_tests.not_a_celery_app')
def test_get_celery_app_rejects_non_celery_instance() -> None:
    with pytest.raises(ValueError, match='must point to a Celery instance'):
        Command._get_celery_app()


@override_settings(CELERY_OUTBOX_APP='nonexistent.module.app')
def test_get_celery_app_nonexistent_module_raises_value_error() -> None:
    with pytest.raises(ValueError, match='module could not be imported'):
        Command._get_celery_app()
```

Add to `django_celery_outbox/app_tests.py`:

```python
@pytest.mark.django_db
def test_send_task_invalid_exclude_tasks_string_raises(f_app: OutboxCelery) -> None:
    with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS='my.excluded.task'):
        with pytest.raises(TypeError, match='CELERY_OUTBOX_EXCLUDE_TASKS'):
            f_app.send_task('my.excluded.task')

    assert CeleryOutbox.objects.count() == 0


@pytest.mark.django_db
def test_send_task_invalid_exclude_tasks_member_type_raises(f_app: OutboxCelery) -> None:
    with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS=('my.excluded.task', 1)):
        with pytest.raises(TypeError, match='must contain only strings'):
            f_app.send_task('my.excluded.task')

    assert CeleryOutbox.objects.count() == 0
```

- [ ] **Step 2: Run the runtime regression tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/app_tests.py::test_send_task_invalid_exclude_tasks_string_raises django_celery_outbox/app_tests.py::test_send_task_invalid_exclude_tasks_member_type_raises django_celery_outbox/management/commands/celery_outbox_relay_tests.py::test_get_celery_app_rejects_non_celery_instance django_celery_outbox/management/commands/celery_outbox_relay_tests.py::test_get_celery_app_nonexistent_module_raises_value_error -v`
Expected: FAIL because `send_task()` still coerces invalid values and `_get_celery_app()` still returns raw import exceptions or accepts non-Celery objects

- [ ] **Step 3: Refactor runtime code to use the helpers**

Update `django_celery_outbox/app.py` imports and `send_task()`:

```python
from django_celery_outbox._settings import get_exclude_tasks_setting
from django_celery_outbox.serialization import CURRENT_SCHEMA_VERSION, serialize_options
from django_celery_outbox.signals import outbox_message_created
from django_celery_outbox.structlog_utils import get_structlog_context_json
```

Replace the exclude-task read in `OutboxCelery.send_task()`:

```python
        exclude_tasks = get_exclude_tasks_setting()
        if name in exclude_tasks:
            return super().send_task(
                name,
                args=args,
                kwargs=kwargs,
                countdown=countdown,
                eta=eta,
                task_id=task_id,
                producer=producer,
                connection=connection,
                result_cls=result_cls,
                expires=expires,
                publisher=publisher,
                link=link,
                link_error=link_error,
                add_to_parent=add_to_parent,
                group_id=group_id,
                group_index=group_index,
                retries=retries,
                chord=chord,
                reply_to=reply_to,
                time_limit=time_limit,
                soft_time_limit=soft_time_limit,
                root_id=root_id,
                parent_id=parent_id,
                route_name=route_name,
                shadow=shadow,
                chain=chain,
                task_type=task_type,
                **options,
            )
```

Update `django_celery_outbox/management/commands/celery_outbox_relay.py`:

```python
from celery import Celery
from django.core.management.base import BaseCommand, CommandParser

from django_celery_outbox._settings import load_celery_app_setting
from django_celery_outbox.relay import Relay, RelayConfig
```

Replace `_get_celery_app()`:

```python
    @staticmethod
    def _get_celery_app() -> Celery:
        return load_celery_app_setting()
```

- [ ] **Step 4: Run the runtime regression tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/app_tests.py::test_send_task_invalid_exclude_tasks_string_raises django_celery_outbox/app_tests.py::test_send_task_invalid_exclude_tasks_member_type_raises django_celery_outbox/management/commands/celery_outbox_relay_tests.py -v`
Expected: PASS

- [ ] **Step 5: Commit the runtime integration changes**

```bash
git add django_celery_outbox/app.py django_celery_outbox/app_tests.py django_celery_outbox/management/commands/celery_outbox_relay.py django_celery_outbox/management/commands/celery_outbox_relay_tests.py
git commit -m "feat: reuse shared validation in runtime paths"
```

---

### Task 3: Expand Django System Checks And Check Command Coverage

**Files:**
- Modify: `django_celery_outbox/checks.py`
- Modify: `django_celery_outbox/checks_tests.py`

- [ ] **Step 1: Write the failing direct-check and `call_command('check')` tests**

Replace `django_celery_outbox/checks_tests.py` with:

```python
from unittest.mock import MagicMock, patch

from celery import Celery
import pytest
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.test import override_settings

from django_celery_outbox.checks import (
    check_celery_outbox_app_setting,
    check_celery_outbox_exclude_tasks_setting,
    check_database_supports_skip_locked,
    check_outbox_migrations_applied,
)

valid_celery_app = Celery('checks-tests')
not_a_celery_app = object()


def _mock_connection(skip_locked: bool = True, table_names: list[str] | None = None) -> MagicMock:
    connection = MagicMock()
    connection.features.has_select_for_update_skip_locked = skip_locked
    connection.introspection.table_names.return_value = table_names or [
        'django_migrations',
        'celery_outbox',
        'celery_outbox_dead_letter',
    ]
    return connection


def test_check_returns_error_when_skip_locked_not_supported() -> None:
    m_connection = _mock_connection(skip_locked=False)

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            errors = check_database_supports_skip_locked(None)

    assert len(errors) == 1
    assert errors[0].id == 'celery_outbox.E001'
    assert 'SELECT FOR UPDATE SKIP LOCKED' in errors[0].msg


def test_check_database_supports_skip_locked_skips_other_database_aliases() -> None:
    m_connection = _mock_connection(skip_locked=False)

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            errors = check_database_supports_skip_locked(None, databases=['replica'])

    assert errors == []


def test_check_celery_outbox_app_setting_returns_missing_setting_error() -> None:
    errors = check_celery_outbox_app_setting(None)

    assert [error.id for error in errors] == ['celery_outbox.E002']


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.not_a_celery_app')
def test_check_celery_outbox_app_setting_returns_invalid_setting_error() -> None:
    errors = check_celery_outbox_app_setting(None)

    assert [error.id for error in errors] == ['celery_outbox.E003']


@override_settings(CELERY_OUTBOX_EXCLUDE_TASKS='task.a')
def test_check_celery_outbox_exclude_tasks_setting_returns_error() -> None:
    errors = check_celery_outbox_exclude_tasks_setting(None)

    assert [error.id for error in errors] == ['celery_outbox.E004']


def test_check_outbox_migrations_applied_returns_missing_migration_error() -> None:
    m_connection = _mock_connection()
    m_recorder = MagicMock()
    m_recorder.applied_migrations.return_value = {
        ('django_celery_outbox', '0001_initial'): object(),
    }
    m_loader = MagicMock()
    m_loader.disk_migrations = {
        ('django_celery_outbox', '0001_initial'): object(),
        ('django_celery_outbox', '0002_schema_version'): object(),
        ('django_celery_outbox', '0003_redacted_payload_fields'): object(),
    }

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            with patch('django_celery_outbox.checks.MigrationRecorder', return_value=m_recorder):
                with patch('django_celery_outbox.checks.MigrationLoader', return_value=m_loader):
                    errors = check_outbox_migrations_applied(None)

    assert [error.id for error in errors] == ['celery_outbox.E005']


def test_check_outbox_migrations_applied_returns_schema_verification_error_when_tables_missing() -> None:
    m_connection = _mock_connection(table_names=['django_migrations'])

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            errors = check_outbox_migrations_applied(None)

    assert [error.id for error in errors] == ['celery_outbox.E006']


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.valid_celery_app')
def test_call_command_check_reports_invalid_exclude_tasks() -> None:
    with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS='task.a'):
        with pytest.raises(SystemCheckError, match='celery_outbox.E004'):
            call_command('check')


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.valid_celery_app')
def test_call_command_check_reports_database_errors_on_plain_check() -> None:
    m_connection = _mock_connection(skip_locked=False)

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            with pytest.raises(SystemCheckError, match='celery_outbox.E001'):
                call_command('check')


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.valid_celery_app')
def test_call_command_check_reports_database_errors_with_database_argument() -> None:
    m_connection = _mock_connection(skip_locked=False)

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            with pytest.raises(SystemCheckError, match='celery_outbox.E001'):
                call_command('check', databases=['default'])


```

- [ ] **Step 2: Run the system check tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/checks_tests.py -v`
Expected: FAIL because the new check functions do not exist and plain `check` coverage is not implemented yet

- [ ] **Step 3: Implement the expanded check set**

Update `django_celery_outbox/checks.py`:

```python
from django.core.checks import Error, Tags, register
from django.db import DatabaseError, connections
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

from django_celery_outbox._settings import (
    get_exclude_tasks_setting,
    get_outbox_db_alias,
    load_celery_app_setting,
)

_REQUIRED_OUTBOX_TABLES = frozenset({'celery_outbox', 'celery_outbox_dead_letter'})


def _selected_outbox_aliases(databases: object) -> list[str]:
    outbox_alias = get_outbox_db_alias()
    if databases is None:
        return [outbox_alias]
    if outbox_alias in databases:
        return [outbox_alias]
    return []


@register()
def check_celery_outbox_app_setting(
    app_configs: object,
    **kwargs: object,
) -> list[Error]:
    try:
        load_celery_app_setting()
    except ValueError as exc:
        error_id = 'celery_outbox.E002' if 'setting is required' in str(exc) else 'celery_outbox.E003'
        return [
            Error(
                str(exc),
                hint='Set CELERY_OUTBOX_APP to the dotted path of your Celery app instance.',
                id=error_id,
            )
        ]

    return []


@register()
def check_celery_outbox_exclude_tasks_setting(
    app_configs: object,
    **kwargs: object,
) -> list[Error]:
    try:
        get_exclude_tasks_setting()
    except TypeError as exc:
        return [
            Error(
                str(exc),
                hint='Use a set, frozenset, list, or tuple of task-name strings.',
                id='celery_outbox.E004',
            )
        ]

    return []


@register(Tags.database)
def check_database_supports_skip_locked(
    app_configs: object,
    **kwargs: object,
) -> list[Error]:
    errors: list[Error] = []
    for db_alias in _selected_outbox_aliases(kwargs.get('databases')):
        connection = connections[db_alias]
        if not connection.features.has_select_for_update_skip_locked:
            errors.append(
                Error(
                    'Database does not support SELECT FOR UPDATE SKIP LOCKED.',
                    hint='Use PostgreSQL >= 9.5 or MySQL >= 8.0.1 for django-celery-outbox.',
                    id='celery_outbox.E001',
                )
            )

    return errors


@register(Tags.database)
def check_outbox_migrations_applied(
    app_configs: object,
    **kwargs: object,
) -> list[Error]:
    errors: list[Error] = []

    for db_alias in _selected_outbox_aliases(kwargs.get('databases')):
        connection = connections[db_alias]

        try:
            table_names = set(connection.introspection.table_names())
            if 'django_migrations' not in table_names or not _REQUIRED_OUTBOX_TABLES.issubset(table_names):
                return [
                    Error(
                        f'Could not verify django-celery-outbox schema on database "{db_alias}".',
                        hint='Ensure the configured database is reachable and run `python manage.py migrate`.',
                        id='celery_outbox.E006',
                    )
                ]

            applied = {
                name
                for (app_label, name) in MigrationRecorder(connection).applied_migrations()
                if app_label == 'django_celery_outbox'
            }
            expected = {
                name
                for (app_label, name) in MigrationLoader(
                    connection,
                    ignore_no_migrations=True,
                ).disk_migrations
                if app_label == 'django_celery_outbox'
            }
        except DatabaseError as exc:
            return [
                Error(
                    f'Could not verify django-celery-outbox schema on database "{db_alias}": {exc}',
                    hint='Ensure the configured database is reachable and run `python manage.py migrate`.',
                    id='celery_outbox.E006',
                )
            ]

        missing = sorted(expected - applied)
        if missing:
            errors.append(
                Error(
                    'django-celery-outbox migrations are not fully applied.',
                    hint='Run `python manage.py migrate` to apply missing django-celery-outbox migrations.',
                    id='celery_outbox.E005',
                )
            )

    return errors
```

- [ ] **Step 4: Run the system check tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/checks_tests.py -v`
Expected: PASS

- [ ] **Step 5: Commit the check implementation**

```bash
git add django_celery_outbox/checks.py django_celery_outbox/checks_tests.py
git commit -m "feat: add config and schema validation checks"
```

---

### Task 4: Update Documentation And Verify The Full Change

**Files:**
- Modify: `README.md`
- Modify: `docs/configuration.md`
- Modify: `docs/getting-started.md`
- Modify: `docs/usage/excluded-tasks.md`

- [ ] **Step 1: Update the settings and excluded-task documentation**

Edit `docs/configuration.md` so the `CELERY_OUTBOX_EXCLUDE_TASKS` row becomes:

```markdown
| `CELERY_OUTBOX_EXCLUDE_TASKS` | `set[str] \| frozenset[str] \| list[str] \| tuple[str, ...]` | `set()` | Task names to bypass the outbox (sent directly to broker). Invalid values fail in `python manage.py check` and at runtime. |
```

Add this note below the example in `docs/usage/excluded-tasks.md`:

```markdown
`CELERY_OUTBOX_EXCLUDE_TASKS` must be a `set`, `frozenset`, `list`, or `tuple` of task-name strings. Bare strings such as `'myapp.tasks.send_push_notification'` are invalid and now fail in `python manage.py check` and at runtime.
```

- [ ] **Step 2: Update the getting started and README quick-start flow**

Edit `docs/getting-started.md` so the setup sequence becomes:

````markdown
### 6. Run migrations

```bash
python manage.py migrate
```

### 7. Run configuration checks

```bash
python manage.py check
```

### 8. Start the relay

```bash
python manage.py celery_outbox_relay
```
````

Edit `README.md` so the quick-start commands become:

```bash
python manage.py migrate
python manage.py check
python manage.py celery_outbox_relay
```

- [ ] **Step 3: Run focused verification commands**

Run: `docker compose run --rm app pytest django_celery_outbox/settings_tests.py django_celery_outbox/checks_tests.py django_celery_outbox/app_tests.py django_celery_outbox/management/commands/celery_outbox_relay_tests.py -v`
Expected: PASS

Run: `docker compose run --rm app ruff check django_celery_outbox`
Expected: PASS

Run: `git diff -- README.md docs/configuration.md docs/getting-started.md docs/usage/excluded-tasks.md`
Expected: Diff shows only the intended config-validation wording updates

Run: `docker compose run --rm -e DJANGO_SETTINGS_MODULE=tests.settings app python -m django check`
Expected: `System check identified no issues`

Run: `docker compose run --rm -e DJANGO_SETTINGS_MODULE=tests.settings app python -m django check --database default`
Expected: `System check identified no issues`

- [ ] **Step 4: Run the full test suite**

Run: `docker compose run --rm app pytest -v`
Expected: PASS

- [ ] **Step 5: Commit the documentation and verification pass**

```bash
git add README.md docs/configuration.md docs/getting-started.md docs/usage/excluded-tasks.md
git commit -m "docs: document config validation checks"
```
