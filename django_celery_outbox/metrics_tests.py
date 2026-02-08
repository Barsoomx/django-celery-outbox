from unittest.mock import MagicMock, patch

from django.test import override_settings

from django_celery_outbox import metrics


@override_settings(MONITORING_METRICS_ENABLED=True)
def test_increment_calls_statsd_when_enabled() -> None:
    with patch('django_celery_outbox.metrics.get_statsd') as m_get_statsd:
        m_statsd = MagicMock()
        m_get_statsd.return_value = m_statsd

        metrics.increment('messages.published', value=1, tags={'task_name': 'my.task'})

    m_statsd.increment.assert_called_once_with(
        'messages.published',
        value=1,
        tags=['task_name:my.task'],
    )


@override_settings(MONITORING_METRICS_ENABLED=True)
def test_gauge_calls_statsd_when_enabled() -> None:
    with patch('django_celery_outbox.metrics.get_statsd') as m_get_statsd:
        m_statsd = MagicMock()
        m_get_statsd.return_value = m_statsd

        metrics.gauge('queue.depth', value=42, tags={'env': 'prod'})

    m_statsd.gauge.assert_called_once_with(
        'queue.depth',
        value=42,
        tags=['env:prod'],
    )


@override_settings(MONITORING_METRICS_ENABLED=True)
def test_timing_calls_statsd_when_enabled() -> None:
    with patch('django_celery_outbox.metrics.get_statsd') as m_get_statsd:
        m_statsd = MagicMock()
        m_get_statsd.return_value = m_statsd

        metrics.timing('batch.duration_ms', value_ms=123.45, tags={'region': 'us'})

    m_statsd.timing.assert_called_once_with(
        'batch.duration_ms',
        value=123.45,
        tags=['region:us'],
    )


@override_settings(MONITORING_METRICS_ENABLED=False)
def test_increment_noop_when_disabled() -> None:
    with patch('django_celery_outbox.metrics.get_statsd') as m_get_statsd:
        metrics.increment('messages.published')

    m_get_statsd.assert_not_called()


@override_settings(MONITORING_METRICS_ENABLED=False)
def test_gauge_noop_when_disabled() -> None:
    with patch('django_celery_outbox.metrics.get_statsd') as m_get_statsd:
        metrics.gauge('queue.depth', value=10)

    m_get_statsd.assert_not_called()


@override_settings(MONITORING_METRICS_ENABLED=False)
def test_timing_noop_when_disabled() -> None:
    with patch('django_celery_outbox.metrics.get_statsd') as m_get_statsd:
        metrics.timing('batch.duration_ms', value_ms=50.0)

    m_get_statsd.assert_not_called()


def test_to_tags_converts_dict_to_list() -> None:
    result = metrics._to_tags({'task_name': 'my.task', 'env': 'prod'})

    assert result == ['task_name:my.task', 'env:prod']


def test_to_tags_returns_none_for_none() -> None:
    result = metrics._to_tags(None)

    assert result is None


def test_to_tags_returns_none_for_empty_dict() -> None:
    result = metrics._to_tags({})

    assert result is None


@override_settings(MONITORING_METRICS_ENABLED=True)
def test_is_enabled_returns_true_when_enabled() -> None:
    assert metrics._is_enabled() is True


@override_settings(MONITORING_METRICS_ENABLED=False)
def test_is_enabled_returns_false_when_disabled() -> None:
    assert metrics._is_enabled() is False


@override_settings(MONITORING_METRICS_ENABLED=True)
def test_increment_without_tags() -> None:
    with patch('django_celery_outbox.metrics.get_statsd') as m_get_statsd:
        m_statsd = MagicMock()
        m_get_statsd.return_value = m_statsd

        metrics.increment('messages.published')

    m_statsd.increment.assert_called_once_with(
        'messages.published',
        value=1,
        tags=None,
    )


def test_is_enabled_defaults_to_true() -> None:
    result = metrics._is_enabled()

    assert result is True
