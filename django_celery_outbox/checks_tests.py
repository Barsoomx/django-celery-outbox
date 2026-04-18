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
    connection.alias = 'default'
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


def test_check_outbox_migrations_applied_converts_database_error_to_schema_verification_error() -> None:
    m_connection = _mock_connection()
    m_connection.introspection.table_names.side_effect = RuntimeError('db unavailable')

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
            with patch('django_celery_outbox.checks.DatabaseError', RuntimeError):
                errors = check_outbox_migrations_applied(None)

    assert [error.id for error in errors] == ['celery_outbox.E006']


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.valid_celery_app')
def test_call_command_check_reports_invalid_exclude_tasks() -> None:
    m_connection = _mock_connection()
    m_recorder = MagicMock()
    m_recorder.applied_migrations.return_value = {
        ('django_celery_outbox', '0001_initial'): object(),
        ('django_celery_outbox', '0002_schema_version'): object(),
        ('django_celery_outbox', '0003_redacted_payload_fields'): object(),
    }
    m_loader = MagicMock()
    m_loader.disk_migrations = {
        ('django_celery_outbox', '0001_initial'): object(),
        ('django_celery_outbox', '0002_schema_version'): object(),
        ('django_celery_outbox', '0003_redacted_payload_fields'): object(),
    }

    with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS='task.a'):
        with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
            with patch('django_celery_outbox.checks.get_outbox_db_alias', return_value='default'):
                with patch('django_celery_outbox.checks.MigrationRecorder', return_value=m_recorder):
                    with patch('django_celery_outbox.checks.MigrationLoader', return_value=m_loader):
                        with pytest.raises(SystemCheckError, match='celery_outbox.E004'):
                            call_command('check')


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.valid_celery_app')
def test_call_command_check_reports_database_errors_on_plain_check() -> None:
    m_connection = _mock_connection(skip_locked=False)
    m_recorder = MagicMock()
    m_recorder.applied_migrations.return_value = {
        ('django_celery_outbox', '0001_initial'): object(),
        ('django_celery_outbox', '0002_schema_version'): object(),
        ('django_celery_outbox', '0003_redacted_payload_fields'): object(),
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
                    with pytest.raises(SystemCheckError, match='celery_outbox.E001'):
                        call_command('check')


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.checks_tests.valid_celery_app')
def test_call_command_check_reports_database_errors_with_database_argument() -> None:
    m_connection = _mock_connection(skip_locked=False)
    m_recorder = MagicMock()
    m_recorder.applied_migrations.return_value = {
        ('django_celery_outbox', '0001_initial'): object(),
        ('django_celery_outbox', '0002_schema_version'): object(),
        ('django_celery_outbox', '0003_redacted_payload_fields'): object(),
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
                    with pytest.raises(SystemCheckError, match='celery_outbox.E001'):
                        call_command('check', databases=['default'])
