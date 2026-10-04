import sys
from collections.abc import Iterator
from typing import NoReturn
from unittest.mock import MagicMock, patch

import pytest
from celery import Celery
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.db import DatabaseError
from django.test import override_settings

from django_celery_outbox.checks import (
    _is_migrate_command,
    check_celery_outbox_app_setting,
    check_celery_outbox_dlq_retention_setting,
    check_celery_outbox_exclude_tasks_setting,
    check_celery_outbox_redactor_setting,
    check_database_supports_skip_locked,
    check_outbox_migrations_applied,
)

valid_celery_app = Celery('checks-tests')
not_a_celery_app = object()


def bad_redactor_signature(task_name: str, args: list) -> tuple[list, dict]:
    return args, {}


def _mock_connection(
    skip_locked: bool = True,
    table_names: list[str] | None = None,
    alias: str = 'default',
) -> MagicMock:
    connection = MagicMock()
    connection.alias = alias
    connection.features.has_select_for_update_skip_locked = skip_locked
    connection.introspection.table_names.return_value = (
        table_names
        if table_names is not None
        else [
            'django_migrations',
            'celery_outbox',
            'celery_outbox_dead_letter',
        ]
    )
    return connection


def _mock_applied_outbox_migrations() -> dict[tuple[str, str], object]:
    return {
        ('django_celery_outbox', '0001_initial'): object(),
        ('django_celery_outbox', '0002_schema_version'): object(),
        ('django_celery_outbox', '0003_redacted_payload_fields'): object(),
    }


class _ForbiddenConnections:
    def __getitem__(self, alias: str) -> NoReturn:
        raise AssertionError(f'database connection {alias!r} must not be accessed')


@pytest.fixture
def f_forbidden_connections() -> Iterator[_ForbiddenConnections]:
    forbidden_connections = _ForbiddenConnections()
    with patch('django_celery_outbox.checks.connections', forbidden_connections):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            yield forbidden_connections


@pytest.fixture
def m_unmigrated_connection() -> Iterator[MagicMock]:
    connection = _mock_connection(table_names=['django_migrations'])
    with patch('django_celery_outbox.checks.connections', {'default': connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            yield connection


@pytest.mark.parametrize(
    'check_kwargs',
    [{}, {'databases': None}, {'databases': []}],
    ids=['no_databases_kwarg', 'databases_none', 'databases_empty'],
)
def test_database_checks_skip_database_access_without_selected_databases(
    check_kwargs: dict[str, object],
    f_forbidden_connections: _ForbiddenConnections,
) -> None:
    skip_locked_errors = check_database_supports_skip_locked(None, **check_kwargs)
    migrations_errors = check_outbox_migrations_applied(None, **check_kwargs)

    assert skip_locked_errors == []
    assert migrations_errors == []


def test_check_outbox_migrations_applied_reports_unmigrated_schema_for_selected_database(
    m_unmigrated_connection: MagicMock,
) -> None:
    errors = check_outbox_migrations_applied(None, databases=['default'])

    assert [error.id for error in errors] == ['celery_outbox.E006']
    m_unmigrated_connection.introspection.table_names.assert_called_once_with()


def test_call_command_check_without_database_argument_does_not_access_database() -> None:
    call_command('check')


@pytest.mark.django_db
def test_call_command_makemigrations_check_ignores_unmigrated_outbox_schema(
    m_unmigrated_connection: MagicMock,
) -> None:
    call_command('makemigrations', '--check', '--dry-run', skip_checks=False)

    m_unmigrated_connection.introspection.table_names.assert_not_called()


def test_call_command_check_with_database_argument_reports_unmigrated_outbox_schema(
    m_unmigrated_connection: MagicMock,
) -> None:
    with pytest.raises(SystemCheckError, match='celery_outbox.E006'):
        call_command('check', databases=['default'])


def test_check_returns_error_when_skip_locked_not_supported() -> None:
    m_connection = _mock_connection(skip_locked=False)

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            errors = check_database_supports_skip_locked(None, databases=['default'])

    assert len(errors) == 1
    assert errors[0].id == 'celery_outbox.E001'
    assert 'SELECT FOR UPDATE SKIP LOCKED' in errors[0].msg


def test_check_database_supports_skip_locked_skips_other_database_aliases() -> None:
    m_connection = _mock_connection(skip_locked=False)

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            errors = check_database_supports_skip_locked(None, databases=['replica'])

    assert errors == []


@override_settings(CELERY_OUTBOX_APP=None)
def test_check_celery_outbox_app_setting_returns_missing_setting_error() -> None:
    errors = check_celery_outbox_app_setting(None)

    assert [error.id for error in errors] == ['celery_outbox.E002']


@override_settings(CELERY_OUTBOX_APP='')
def test_check_celery_outbox_app_setting_treats_empty_string_as_missing_setting() -> None:
    errors = check_celery_outbox_app_setting(None)

    assert [error.id for error in errors] == ['celery_outbox.E002']


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.not_a_celery_app')
def test_check_celery_outbox_app_setting_returns_invalid_setting_error() -> None:
    errors = check_celery_outbox_app_setting(None)

    assert [error.id for error in errors] == ['celery_outbox.E003']


@override_settings(CELERY_OUTBOX_APP='project.celery_app')
def test_check_celery_outbox_app_setting_converts_import_error_to_invalid_setting_error() -> None:
    with patch('django_celery_outbox.checks.load_celery_app_setting', side_effect=ImportError('boom')):
        errors = check_celery_outbox_app_setting(None)

    assert [error.id for error in errors] == ['celery_outbox.E003']
    assert errors[0].msg == "Could not import CELERY_OUTBOX_APP 'project.celery_app': boom"


@override_settings(CELERY_OUTBOX_APP='project.celery_app')
def test_check_celery_outbox_app_setting_converts_unexpected_error_to_invalid_setting_error() -> None:
    with patch('django_celery_outbox.checks.load_celery_app_setting', side_effect=RuntimeError('boom')):
        errors = check_celery_outbox_app_setting(None)

    assert [error.id for error in errors] == ['celery_outbox.E003']


@override_settings(CELERY_OUTBOX_EXCLUDE_TASKS='task.a')
def test_check_celery_outbox_exclude_tasks_setting_returns_error() -> None:
    errors = check_celery_outbox_exclude_tasks_setting(None)

    assert [error.id for error in errors] == ['celery_outbox.E004']


@override_settings(CELERY_OUTBOX_PII_REDACTOR='missing.module.redactor')
def test_check_celery_outbox_redactor_setting_returns_error_for_invalid_path() -> None:
    errors = check_celery_outbox_redactor_setting(None)

    assert [error.id for error in errors] == ['celery_outbox.E007']


@override_settings(CELERY_OUTBOX_PII_REDACTOR='django_celery_outbox.checks_tests.bad_redactor_signature')
def test_check_celery_outbox_redactor_setting_returns_error_for_bad_signature() -> None:
    errors = check_celery_outbox_redactor_setting(None)

    assert [error.id for error in errors] == ['celery_outbox.E007']


@override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '30x'})
def test_check_celery_outbox_dlq_retention_setting_returns_error_for_bad_duration() -> None:
    errors = check_celery_outbox_dlq_retention_setting(None)

    assert [error.id for error in errors] == ['celery_outbox.E008']


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
                    errors = check_outbox_migrations_applied(None, databases=['default'])

    assert [error.id for error in errors] == ['celery_outbox.E005']


