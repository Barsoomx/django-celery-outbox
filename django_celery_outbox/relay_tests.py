import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from celery import Celery

from django_celery_outbox.factories import CeleryOutboxFactory
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter
from django_celery_outbox.relay import Relay


@pytest.fixture()
def m_celery_app() -> MagicMock:
    app = MagicMock(spec=Celery)
    app.send_task = MagicMock()
    return app


@pytest.fixture()
def f_relay(m_celery_app: MagicMock) -> Relay:
    return Relay(
        app=m_celery_app,
        batch_size=10,
        idle_time=0.01,
        backoff_time=120,
        max_retries=3,
    )


@pytest.mark.django_db
def test_select_messages_pending_without_updated_at(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        updated_at=None,
    )

    result = f_relay._select_messages()

    assert len(result) == 1
    assert result[0].id == msg.id


@pytest.mark.django_db
def test_select_messages_stale_updated_at(f_relay: Relay) -> None:
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        updated_at=stale_time,
    )

    result = f_relay._select_messages()

    assert len(result) == 1
    assert result[0].id == msg.id


@pytest.mark.django_db
def test_select_messages_skips_inflight(f_relay: Relay) -> None:
    recent_time = datetime.now(timezone.utc) - timedelta(minutes=1)
    CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        updated_at=recent_time,
    )

    result = f_relay._select_messages()

    assert len(result) == 0


@pytest.mark.django_db
def test_select_messages_skips_future_retry_after(f_relay: Relay) -> None:
    future_time = datetime.now(timezone.utc) + timedelta(seconds=300)
    CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        updated_at=datetime.now(timezone.utc),
        retry_after=future_time,
    )

    result = f_relay._select_messages()

    assert len(result) == 0


@pytest.mark.django_db
def test_select_messages_respects_batch_size(m_celery_app: MagicMock) -> None:
    relay = Relay(app=m_celery_app, batch_size=2, max_retries=3)

    for i in range(5):
        CeleryOutbox.objects.create(
            task_id=f'task-{i}',
            task_name='some.task',
            updated_at=None,
        )

    result = relay._select_messages()

    assert len(result) == 2


@pytest.mark.django_db
def test_select_messages_ordered_by_id_asc(f_relay: Relay) -> None:
    msg1 = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        updated_at=None,
    )
    msg2 = CeleryOutbox.objects.create(
        task_id='task-2',
        task_name='some.task',
        updated_at=None,
    )
    msg3 = CeleryOutbox.objects.create(
        task_id='task-3',
        task_name='some.task',
        updated_at=None,
    )

    result = f_relay._select_messages()

    assert [m.id for m in result] == [msg1.id, msg2.id, msg3.id]


@pytest.mark.django_db
def test_process_messages_success(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=0,
    )

    with patch.object(f_relay, '_send_task'):
        published, failed, exceeded = f_relay._process_messages([msg])

    assert published == [msg.id]
    assert failed == []
    assert exceeded == []


@pytest.mark.django_db
def test_process_messages_send_failure(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=0,
    )

    with patch.object(f_relay, '_send_task', side_effect=RuntimeError('broker down')):
        published, failed, exceeded = f_relay._process_messages([msg])

    assert published == []
    assert failed == [(msg.id, 0)]
    assert exceeded == []


@pytest.mark.django_db
def test_process_messages_max_retries_exceeded(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=3,
    )

    with patch.object(f_relay, '_send_task') as m_send:
        published, failed, exceeded = f_relay._process_messages([msg])

    assert published == []
    assert failed == []
    assert exceeded == [msg.id]
    m_send.assert_not_called()


@pytest.mark.django_db
def test_process_messages_failure_at_max_retries(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=2,
    )

    with patch.object(f_relay, '_send_task', side_effect=RuntimeError('fail')):
        published, failed, exceeded = f_relay._process_messages([msg])

    assert published == []
    assert failed == []
    assert exceeded == [msg.id]


@pytest.mark.django_db
def test_send_task_calls_celery(m_celery_app: MagicMock) -> None:
    relay = Relay(app=m_celery_app, max_retries=3)
    msg = CeleryOutbox.objects.create(
        task_id='abc-123',
        task_name='myapp.tasks.do_stuff',
        args=[1, 2],
        kwargs={'key': 'val'},
        options={},
        sentry_trace_id='trace-id-1',
        sentry_baggage='baggage-1',
    )

    with patch('django_celery_outbox.relay.Celery.send_task') as m_send:
        relay._send_task(msg)

    m_send.assert_called_once()
    _, kwargs = m_send.call_args
    assert kwargs['name'] == 'myapp.tasks.do_stuff'
    assert kwargs['args'] == [1, 2]
    assert kwargs['kwargs'] == {'key': 'val'}
    assert kwargs['task_id'] == 'abc-123'
    assert kwargs['headers']['sentry-trace'] == 'trace-id-1'
    assert kwargs['headers']['baggage'] == 'baggage-1'


