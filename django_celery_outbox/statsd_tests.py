from unittest.mock import patch

import pytest
from django.test import override_settings

from django_celery_outbox.statsd import _build_constant_tags, get_statsd


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    import django_celery_outbox.statsd as statsd_module

    statsd_module._statsd = None


def test_get_statsd_returns_dogstatsd_instance() -> None:
    with patch('django_celery_outbox.statsd.DogStatsd') as m_cls:
        result = get_statsd()

    assert result is m_cls.return_value


def test_get_statsd_singleton_returns_same_instance() -> None:
    with patch('django_celery_outbox.statsd.DogStatsd') as m_cls:
        result1 = get_statsd()
        result2 = get_statsd()

    assert result1 is result2
    m_cls.assert_called_once()


@override_settings(
    MONITORING_STATSD_HOST='statsd.example.com',
    MONITORING_STATSD_PORT=8125,
    MONITORING_STATSD_PREFIX='myapp',
)
def test_get_statsd_passes_settings() -> None:
    with patch('django_celery_outbox.statsd.DogStatsd') as m_cls:
        get_statsd()

    m_cls.assert_called_once_with(
        host='statsd.example.com',
        port=8125,
        namespace='myapp',
        constant_tags=[],
    )


def test_get_statsd_uses_defaults() -> None:
    with patch('django_celery_outbox.statsd.DogStatsd') as m_cls:
        get_statsd()

    m_cls.assert_called_once_with(
        host='localhost',
        port=9125,
        namespace='celery_outbox',
        constant_tags=[],
    )


@override_settings(MONITORING_STATSD_TAGS={'env': 'prod', 'region': 'us'})
def test_build_constant_tags_converts_dict() -> None:
    result = _build_constant_tags()

    assert sorted(result) == ['env:prod', 'region:us']


def test_build_constant_tags_empty_when_no_setting() -> None:
    result = _build_constant_tags()

    assert result == []


@override_settings(MONITORING_STATSD_TAGS={'env': 'prod', 'service': 'outbox'})
def test_get_statsd_passes_constant_tags() -> None:
    with patch('django_celery_outbox.statsd.DogStatsd') as m_cls:
        get_statsd()

    call_kwargs = m_cls.call_args[1]
    assert sorted(call_kwargs['constant_tags']) == ['env:prod', 'service:outbox']
