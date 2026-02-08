from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from django_celery_outbox.management.commands.celery_outbox_relay import Command

_fake_app = object()


@override_settings(CELERY_OUTBOX_APP='django_celery_outbox.management.commands.celery_outbox_relay_tests._fake_app')
def test_get_celery_app_loads_module_by_path() -> None:
    result = Command._get_celery_app()

    assert result is _fake_app


def test_get_celery_app_raises_without_setting() -> None:
    with pytest.raises(ValueError, match='CELERY_OUTBOX_APP setting is required'):
        Command._get_celery_app()


@patch.object(Command, '_get_celery_app')
@patch('django_celery_outbox.management.commands.celery_outbox_relay.Relay')
def test_handle_creates_relay_with_correct_params(
    m_relay_cls: MagicMock,
    m_get_celery_app: MagicMock,
) -> None:
    m_app = MagicMock()
    m_get_celery_app.return_value = m_app
    command = Command()

    command.handle(
        batch_size=50,
        idle_time=2.0,
        backoff_time=60,
        max_retries=3,
        liveness_file='/var/run/celery-outbox-alive',
    )

    m_relay_cls.assert_called_once_with(
        app=m_app,
        batch_size=50,
        idle_time=2.0,
        backoff_time=60,
        max_retries=3,
        liveness_file='/var/run/celery-outbox-alive',
    )
    m_relay_cls.return_value.start.assert_called_once()


@override_settings(CELERY_OUTBOX_APP='no_dot_in_path')
def test_get_celery_app_invalid_path_raises() -> None:
    with pytest.raises(ValueError, match='CELERY_OUTBOX_APP must be a dotted path'):
        Command._get_celery_app()


@override_settings(CELERY_OUTBOX_APP='nonexistent.module.app')
def test_get_celery_app_nonexistent_module_raises() -> None:
    with pytest.raises(ModuleNotFoundError):
        Command._get_celery_app()


def test_add_arguments_registers_all_params() -> None:
    command = Command()
    parser = MagicMock()

    command.add_arguments(parser)

    assert parser.add_argument.call_count == 5
    arg_names = [c.args[0] for c in parser.add_argument.call_args_list]
    assert '--batch-size' in arg_names
    assert '--idle-time' in arg_names
    assert '--backoff-time' in arg_names
    assert '--max-retries' in arg_names
    assert '--liveness-file' in arg_names
