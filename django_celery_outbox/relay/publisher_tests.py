import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from celery import Celery

from django_celery_outbox.models import CeleryOutbox
from django_celery_outbox.relay._publisher import RelayPublisher, parse_structlog_context


@pytest.fixture()
def m_celery_app() -> MagicMock:
    app = MagicMock(spec=Celery)
    app.send_task = MagicMock()
    return app


@pytest.mark.django_db
def test_publish_calls_raw_celery_send_task(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app, send_timeout=10.0)
    eta_dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    msg = CeleryOutbox.objects.create(
        task_id='abc-123',
        task_name='myapp.tasks.do_stuff',
        args=[1, 2],
        kwargs={'key': 'val'},
        options={'eta': eta_dt.isoformat(), 'priority': 9},
        sentry_trace_id='trace-id-1',
        sentry_baggage='baggage-1',
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task') as m_send:
        publisher.publish(msg)

    _, kwargs = m_send.call_args
    assert kwargs['name'] == 'myapp.tasks.do_stuff'
    assert kwargs['args'] == [1, 2]
    assert kwargs['kwargs'] == {'key': 'val'}
    assert kwargs['task_id'] == 'abc-123'
    assert kwargs['eta'] == eta_dt
    assert kwargs['priority'] == 9
    assert kwargs['headers']['sentry-trace'] == 'trace-id-1'
    assert kwargs['headers']['baggage'] == 'baggage-1'


@pytest.mark.django_db
def test_publish_passes_timeout_to_raw_celery_send_task(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app, send_timeout=10.0)
    msg = CeleryOutbox.objects.create(
        task_id='timeout-123',
        task_name='myapp.tasks.timeout',
        options={},
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task') as m_send:
        publisher.publish(msg)

    _, kwargs = m_send.call_args
    assert kwargs['timeout'] == 10.0


@pytest.mark.django_db
def test_publish_send_timeout_overrides_deserialized_timeout_option(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app, send_timeout=10.0)
    msg = CeleryOutbox.objects.create(
        task_id='timeout-override-123',
        task_name='myapp.tasks.timeout_override',
        options={},
    )

    with patch(
        'django_celery_outbox.relay._publisher.deserialize_options',
        return_value={'timeout': 1.5, 'priority': 9},
    ):
        with patch('django_celery_outbox.relay._publisher.Celery.send_task') as m_send:
            publisher.publish(msg)

    _, kwargs = m_send.call_args
    assert kwargs['timeout'] == 10.0
    assert kwargs['priority'] == 9


@pytest.mark.django_db
def test_publish_binds_structlog_context(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app, send_timeout=10.0)
    msg = CeleryOutbox.objects.create(
        task_id='ctx-123',
        task_name='myapp.tasks.ctx',
        options={},
        structlog_context=json.dumps({'request_id': 'req-1'}),
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
        with patch('django_celery_outbox.relay._publisher.structlog.contextvars.bound_contextvars') as m_bound:
            publisher.publish(msg)

    m_bound.assert_called_once_with(request_id='req-1')


@pytest.mark.django_db
def test_publish_tolerates_headers_none(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app, send_timeout=10.0)
    msg = CeleryOutbox.objects.create(
        task_id='headers-none',
        task_name='myapp.tasks.headers',
        options={'headers': None},
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task') as m_send:
        publisher.publish(msg)

    _, kwargs = m_send.call_args
    assert kwargs['headers'] == {}


@pytest.mark.django_db
def test_publish_without_sentry_context_does_not_add_headers(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app, send_timeout=10.0)
    msg = CeleryOutbox.objects.create(
        task_id='no-sentry',
        task_name='myapp.tasks.no_sentry',
        options={},
        sentry_trace_id=None,
        sentry_baggage=None,
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task') as m_send:
        publisher.publish(msg)

    _, kwargs = m_send.call_args
    assert kwargs['headers'] == {}


@pytest.mark.django_db
def test_publish_propagates_extra_options(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app, send_timeout=10.0)
    msg = CeleryOutbox.objects.create(
        task_id='extra-opts',
        task_name='myapp.tasks.extra',
        options={'priority': 9, 'routing_key': 'high'},
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task') as m_send:
        publisher.publish(msg)

    _, kwargs = m_send.call_args
    assert kwargs['priority'] == 9
    assert kwargs['routing_key'] == 'high'


@pytest.mark.django_db
def test_publish_passes_schema_version_to_deserializer(m_celery_app: MagicMock) -> None:
    publisher = RelayPublisher(app=m_celery_app, send_timeout=10.0)
    msg = CeleryOutbox.objects.create(
        task_id='schema-v2',
        task_name='myapp.tasks.schema',
        options={'priority': 9},
        schema_version=2,
    )

    with patch('django_celery_outbox.relay._publisher.deserialize_options', return_value={'priority': 9}) as m_deserialize:
        with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
            publisher.publish(msg)

    m_deserialize.assert_called_once_with(msg.options, m_celery_app, 2)


def test_parse_structlog_context_valid_json() -> None:
    assert parse_structlog_context('{"k": "v"}') == {'k': 'v'}


def test_parse_structlog_context_empty_string_returns_empty_dict() -> None:
    assert parse_structlog_context('') == {}


def test_parse_structlog_context_invalid_json_returns_empty_dict() -> None:
    assert parse_structlog_context('invalid') == {}


def test_parse_structlog_context_none_returns_empty_dict() -> None:
    assert parse_structlog_context(None) == {}


def test_parse_structlog_context_non_object_json_returns_empty_dict() -> None:
    assert parse_structlog_context('[]') == {}