def test_check_outbox_migrations_applied_returns_schema_verification_error_when_tables_missing() -> None:
    m_connection = _mock_connection(table_names=['django_migrations'])

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            errors = check_outbox_migrations_applied(None, databases=['default'])

    assert [error.id for error in errors] == ['celery_outbox.E006']


def test_check_outbox_migrations_applied_skips_schema_verification_during_migrate() -> None:
    m_connection = _mock_connection(table_names=['django_migrations'])

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            with patch.object(sys, 'argv', ['python', '-m', 'django', 'migrate']):
                errors = check_outbox_migrations_applied(None, databases=['default'])

    assert errors == []


def test_is_migrate_command_detects_programmatic_migrate_from_stack() -> None:
    migrate_frame = MagicMock()
    migrate_frame.f_code.co_filename = '/venv/lib/python3.12/site-packages/django/core/management/commands/migrate.py'
    migrate_frame.f_back = None
    current_frame = MagicMock()
    current_frame.f_code.co_filename = '/app/django_celery_outbox/checks.py'
    current_frame.f_back = migrate_frame

    with patch.object(sys, 'argv', ['pytest']):
        with patch('django_celery_outbox.checks.sys._getframe', return_value=current_frame):
            assert _is_migrate_command() is True


def test_check_outbox_migrations_applied_converts_database_error_to_schema_verification_error() -> None:
    m_connection = _mock_connection()
    m_connection.introspection.table_names.side_effect = DatabaseError('db unavailable')

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            errors = check_outbox_migrations_applied(None, databases=['default'])

    assert [error.id for error in errors] == ['celery_outbox.E006']


