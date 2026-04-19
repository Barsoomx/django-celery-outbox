from unittest.mock import MagicMock, patch

import pytest
from celery import Celery
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


@override_settings(CELERY_OUTBOX_APP=None)
def test_get_celery_app_raises_without_setting() -> None:
    with pytest.raises(ValueError, match='CELERY_OUTBOX_APP setting is required'):
        Command._get_celery_app()


@patch.object(Command, '_get_celery_app')
@patch('django_celery_outbox.management.commands.celery_outbox_relay.Relay')
def test_handle_creates_relay_with_reliability_params(
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
        stale_timeout_seconds=300,
        send_timeout=10.0,
        shutdown_timeout=30.0,
        broker_outage_cooldown=30.0,
        max_backoff=3600.0,
        liveness_file='/var/run/celery-outbox-alive',
    )

    m_relay_cls.assert_called_once_with(
        app=m_app,
        config=RelayConfig.init(
            batch_size=50,
            idle_time=2.0,
            backoff_time=60,
            max_retries=3,
            stale_timeout_seconds=300,
            send_timeout=10.0,
            shutdown_timeout=30.0,
            broker_outage_cooldown=30.0,
            max_backoff=3600.0,
            liveness_file='/var/run/celery-outbox-alive',
        ),
    )
    m_relay_cls.return_value.start.assert_called_once()


@override_settings(CELERY_OUTBOX_APP='no_dot_in_path')
def test_get_celery_app_invalid_path_raises() -> None:
    with pytest.raises(ValueError, match='CELERY_OUTBOX_APP must be a dotted path'):
        Command._get_celery_app()


@override_settings(CELERY_OUTBOX_APP='nonexistent.module.app')
def test_get_celery_app_nonexistent_module_raises_value_error() -> None:
    with pytest.raises(ValueError, match='module could not be imported'):
        Command._get_celery_app()


def test_add_arguments_registers_reliability_params() -> None:
    command = Command()
    parser = command.create_parser('manage.py', 'celery_outbox_relay')
    defaults = parser.parse_args([])
    parsed = parser.parse_args(
        [
            '--send-timeout',
            '12.5',
            '--shutdown-timeout',
            '45.0',
            '--broker-outage-cooldown',
            '90.5',
            '--max-backoff',
            '7200.0',
        ],
    )

    assert vars(defaults)['send_timeout'] == 10.0
    assert vars(defaults)['shutdown_timeout'] == 30.0
    assert vars(defaults)['broker_outage_cooldown'] == 30.0
    assert vars(defaults)['max_backoff'] == 3600.0

    assert vars(parsed)['send_timeout'] == 12.5
    assert vars(parsed)['shutdown_timeout'] == 45.0
    assert vars(parsed)['broker_outage_cooldown'] == 90.5
    assert vars(parsed)['max_backoff'] == 7200.0

    assert isinstance(parsed.send_timeout, float)
    assert isinstance(parsed.shutdown_timeout, float)
    assert isinstance(parsed.broker_outage_cooldown, float)
    assert isinstance(parsed.max_backoff, float)


@override_settings(
    CELERY_OUTBOX_APP='django_celery_outbox.management.commands.celery_outbox_relay_tests.valid_celery_app',
    CELERY_OUTBOX_STALE_TIMEOUT_SECONDS=900,
)
def test_add_arguments_defaults_stale_timeout_from_settings() -> None:
    command = Command()
    parser = command.create_parser('manage.py', 'celery_outbox_relay')

    defaults = parser.parse_args([])

    assert defaults.stale_timeout_seconds == 900
