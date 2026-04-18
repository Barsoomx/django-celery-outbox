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
