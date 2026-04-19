from datetime import timedelta

import pytest
from celery import Celery
from django.test import override_settings

from django_celery_outbox._settings import (
    get_exclude_tasks_setting,
    get_outbox_db_alias,
    load_celery_app_setting,
    load_dlq_retention_setting,
    load_pii_redactor_setting,
    load_stale_timeout_seconds_setting,
)

valid_celery_app = Celery('settings-tests')
not_a_celery_app = object()


def valid_redactor(task_name: str, args: list, kwargs: dict) -> tuple[list, dict]:
    return args, kwargs


def bad_redactor_signature(task_name: str, args: list) -> tuple[list, dict]:
    return args, {}


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.settings_tests.valid_celery_app')
def test_load_celery_app_setting_returns_celery_instance() -> None:
    assert load_celery_app_setting() is valid_celery_app


@override_settings(CELERY_OUTBOX_APP=None)
def test_load_celery_app_setting_requires_value() -> None:
    with pytest.raises(ValueError, match='CELERY_OUTBOX_APP setting is required'):
        load_celery_app_setting()


@override_settings(CELERY_OUTBOX_APP='')
def test_load_celery_app_setting_treats_empty_string_as_missing() -> None:
    with pytest.raises(ValueError, match='CELERY_OUTBOX_APP setting is required'):
        load_celery_app_setting()


@pytest.mark.parametrize('app_path, expected_type', [(0, 'int'), ([], 'list'), (False, 'bool')])
def test_load_celery_app_setting_rejects_falsey_non_strings(app_path: object, expected_type: str) -> None:
    with override_settings(CELERY_OUTBOX_APP=app_path):
        with pytest.raises(ValueError, match=f'must be a dotted path string, got {expected_type}'):
            load_celery_app_setting()


@override_settings(CELERY_OUTBOX_APP='no_dot_in_path')
def test_load_celery_app_setting_requires_dotted_path() -> None:
    with pytest.raises(ValueError, match='must be a dotted path'):
        load_celery_app_setting()


@pytest.mark.parametrize('app_path', ['.app', 'module.'])
def test_load_celery_app_setting_rejects_malformed_dotted_paths(app_path: str) -> None:
    with override_settings(CELERY_OUTBOX_APP=app_path):
        with pytest.raises(ValueError, match='must be a dotted path'):
            load_celery_app_setting()


@override_settings(CELERY_OUTBOX_APP='nonexistent.module.app')
def test_load_celery_app_setting_wraps_import_errors() -> None:
    with pytest.raises(ValueError, match='module could not be imported'):
        load_celery_app_setting()


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.settings_tests.missing_celery_app')
def test_load_celery_app_setting_requires_attribute() -> None:
    with pytest.raises(ValueError, match='was not found'):
        load_celery_app_setting()


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.settings_tests.not_a_celery_app')
def test_load_celery_app_setting_requires_celery_instance() -> None:
    with pytest.raises(ValueError, match='must point to a Celery instance'):
        load_celery_app_setting()


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.settings_tests.valid_celery_app')
def test_load_celery_app_setting_propagates_internal_import_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_import_error(_: object) -> object:
        raise ImportError('boom')

    monkeypatch.setattr('django_celery_outbox._settings.importlib.util.find_spec', lambda _: object())
    monkeypatch.setattr('django_celery_outbox._settings.importlib.import_module', raise_import_error)

    with pytest.raises(
        ValueError,
        match=(
            r'CELERY_OUTBOX_APP "django_celery_outbox\.settings_tests\.valid_celery_app" '
            r'could not be loaded because importing module '
            r'"django_celery_outbox\.settings_tests" failed: boom'
        ),
    ):
        load_celery_app_setting()


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.settings_tests.valid_celery_app')
def test_load_celery_app_setting_wraps_internal_find_spec_import_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    error = ModuleNotFoundError("No module named 'missing_dependency'")
    error.name = 'missing_dependency'

    def raise_module_not_found(_: object) -> object:
        raise error

    monkeypatch.setattr('django_celery_outbox._settings.importlib.util.find_spec', raise_module_not_found)

    with pytest.raises(
        ValueError,
        match=(
            r'CELERY_OUTBOX_APP "django_celery_outbox\.settings_tests\.valid_celery_app" '
            r'could not be loaded because resolving module '
            r'"django_celery_outbox\.settings_tests" failed: '
            r"No module named 'missing_dependency'"
        ),
    ):
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


@override_settings(CELERY_OUTBOX_PII_REDACTOR='django_celery_outbox.settings_tests.valid_redactor')
def test_load_pii_redactor_setting_loads_dotted_path() -> None:
    assert load_pii_redactor_setting() is valid_redactor


@override_settings(CELERY_OUTBOX_PII_REDACTOR=valid_redactor)
def test_load_pii_redactor_setting_accepts_callable() -> None:
    assert load_pii_redactor_setting() is valid_redactor


@override_settings(CELERY_OUTBOX_PII_REDACTOR='missing.module.redactor')
def test_load_pii_redactor_setting_raises_for_invalid_path() -> None:
    with pytest.raises(ImportError):
        load_pii_redactor_setting()


@override_settings(CELERY_OUTBOX_PII_REDACTOR='django_celery_outbox.settings_tests.bad_redactor_signature')
def test_load_pii_redactor_setting_raises_for_bad_signature() -> None:
    with pytest.raises(TypeError, match='must accept \\(task_name, args, kwargs\\)'):
        load_pii_redactor_setting()


@override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '7d', 'task_name': 'myapp.*'})
def test_load_dlq_retention_setting_parses_supported_values() -> None:
    assert load_dlq_retention_setting() == {
        'older_than_dead': timedelta(days=7),
        'older_than_created': None,
        'task_name_pattern': 'myapp.*',
    }


@override_settings(CELERY_OUTBOX_DLQ_RETENTION={})
def test_load_dlq_retention_setting_requires_a_threshold() -> None:
    with pytest.raises(ValueError, match='must specify older_than_dead or older_than_created'):
        load_dlq_retention_setting()


@override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '30x'})
def test_load_dlq_retention_setting_rejects_invalid_duration() -> None:
    with pytest.raises(ValueError, match="Invalid duration format: '30x'"):
        load_dlq_retention_setting()


@override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '7d', 'task_name': 123})
def test_load_dlq_retention_setting_rejects_non_string_task_name() -> None:
    with pytest.raises(TypeError, match='task_name must be a string'):
        load_dlq_retention_setting()


@override_settings(CELERY_OUTBOX_STALE_TIMEOUT_SECONDS=900)
def test_load_stale_timeout_seconds_setting_returns_configured_value() -> None:
    assert load_stale_timeout_seconds_setting() == 900


@override_settings(CELERY_OUTBOX_STALE_TIMEOUT_SECONDS=0)
def test_load_stale_timeout_seconds_setting_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError, match='CELERY_OUTBOX_STALE_TIMEOUT_SECONDS must be > 0'):
        load_stale_timeout_seconds_setting()