@pytest.mark.django_db
def test_send_task_with_eta(m_celery_app: MagicMock) -> None:
    eta_dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    relay = Relay(app=m_celery_app, max_retries=3)
    msg = CeleryOutbox.objects.create(
        task_id='abc-456',
        task_name='myapp.tasks.delayed',
        options={'eta': eta_dt.isoformat()},
    )

    with patch('django_celery_outbox.relay.Celery.send_task') as m_send:
        relay._send_task(msg)

    _, kwargs = m_send.call_args
    assert kwargs['eta'] == eta_dt


@pytest.mark.django_db
def test_send_task_restores_structlog_context(m_celery_app: MagicMock) -> None:
    relay = Relay(app=m_celery_app, max_retries=3)
    msg = CeleryOutbox.objects.create(
        task_id='abc-789',
        task_name='myapp.tasks.ctx',
        options={},
        structlog_context=json.dumps({'request_id': 'req-1'}),
    )

    with patch('django_celery_outbox.relay.Celery.send_task'):
        with patch('django_celery_outbox.relay.structlog.contextvars.bound_contextvars') as m_bound:
            relay._send_task(msg)

    m_bound.assert_called_once_with(request_id='req-1')


def test_parse_structlog_context_valid_json() -> None:
    result = Relay._parse_structlog_context('{"k": "v"}')

    assert result == {'k': 'v'}


def test_parse_structlog_context_empty_string() -> None:
    result = Relay._parse_structlog_context('')

    assert result == {}


def test_parse_structlog_context_none() -> None:
    result = Relay._parse_structlog_context(None)

    assert result == {}


def test_parse_structlog_context_invalid_json() -> None:
    result = Relay._parse_structlog_context('invalid')

    assert result == {}


@pytest.mark.django_db
def test_update_failed_increments_retries(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=1,
        updated_at=None,
    )

    f_relay._update_failed([(msg.id, 1)])

    msg.refresh_from_db()
    assert msg.retries == 2
    assert msg.updated_at is not None
    assert msg.retry_after is not None


@pytest.mark.django_db
def test_update_failed_empty_list(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=0,
    )

    f_relay._update_failed([])

    msg.refresh_from_db()
    assert msg.retries == 0


@pytest.mark.django_db
def test_delete_done_removes_records(f_relay: Relay) -> None:
    msg1 = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
    )
    msg2 = CeleryOutbox.objects.create(
        task_id='task-2',
        task_name='some.task',
    )

    f_relay._delete_done([msg1.id])

    assert not CeleryOutbox.objects.filter(pk=msg1.id).exists()
    assert CeleryOutbox.objects.filter(pk=msg2.id).exists()


@pytest.mark.django_db
def test_delete_done_empty_list(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
    )

    f_relay._delete_done([])

    assert CeleryOutbox.objects.filter(pk=msg.id).exists()


@pytest.mark.django_db
def test_processing_full_cycle(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        batch_size=10,
        idle_time=0.01,
        max_retries=3,
    )

    msg_ok = CeleryOutbox.objects.create(
        task_id='task-ok',
        task_name='some.task',
        options={},
        retries=0,
    )
    msg_exceeded = CeleryOutbox.objects.create(
        task_id='task-exceeded',
        task_name='some.task',
        options={},
        retries=3,
    )

    with patch('django_celery_outbox.relay.Celery.send_task'):
        with patch('django_celery_outbox.relay.time.sleep') as m_sleep:
            relay._processing()

    assert not CeleryOutbox.objects.filter(pk=msg_ok.id).exists()
    assert not CeleryOutbox.objects.filter(pk=msg_exceeded.id).exists()
    assert CeleryOutboxDeadLetter.objects.filter(task_id='task-exceeded').exists()
    dead = CeleryOutboxDeadLetter.objects.get(task_id='task-exceeded')
    assert dead.failure_reason == 'max retries exceeded'
    m_sleep.assert_called_once_with(0.01)


@pytest.mark.django_db
def test_processing_no_sleep_when_batch_full(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        batch_size=2,
        idle_time=0.01,
        max_retries=3,
    )

    for i in range(3):
        CeleryOutbox.objects.create(
            task_id=f'task-{i}',
            task_name='some.task',
            options={},
            retries=0,
        )

    with patch('django_celery_outbox.relay.Celery.send_task'):
        with patch('django_celery_outbox.relay.time.sleep') as m_sleep:
            relay._processing()

    m_sleep.assert_not_called()