def test_check_outbox_migrations_applied_converts_loader_error_to_schema_verification_error() -> None:
    m_connection = _mock_connection()
    m_recorder = MagicMock()
    m_recorder.applied_migrations.return_value = _mock_applied_outbox_migrations()

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            with patch('django_celery_outbox.checks.MigrationRecorder', return_value=m_recorder):
                with patch('django_celery_outbox.checks.MigrationLoader', side_effect=RuntimeError('boom')):
                    errors = check_outbox_migrations_applied(None, databases=['default'])

    assert [error.id for error in errors] == ['celery_outbox.E006']


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.valid_celery_app')
def test_call_command_check_reports_invalid_exclude_tasks() -> None:
    m_connection = _mock_connection(alias='outbox')
    m_recorder = MagicMock()
    m_recorder.applied_migrations.return_value = _mock_applied_outbox_migrations()
    m_loader = MagicMock()
    m_loader.disk_migrations = _mock_applied_outbox_migrations()

    with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS='task.a'):
        with patch('django_celery_outbox.checks.connections', {'outbox': m_connection}):
            with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='outbox'):
                with patch('django_celery_outbox.checks.MigrationRecorder', return_value=m_recorder):
                    with patch('django_celery_outbox.checks.MigrationLoader', return_value=m_loader):
                        with pytest.raises(SystemCheckError, match='celery_outbox.E004'):
                            call_command('check')


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.valid_celery_app')
def test_call_command_check_reports_invalid_redactor_setting() -> None:
    m_connection = _mock_connection(alias='outbox')
    m_recorder = MagicMock()
    m_recorder.applied_migrations.return_value = _mock_applied_outbox_migrations()
    m_loader = MagicMock()
    m_loader.disk_migrations = _mock_applied_outbox_migrations()

    with override_settings(CELERY_OUTBOX_PII_REDACTOR='missing.module.redactor'):
        with patch('django_celery_outbox.checks.connections', {'outbox': m_connection}):
            with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='outbox'):
                with patch('django_celery_outbox.checks.MigrationRecorder', return_value=m_recorder):
                    with patch('django_celery_outbox.checks.MigrationLoader', return_value=m_loader):
                        with pytest.raises(SystemCheckError, match='celery_outbox.E007'):
                            call_command('check')


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.valid_celery_app')
def test_call_command_check_reports_invalid_dlq_retention_setting() -> None:
    m_connection = _mock_connection(alias='outbox')
    m_recorder = MagicMock()
    m_recorder.applied_migrations.return_value = _mock_applied_outbox_migrations()
    m_loader = MagicMock()
    m_loader.disk_migrations = _mock_applied_outbox_migrations()

    with override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '30x'}):
        with patch('django_celery_outbox.checks.connections', {'outbox': m_connection}):
            with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='outbox'):
                with patch('django_celery_outbox.checks.MigrationRecorder', return_value=m_recorder):
                    with patch('django_celery_outbox.checks.MigrationLoader', return_value=m_loader):
                        with pytest.raises(SystemCheckError, match='celery_outbox.E008'):
                            call_command('check')


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.valid_celery_app')
def test_call_command_check_skips_outbox_database_checks_on_plain_check() -> None:
    m_connection = _mock_connection(skip_locked=False, table_names=['django_migrations'], alias='outbox')
    m_recorder = MagicMock()
    m_loader = MagicMock()

    with patch('django_celery_outbox.checks.connections', {'outbox': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='outbox'):
            with patch('django_celery_outbox.checks.MigrationRecorder', return_value=m_recorder):
                with patch('django_celery_outbox.checks.MigrationLoader', return_value=m_loader):
                    call_command('check')

    m_connection.introspection.table_names.assert_not_called()
    m_recorder.applied_migrations.assert_not_called()
    assert m_loader.mock_calls == []


def test_call_command_check_reports_database_errors_with_database_argument() -> None:
    m_connection = _mock_connection(skip_locked=False, alias='default')
    m_recorder = MagicMock()
    m_recorder.applied_migrations.return_value = _mock_applied_outbox_migrations()
    m_loader = MagicMock()
    m_loader.disk_migrations = _mock_applied_outbox_migrations()

    with override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.valid_celery_app'):
        with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
            with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
                with patch('django_celery_outbox.checks.MigrationRecorder', return_value=m_recorder):
                    with patch('django_celery_outbox.checks.MigrationLoader', return_value=m_loader):
                        with pytest.raises(SystemCheckError, match='celery_outbox.E001'):
                            call_command('check', databases=['default'])


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.valid_celery_app')
def test_call_command_check_skips_outbox_database_checks_when_database_argument_excludes_alias() -> None:
    m_connection = _mock_connection(skip_locked=False, alias='outbox')
    m_recorder = MagicMock()
    m_loader = MagicMock()

    with patch('django_celery_outbox.checks.connections', {'outbox': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='outbox'):
            with patch('django_celery_outbox.checks.MigrationRecorder', return_value=m_recorder):
                with patch('django_celery_outbox.checks.MigrationLoader', return_value=m_loader):
                    call_command('check', databases=['default'])

    m_connection.introspection.table_names.assert_not_called()
    m_recorder.applied_migrations.assert_not_called()
    assert m_loader.mock_calls == []