@pytest.mark.django_db
def test_processing_failed_messages_retained(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        batch_size=10,
        idle_time=0.01,
        max_retries=3,
    )

    msg = CeleryOutbox.objects.create(
        task_id='task-fail',
        task_name='some.task',
        options={},
        retries=0,
    )

    with patch('django_celery_outbox.relay.Celery.send_task', side_effect=RuntimeError('fail')):
        with patch('django_celery_outbox.relay.time.sleep'):
            relay._processing()

    msg.refresh_from_db()
    assert msg.retries == 1
    assert msg.updated_at is not None
    assert msg.retry_after is not None


@pytest.mark.django_db
def test_send_task_without_sentry_context(m_celery_app: MagicMock) -> None:
    relay = Relay(app=m_celery_app, max_retries=3)
    msg = CeleryOutbox.objects.create(
        task_id='abc-no-sentry',
        task_name='myapp.tasks.no_sentry',
        args=[],
        kwargs={},
        options={},
        sentry_trace_id=None,
        sentry_baggage=None,
    )

    with patch('django_celery_outbox.relay.Celery.send_task') as m_send:
        relay._send_task(msg)

    _, kwargs = m_send.call_args
    assert 'sentry-trace' not in kwargs['headers']
    assert 'baggage' not in kwargs['headers']


@pytest.mark.django_db
def test_send_task_propagates_extra_options(m_celery_app: MagicMock) -> None:
    relay = Relay(app=m_celery_app, max_retries=3)
    msg = CeleryOutbox.objects.create(
        task_id='abc-opts',
        task_name='myapp.tasks.with_opts',
        args=[],
        kwargs={},
        options={'priority': 9, 'routing_key': 'high'},
    )

    with patch('django_celery_outbox.relay.Celery.send_task') as m_send:
        relay._send_task(msg)

    _, kwargs = m_send.call_args
    assert kwargs['priority'] == 9
    assert kwargs['routing_key'] == 'high'


def test_process_messages_empty_list(f_relay: Relay) -> None:
    published, failed, exceeded = f_relay._process_messages([])

    assert published == []
    assert failed == []
    assert exceeded == []


@pytest.mark.django_db
def test_processing_calls_close_old_connections(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        batch_size=10,
        idle_time=0.01,
        max_retries=3,
    )

    with patch('django_celery_outbox.relay.Celery.send_task'):
        with patch('django_celery_outbox.relay.time.sleep'):
            with patch('django_celery_outbox.relay.close_old_connections') as m_close:
                relay._processing()

    assert m_close.call_count == 2


@pytest.mark.django_db
def test_processing_sets_updated_at_on_select(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        batch_size=10,
        idle_time=0.01,
        max_retries=3,
    )

    msg = CeleryOutboxFactory.create(options={}, updated_at=None)
    before = datetime.now(timezone.utc)

    with patch('django_celery_outbox.relay.Celery.send_task', side_effect=RuntimeError('fail')):
        with patch('django_celery_outbox.relay.time.sleep'):
            relay._processing()

    msg.refresh_from_db()
    assert msg.updated_at is not None
    assert msg.updated_at >= before


@pytest.mark.django_db
def test_send_task_with_headers_none_in_options(m_celery_app: MagicMock) -> None:
    relay = Relay(app=m_celery_app, max_retries=3)
    msg = CeleryOutbox.objects.create(
        task_id='abc-headers-none',
        task_name='myapp.tasks.headers_none',
        args=[],
        kwargs={},
        options={'headers': None},
    )

    with patch('django_celery_outbox.relay.Celery.send_task') as m_send:
        relay._send_task(msg)

    m_send.assert_called_once()
    _, kwargs = m_send.call_args
    assert isinstance(kwargs['headers'], dict)


def test_graceful_shutdown_stops_start_loop(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        batch_size=10,
        idle_time=0.01,
        max_retries=3,
    )
    relay._running = False

    with patch.object(relay, '_setup_signals'):
        with patch.object(relay, '_processing') as m_processing:
            relay.start()

    m_processing.assert_not_called()


def test_config_validation_batch_size_zero(m_celery_app: MagicMock) -> None:
    with pytest.raises(ValueError, match='batch_size must be > 0'):
        Relay(app=m_celery_app, batch_size=0)


def test_config_validation_negative_idle_time(m_celery_app: MagicMock) -> None:
    with pytest.raises(ValueError, match='idle_time must be >= 0'):
        Relay(app=m_celery_app, idle_time=-1.0)


def test_config_validation_zero_backoff_time(m_celery_app: MagicMock) -> None:
    with pytest.raises(ValueError, match='backoff_time must be > 0'):
        Relay(app=m_celery_app, backoff_time=0)


def test_config_validation_zero_max_retries(m_celery_app: MagicMock) -> None:
    with pytest.raises(ValueError, match='max_retries must be > 0'):
        Relay(app=m_celery_app, max_retries=0)


@pytest.mark.django_db
def test_processing_logs_batch_summary(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        batch_size=10,
        idle_time=0.01,
        max_retries=3,
    )

    CeleryOutboxFactory.create(options={}, retries=0)

    with patch('django_celery_outbox.relay._logger') as m_logger:
        with patch('django_celery_outbox.relay.Celery.send_task'):
            with patch('django_celery_outbox.relay.time.sleep'):
                relay._processing()

    m_logger.info.assert_any_call(
        'celery_outbox_batch_processed',
        published=1,
        failed=0,
        exceeded=0,
        queue_depth=0,
    )


def test_touch_liveness_creates_file(m_celery_app: MagicMock, tmp_path: object) -> None:
    liveness_file = f'{tmp_path}/alive'
    relay = Relay(app=m_celery_app, liveness_file=liveness_file, max_retries=3)

    relay._touch_liveness()

    from pathlib import Path

    assert Path(liveness_file).exists()


def test_touch_liveness_noop_when_not_configured(m_celery_app: MagicMock) -> None:
    relay = Relay(app=m_celery_app, max_retries=3)

    relay._touch_liveness()


@pytest.mark.django_db
def test_processing_touches_liveness_file(m_celery_app: MagicMock, tmp_path: object) -> None:
    liveness_file = f'{tmp_path}/alive'
    relay = Relay(
        app=m_celery_app,
        batch_size=10,
        idle_time=0.01,
        max_retries=3,
        liveness_file=liveness_file,
    )

    with patch('django_celery_outbox.relay.Celery.send_task'):
        with patch('django_celery_outbox.relay.time.sleep'):
            relay._processing()

    from pathlib import Path

    assert Path(liveness_file).exists()


@pytest.mark.django_db
@patch('django_celery_outbox.relay.sentry_sdk')
def test_processing_creates_batch_span(m_sentry: MagicMock, f_relay: Relay) -> None:
    m_batch_span = MagicMock()
    m_sentry.start_span.return_value.__enter__.return_value = m_batch_span

    with patch('django_celery_outbox.relay.time.sleep'):
        f_relay._processing()

    m_sentry.start_span.assert_called_with(
        op='queue.process',
        name='celery_outbox.relay.batch',
    )
    m_batch_span.set_status.assert_called_once_with('ok')


@pytest.mark.django_db
@patch('django_celery_outbox.relay.sentry_sdk')
def test_processing_batch_span_internal_error_on_failure(
    m_sentry: MagicMock,
    f_relay: Relay,
) -> None:
    m_batch_span = MagicMock()
    m_sentry.start_span.return_value.__enter__.return_value = m_batch_span
    CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='fail.task',
    )

    with patch('django_celery_outbox.relay.Celery.send_task', side_effect=ConnectionError('broker down')):
        with patch('django_celery_outbox.relay.time.sleep'):
            f_relay._processing()

    m_batch_span.set_status.assert_called_with('internal_error')


@pytest.mark.django_db
@patch('django_celery_outbox.relay.sentry_sdk')
def test_process_messages_creates_per_message_span(
    m_sentry: MagicMock,
    f_relay: Relay,
) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='msg-123',
        task_name='my.task',
        retries=0,
    )
    m_span = MagicMock()
    m_sentry.start_span.return_value.__enter__.return_value = m_span

    with patch.object(f_relay, '_send_task'):
        f_relay._process_messages([msg])

    m_sentry.start_span.assert_called_with(
        op='celery_outbox.relay.send',
        name='my.task',
    )
    m_span.set_data.assert_any_call('messaging.message.id', 'msg-123')
    m_span.set_data.assert_any_call('messaging.message.retry.count', 0)
    m_span.set_status.assert_called_once_with('ok')


@pytest.mark.django_db
@patch('django_celery_outbox.relay.sentry_sdk')
def test_process_messages_span_internal_error_on_send_failure(
    m_sentry: MagicMock,
    f_relay: Relay,
) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='fail.task',
        retries=0,
    )
    m_span = MagicMock()
    m_sentry.start_span.return_value.__enter__.return_value = m_span

    with patch.object(f_relay, '_send_task', side_effect=ConnectionError('down')):
        f_relay._process_messages([msg])

    m_span.set_status.assert_called_once_with('internal_error')
