import math
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from celery import Celery
from django.core.exceptions import ImproperlyConfigured
from django.db import connections
from django.test import override_settings
from django.utils import timezone as django_timezone

from django_celery_outbox.factories import CeleryOutboxFactory
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter
from django_celery_outbox.relay import Relay, RelayConfig
from django_celery_outbox.relay._message_selector import MessageSelector
from django_celery_outbox.relay._mutations import RelayMutations
from django_celery_outbox.relay._publisher import RelayPublisher


@pytest.fixture()
def m_celery_app() -> MagicMock:
    app = MagicMock(spec=Celery)
    app.send_task = MagicMock()
    return app


@pytest.fixture()
def m_metrics() -> MagicMock:
    with patch('django_celery_outbox.relay._relay.metrics') as mock:
        yield mock


@pytest.fixture()
def f_config() -> RelayConfig:
    return RelayConfig.init(
        batch_size=10,
        idle_time=0.01,
        backoff_time=120,
        max_retries=3,
    )


# TODO(mcproger) extract message selector tests?
@pytest.fixture()
def f_message_selector() -> MessageSelector:
    return MessageSelector(batch_size=10)


@pytest.fixture()
def f_relay(m_celery_app: MagicMock, f_config: RelayConfig) -> Relay:
    return Relay(app=m_celery_app, config=f_config)


def _enable_relay_for_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = connections[CeleryOutbox.objects.db]
    monkeypatch.setattr(connection.features, 'has_select_for_update_skip_locked', True, raising=False)


@pytest.mark.django_db
def test_select_messages_pending_without_updated_at(f_message_selector: MessageSelector) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        updated_at=None,
    )

    result = f_message_selector.run()

    assert len(result) == 1
    assert result[0].id == msg.id


@pytest.mark.django_db
def test_select_messages_stale_updated_at(f_message_selector: MessageSelector) -> None:
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        updated_at=stale_time,
    )

    result = f_message_selector.run()

    assert len(result) == 1
    assert result[0].id == msg.id


@pytest.mark.django_db
def test_select_messages_skips_inflight(f_message_selector: MessageSelector) -> None:
    recent_time = datetime.now(timezone.utc) - timedelta(minutes=1)
    CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        updated_at=recent_time,
    )

    result = f_message_selector.run()

    assert len(result) == 0


@pytest.mark.django_db
def test_select_messages_skips_future_retry_after(f_message_selector: MessageSelector) -> None:
    future_time = datetime.now(timezone.utc) + timedelta(seconds=300)
    CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        updated_at=datetime.now(timezone.utc),
        retry_after=future_time,
    )

    result = f_message_selector.run()

    assert len(result) == 0


@pytest.mark.django_db
def test_select_messages_respects_batch_size() -> None:
    selector = MessageSelector(batch_size=2)

    for i in range(5):
        CeleryOutbox.objects.create(
            task_id=f'task-{i}',
            task_name='some.task',
            updated_at=None,
        )

    result = selector.run()

    assert len(result) == 2


@pytest.mark.django_db
def test_select_messages_ordered_by_id_asc(f_message_selector: MessageSelector) -> None:
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

    result = f_message_selector.run()

    assert [m.id for m in result] == [msg1.id, msg2.id, msg3.id]


@pytest.mark.django_db
def test_process_messages_success(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=0,
    )

    with patch.object(f_relay._publisher, 'publish'):
        published, failed, exceeded, deferred_due_to_outage, shutdown_aborted = f_relay._process_messages([msg])

    assert published == [msg.id]
    assert failed == []
    assert exceeded == []
    assert deferred_due_to_outage == []
    assert shutdown_aborted == []


@pytest.mark.django_db
def test_process_messages_send_failure(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=0,
    )

    with patch.object(f_relay._publisher, 'publish', side_effect=RuntimeError('broker down')):
        published, failed, exceeded, deferred_due_to_outage, shutdown_aborted = f_relay._process_messages([msg])

    assert published == []
    assert failed == [(msg.id, 0)]
    assert exceeded == []
    assert deferred_due_to_outage == []
    assert shutdown_aborted == []


@pytest.mark.django_db
def test_process_messages_max_retries_exceeded(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=3,
    )

    with patch.object(f_relay._publisher, 'publish') as m_publish:
        published, failed, exceeded, deferred_due_to_outage, shutdown_aborted = f_relay._process_messages([msg])

    assert published == []
    assert failed == []
    assert [message.id for message in exceeded] == [msg.id]
    assert deferred_due_to_outage == []
    assert shutdown_aborted == []
    m_publish.assert_not_called()


@pytest.mark.django_db
def test_process_messages_failure_at_max_retries(f_relay: Relay) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=2,
    )

    with patch.object(f_relay._publisher, 'publish', side_effect=RuntimeError('fail')):
        published, failed, exceeded, deferred_due_to_outage, shutdown_aborted = f_relay._process_messages([msg])

    assert published == []
    assert failed == []
    assert [message.id for message in exceeded] == [msg.id]
    assert deferred_due_to_outage == []
    assert shutdown_aborted == []


@pytest.mark.django_db
def test_processing_full_cycle(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(batch_size=10, idle_time=0.01, max_retries=3),
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

    with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
        with patch('django_celery_outbox.relay._relay.time.sleep') as m_sleep:
            with patch('django_celery_outbox.relay._relay.close_old_connections'):
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
        config=RelayConfig.init(batch_size=2, idle_time=0.01, max_retries=3),
    )

    for i in range(3):
        CeleryOutbox.objects.create(
            task_id=f'task-{i}',
            task_name='some.task',
            options={},
            retries=0,
        )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
        with patch('django_celery_outbox.relay._relay.time.sleep') as m_sleep:
            with patch('django_celery_outbox.relay._relay.close_old_connections'):
                relay._processing()

    m_sleep.assert_not_called()


@pytest.mark.django_db
def test_processing_failed_messages_retained(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(batch_size=10, idle_time=0.01, max_retries=3),
    )

    msg = CeleryOutbox.objects.create(
        task_id='task-fail',
        task_name='some.task',
        options={},
        retries=0,
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task', side_effect=RuntimeError('fail')):
        with patch('django_celery_outbox.relay._relay.time.sleep'):
            with patch('django_celery_outbox.relay._relay.close_old_connections'):
                relay._processing()

    msg.refresh_from_db()
    assert msg.retries == 1
    assert msg.updated_at is not None
    assert msg.retry_after is not None


@pytest.mark.django_db
def test_processing_defers_broker_outages_without_consuming_retries(
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(
            batch_size=10,
            idle_time=0,
            backoff_time=120,
            max_retries=5,
            send_timeout=10.0,
            shutdown_timeout=30.0,
            broker_outage_cooldown=30.0,
            max_backoff=3600.0,
        ),
    )
    msg1 = CeleryOutbox.objects.create(task_id='outage-1', task_name='some.task', retries=0, options={})
    msg2 = CeleryOutbox.objects.create(task_id='outage-2', task_name='some.task', retries=0, options={})

    with patch.object(
        relay._publisher,
        'publish',
        side_effect=[TimeoutError('timed out'), TimeoutError('timed out again')],
    ):
        with patch('django_celery_outbox.relay._relay.close_old_connections'):
            with patch('django_celery_outbox.relay._relay.time.sleep'):
                relay._processing()

    msg1.refresh_from_db()
    msg2.refresh_from_db()
    assert msg1.retries == 0
    assert msg2.retries == 0
    assert msg1.retry_after is not None
    assert msg2.retry_after is not None


@pytest.mark.django_db
def test_processing_breaker_trip_defers_remaining_selected_rows(
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(
            batch_size=10,
            idle_time=0,
            backoff_time=120,
            max_retries=5,
            send_timeout=10.0,
            shutdown_timeout=30.0,
            broker_outage_cooldown=30.0,
            max_backoff=3600.0,
        ),
    )
    first = CeleryOutbox.objects.create(task_id='trip-1', task_name='some.task', retries=0, options={})
    second = CeleryOutbox.objects.create(task_id='trip-2', task_name='some.task', retries=0, options={})
    third = CeleryOutbox.objects.create(task_id='trip-3', task_name='some.task', retries=0, options={})

    with patch.object(
        relay._publisher,
        'publish',
        side_effect=[TimeoutError('timed out'), TimeoutError('timed out again')],
    ):
        with patch('django_celery_outbox.relay._relay._logger') as m_logger:
            with patch('django_celery_outbox.relay._relay.close_old_connections'):
                with patch('django_celery_outbox.relay._relay.time.sleep'):
                    relay._processing()

    first.refresh_from_db()
    second.refresh_from_db()
    third.refresh_from_db()
    assert first.retries == 0
    assert second.retries == 0
    assert third.retries == 0
    assert first.retry_after is not None
    assert second.retry_after is not None
    assert third.retry_after is not None
    assert CeleryOutbox.objects.filter(pk=third.pk).exists()
    m_logger.warning.assert_any_call(
        'celery_outbox_relay_breaker_trip',
        deferred_count=3,
        exception_type='TimeoutError',
        exception_message='timed out again',
    )
    m_logger.info.assert_any_call(
        'celery_outbox_batch_processed',
        published=0,
        failed=0,
        exceeded=0,
        deferred_due_to_outage=3,
        shutdown_aborted=0,
        queue_depth=3,
    )


@pytest.mark.django_db
def test_processing_skips_selection_while_breaker_open(
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(
            idle_time=0,
            send_timeout=10.0,
            shutdown_timeout=30.0,
            broker_outage_cooldown=30.0,
            max_backoff=3600.0,
        ),
    )
    relay._policy.begin_batch()
    assert relay._policy.record_outage(now_monotonic=100.0) is False
    assert relay._policy.record_outage(now_monotonic=101.0) is True

    with patch.object(relay._selector, 'run') as m_run:
        with patch('django_celery_outbox.relay._relay.time.monotonic', side_effect=[110.0, 110.0]):
            with patch('django_celery_outbox.relay._relay.time.sleep') as m_sleep:
                relay._processing()

    m_run.assert_not_called()
    m_sleep.assert_called_once_with(21.0)


@pytest.mark.django_db
def test_processing_breaker_counts_only_consecutive_outage_failures(
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(
            batch_size=10,
            idle_time=0,
            backoff_time=120,
            max_retries=5,
            send_timeout=10.0,
            shutdown_timeout=30.0,
            broker_outage_cooldown=30.0,
            max_backoff=3600.0,
        ),
    )
    first = CeleryOutbox.objects.create(task_id='breaker-1', task_name='some.task', retries=0, options={})
    second = CeleryOutbox.objects.create(task_id='breaker-2', task_name='some.task', retries=0, options={})
    third = CeleryOutbox.objects.create(task_id='breaker-3', task_name='some.task', retries=0, options={})
    fourth = CeleryOutbox.objects.create(task_id='breaker-4', task_name='some.task', retries=0, options={})

    with patch.object(
        relay._publisher,
        'publish',
        side_effect=[
            TimeoutError('timed out'),
            RuntimeError('ordinary failure'),
            TimeoutError('timed out again'),
            None,
        ],
    ):
        with patch('django_celery_outbox.relay._relay.close_old_connections'):
            with patch('django_celery_outbox.relay._relay.time.sleep'):
                relay._processing()

    first.refresh_from_db()
    second.refresh_from_db()
    third.refresh_from_db()
    assert first.retries == 0
    assert first.retry_after is not None
    assert second.retries == 1
    assert second.retry_after is not None
    assert third.retries == 0
    assert third.retry_after is not None
    assert not CeleryOutbox.objects.filter(pk=fourth.pk).exists()


@pytest.mark.django_db
def test_processing_shutdown_deadline_leaves_unstarted_rows_for_stale_recovery(
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(
            batch_size=10,
            idle_time=0,
            backoff_time=120,
            max_retries=5,
            send_timeout=10.0,
            shutdown_timeout=30.0,
            broker_outage_cooldown=30.0,
            max_backoff=3600.0,
        ),
    )
    first = CeleryOutbox.objects.create(task_id='shutdown-1', task_name='some.task', retries=0, options={})
    second = CeleryOutbox.objects.create(task_id='shutdown-2', task_name='some.task', retries=0, options={})
    relay._policy.begin_shutdown(now_monotonic=0.0)

    with patch.object(relay._publisher, 'publish'):
        with patch('django_celery_outbox.relay._relay._logger') as m_logger:
            with patch(
                'django_celery_outbox.relay._relay.time.monotonic',
                side_effect=[0.0, 0.0, 0.0, 31.0, 31.0],
            ):
                with patch('django_celery_outbox.relay._relay.close_old_connections'):
                    with patch('django_celery_outbox.relay._relay.time.sleep'):
                        relay._processing()

    assert not CeleryOutbox.objects.filter(pk=first.id).exists()
    second.refresh_from_db()
    assert second.retries == 0
    assert second.retry_after is None
    assert second.updated_at is not None
    m_logger.warning.assert_any_call(
        'celery_outbox_relay_shutdown_deadline_exceeded',
        aborted_count=1,
        aborted_task_ids=['shutdown-2'],
        aborted_task_names=['some.task'],
    )
    m_logger.info.assert_any_call(
        'celery_outbox_batch_processed',
        published=1,
        failed=0,
        exceeded=0,
        deferred_due_to_outage=0,
        shutdown_aborted=1,
        queue_depth=1,
    )


def test_process_messages_empty_list(f_relay: Relay) -> None:
    published, failed, exceeded, deferred_due_to_outage, shutdown_aborted = f_relay._process_messages([])

    assert published == []
    assert failed == []
    assert exceeded == []
    assert deferred_due_to_outage == []
    assert shutdown_aborted == []


@pytest.mark.django_db
def test_processing_calls_close_old_connections(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(batch_size=10, idle_time=0.01, max_retries=3),
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
        with patch('django_celery_outbox.relay._relay.time.sleep'):
            with patch('django_celery_outbox.relay._relay.close_old_connections') as m_close:
                relay._processing()

    assert m_close.call_count == 2


@pytest.mark.django_db
def test_processing_sets_updated_at_on_select(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(batch_size=10, idle_time=0.01, max_retries=3),
    )

    msg = CeleryOutboxFactory.create(options={}, updated_at=None)
    before = datetime.now(timezone.utc)

    with patch('django_celery_outbox.relay._publisher.Celery.send_task', side_effect=RuntimeError('fail')):
        with patch('django_celery_outbox.relay._relay.time.sleep'):
            with patch('django_celery_outbox.relay._relay.close_old_connections'):
                relay._processing()

    msg.refresh_from_db()
    assert msg.updated_at is not None
    assert msg.updated_at >= before


def test_graceful_shutdown_stops_start_loop(m_celery_app: MagicMock) -> None:
    relay = _build_relay_for_start_tests(m_celery_app)
    relay._running = False

    with patch.object(relay, '_setup_signals'):
        with patch.object(relay, '_processing') as m_processing:
            relay.start()

    m_processing.assert_not_called()


def _build_relay_for_start_tests(m_celery_app: MagicMock) -> Relay:
    m_connection = MagicMock()
    m_connection.features.has_select_for_update_skip_locked = True

    with patch('django_celery_outbox.relay._relay.connections', {'default': m_connection}):
        with patch('django_celery_outbox.relay._relay.CeleryOutbox') as m_model:
            m_model.objects.db = 'default'
            return Relay(
                app=m_celery_app,
                config=RelayConfig.init(batch_size=10, idle_time=0.01, max_retries=3),
            )


def test_start_logs_and_continues_after_processing_exception(m_celery_app: MagicMock) -> None:
    relay = _build_relay_for_start_tests(m_celery_app)
    failure = RuntimeError('boom')
    processing_calls = 0

    def fake_processing() -> None:
        nonlocal processing_calls
        processing_calls += 1
        if processing_calls == 1:
            raise failure
        relay._running = False

    with patch.object(relay, '_setup_signals'):
        with patch.object(relay, '_setup_delayed_delivery'):
            with patch.object(relay, '_processing', side_effect=fake_processing) as m_processing:
                with patch('django_celery_outbox.relay._relay._logger') as m_logger:
                    with patch('django_celery_outbox.relay._relay.sentry_sdk.capture_exception') as m_capture_exception:
                        with patch('django_celery_outbox.relay._relay.should_log_traceback', return_value=False):
                            with patch('django_celery_outbox.relay._relay.time.sleep') as m_sleep:
                                relay.start()

    assert m_processing.call_count == 2
    m_logger.error.assert_called_once_with(
        'celery_outbox_relay_iteration_failed',
        exception_type='RuntimeError',
        exception_message='boom',
    )
    m_capture_exception.assert_called_once_with(failure)
    m_sleep.assert_called_once_with(0.01)


def test_start_does_not_sleep_after_processing_exception_when_stopped(m_celery_app: MagicMock) -> None:
    relay = _build_relay_for_start_tests(m_celery_app)
    failure = RuntimeError('boom')

    def fake_processing() -> None:
        relay._running = False
        raise failure

    with patch.object(relay, '_setup_signals'):
        with patch.object(relay, '_setup_delayed_delivery'):
            with patch.object(relay, '_processing', side_effect=fake_processing):
                with patch('django_celery_outbox.relay._relay._logger') as m_logger:
                    with patch('django_celery_outbox.relay._relay.sentry_sdk.capture_exception') as m_capture_exception:
                        with patch('django_celery_outbox.relay._relay.should_log_traceback', return_value=True):
                            with patch('django_celery_outbox.relay._relay.time.sleep') as m_sleep:
                                relay.start()

    m_logger.error.assert_called_once_with(
        'celery_outbox_relay_iteration_failed',
        exception_type='RuntimeError',
        exception_message='boom',
        exc_info=True,
    )
    m_capture_exception.assert_called_once_with(failure)
    m_sleep.assert_not_called()


def test_config_validation_batch_size_zero() -> None:
    with pytest.raises(ImproperlyConfigured, match='batch_size must be > 0'):
        RelayConfig.init(batch_size=0)


def test_config_validation_negative_idle_time() -> None:
    with pytest.raises(ImproperlyConfigured, match='idle_time must be >= 0'):
        RelayConfig.init(idle_time=-1.0)


def test_config_validation_zero_backoff_time() -> None:
    with pytest.raises(ImproperlyConfigured, match='backoff_time must be > 0'):
        RelayConfig.init(backoff_time=0)


def test_config_validation_zero_max_retries() -> None:
    with pytest.raises(ImproperlyConfigured, match='max_retries must be > 0'):
        RelayConfig.init(max_retries=0)


def test_config_validation_zero_stale_timeout_seconds() -> None:
    with pytest.raises(ImproperlyConfigured, match='stale_timeout_seconds must be > 0'):
        RelayConfig.init(stale_timeout_seconds=0)


def test_config_validation_zero_send_timeout() -> None:
    with pytest.raises(ImproperlyConfigured, match='send_timeout must be > 0 and finite'):
        RelayConfig.init(send_timeout=0)


def test_config_validation_zero_shutdown_timeout() -> None:
    with pytest.raises(ImproperlyConfigured, match='shutdown_timeout must be > 0 and finite'):
        RelayConfig.init(shutdown_timeout=0)


def test_config_validation_zero_broker_outage_cooldown() -> None:
    with pytest.raises(ImproperlyConfigured, match='broker_outage_cooldown must be > 0 and finite'):
        RelayConfig.init(broker_outage_cooldown=0)


def test_config_validation_zero_max_backoff() -> None:
    with pytest.raises(ImproperlyConfigured, match='max_backoff must be > 0 and finite'):
        RelayConfig.init(max_backoff=0)


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_config_validation_non_finite_send_timeout(value: float) -> None:
    with pytest.raises(ImproperlyConfigured, match='send_timeout must be > 0 and finite'):
        RelayConfig.init(send_timeout=value)


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_config_validation_non_finite_shutdown_timeout(value: float) -> None:
    with pytest.raises(ImproperlyConfigured, match='shutdown_timeout must be > 0 and finite'):
        RelayConfig.init(shutdown_timeout=value)


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_config_validation_non_finite_broker_outage_cooldown(value: float) -> None:
    with pytest.raises(ImproperlyConfigured, match='broker_outage_cooldown must be > 0 and finite'):
        RelayConfig.init(broker_outage_cooldown=value)


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_config_validation_non_finite_max_backoff(value: float) -> None:
    with pytest.raises(ImproperlyConfigured, match='max_backoff must be > 0 and finite'):
        RelayConfig.init(max_backoff=value)


@pytest.mark.django_db
def test_processing_logs_batch_summary(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(batch_size=10, idle_time=0.01, max_retries=3),
    )

    CeleryOutboxFactory.create(options={}, retries=0)

    with patch('django_celery_outbox.relay._relay._logger') as m_logger:
        with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
            with patch('django_celery_outbox.relay._relay.time.sleep'):
                with patch('django_celery_outbox.relay._relay.close_old_connections'):
                    relay._processing()

    m_logger.info.assert_any_call(
        'celery_outbox_batch_processed',
        published=1,
        failed=0,
        exceeded=0,
        deferred_due_to_outage=0,
        shutdown_aborted=0,
        queue_depth=0,
    )


def test_touch_liveness_creates_file(m_celery_app: MagicMock, tmp_path: object) -> None:
    liveness_file = f'{tmp_path}/alive'
    relay = Relay(app=m_celery_app, config=RelayConfig.init(liveness_file=liveness_file, max_retries=3))

    relay._touch_liveness()

    from pathlib import Path

    assert Path(liveness_file).exists()


def test_touch_liveness_noop_when_not_configured(m_celery_app: MagicMock) -> None:
    relay = Relay(app=m_celery_app, config=RelayConfig.init(max_retries=3))

    relay._touch_liveness()


@pytest.mark.django_db
def test_processing_touches_liveness_file(m_celery_app: MagicMock, tmp_path: object) -> None:
    liveness_file = f'{tmp_path}/alive'
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(batch_size=10, idle_time=0.01, max_retries=3, liveness_file=liveness_file),
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
        with patch('django_celery_outbox.relay._relay.time.sleep'):
            with patch('django_celery_outbox.relay._relay.close_old_connections'):
                relay._processing()

    from pathlib import Path

    assert Path(liveness_file).exists()


@pytest.mark.django_db
@patch('django_celery_outbox.relay._relay.sentry_sdk')
def test_processing_creates_batch_span(m_sentry: MagicMock, f_relay: Relay) -> None:
    m_batch_span = MagicMock()
    m_sentry.start_span.return_value.__enter__.return_value = m_batch_span

    with patch('django_celery_outbox.relay._relay.time.sleep'):
        with patch('django_celery_outbox.relay._relay.close_old_connections'):
            f_relay._processing()

    m_sentry.start_span.assert_called_with(
        op='queue.process',
        name='celery_outbox.relay.batch',
    )
    m_batch_span.set_status.assert_called_once_with('ok')


@pytest.mark.django_db
@patch('django_celery_outbox.relay._relay.sentry_sdk')
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

    with patch('django_celery_outbox.relay._publisher.Celery.send_task', side_effect=ConnectionError('broker down')):
        with patch('django_celery_outbox.relay._relay.time.sleep'):
            with patch('django_celery_outbox.relay._relay.close_old_connections'):
                f_relay._processing()

    m_batch_span.set_status.assert_called_with('internal_error')


@pytest.mark.django_db
@patch('django_celery_outbox.relay._relay.sentry_sdk')
def test_processing_batch_span_records_deferred_due_to_outage_on_breaker_trip(
    m_sentry: MagicMock,
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(
            batch_size=10,
            idle_time=0,
            backoff_time=120,
            max_retries=5,
            send_timeout=10.0,
            shutdown_timeout=30.0,
            broker_outage_cooldown=30.0,
            max_backoff=3600.0,
        ),
    )
    CeleryOutbox.objects.create(task_id='span-trip-1', task_name='some.task', retries=0, options={})
    CeleryOutbox.objects.create(task_id='span-trip-2', task_name='some.task', retries=0, options={})
    CeleryOutbox.objects.create(task_id='span-trip-3', task_name='some.task', retries=0, options={})

    m_batch_span = MagicMock()
    m_send_span1 = MagicMock()
    m_send_span2 = MagicMock()
    m_batch_ctx = MagicMock()
    m_batch_ctx.__enter__.return_value = m_batch_span
    m_batch_ctx.__exit__.return_value = None
    m_send_ctx1 = MagicMock()
    m_send_ctx1.__enter__.return_value = m_send_span1
    m_send_ctx1.__exit__.return_value = None
    m_send_ctx2 = MagicMock()
    m_send_ctx2.__enter__.return_value = m_send_span2
    m_send_ctx2.__exit__.return_value = None
    m_sentry.start_span.side_effect = [m_batch_ctx, m_send_ctx1, m_send_ctx2]

    with patch('django_celery_outbox.relay._publisher.Celery.send_task', side_effect=[TimeoutError('timed out'), TimeoutError('timed out again')]):
        with patch('django_celery_outbox.relay._relay.time.sleep'):
            with patch('django_celery_outbox.relay._relay.close_old_connections'):
                relay._processing()

    m_batch_span.set_data.assert_any_call('celery_outbox.deferred_due_to_outage', 3)
    m_batch_span.set_data.assert_any_call('celery_outbox.shutdown_aborted', 0)


@pytest.mark.django_db
@patch('django_celery_outbox.relay._relay.sentry_sdk')
def test_processing_batch_span_records_shutdown_aborted_on_shutdown_deadline(
    m_sentry: MagicMock,
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(
            batch_size=10,
            idle_time=0,
            backoff_time=120,
            max_retries=5,
            send_timeout=10.0,
            shutdown_timeout=30.0,
            broker_outage_cooldown=30.0,
            max_backoff=3600.0,
        ),
    )
    CeleryOutbox.objects.create(task_id='span-shutdown-1', task_name='some.task', retries=0, options={})
    CeleryOutbox.objects.create(task_id='span-shutdown-2', task_name='some.task', retries=0, options={})
    relay._policy.begin_shutdown(now_monotonic=0.0)

    m_batch_span = MagicMock()
    m_send_span = MagicMock()
    m_batch_ctx = MagicMock()
    m_batch_ctx.__enter__.return_value = m_batch_span
    m_batch_ctx.__exit__.return_value = None
    m_send_ctx = MagicMock()
    m_send_ctx.__enter__.return_value = m_send_span
    m_send_ctx.__exit__.return_value = None
    m_sentry.start_span.side_effect = [m_batch_ctx, m_send_ctx]

    with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
        with patch(
            'django_celery_outbox.relay._relay.time.monotonic',
            side_effect=[0.0, 0.0, 0.0, 31.0, 31.0],
        ):
            with patch('django_celery_outbox.relay._relay.time.sleep'):
                with patch('django_celery_outbox.relay._relay.close_old_connections'):
                    relay._processing()

    m_batch_span.set_data.assert_any_call('celery_outbox.deferred_due_to_outage', 0)
    m_batch_span.set_data.assert_any_call('celery_outbox.shutdown_aborted', 1)


@pytest.mark.django_db
@patch('django_celery_outbox.relay._relay.sentry_sdk')
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

    with patch.object(f_relay._publisher, 'publish'):
        f_relay._process_messages([msg])

    m_sentry.start_span.assert_called_with(
        op='celery_outbox.relay.send',
        name='my.task',
    )
    m_span.set_data.assert_any_call('messaging.message.id', 'msg-123')
    m_span.set_data.assert_any_call('messaging.message.retry.count', 0)
    m_span.set_status.assert_called_once_with('ok')


@pytest.mark.django_db
@patch('django_celery_outbox.relay._relay.sentry_sdk')
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

    with patch.object(f_relay._publisher, 'publish', side_effect=ConnectionError('down')):
        f_relay._process_messages([msg])

    m_span.set_status.assert_called_once_with('internal_error')


def test_relay_init_raises_when_skip_locked_not_supported(m_celery_app: MagicMock) -> None:
    m_connection = MagicMock()
    m_connection.features.has_select_for_update_skip_locked = False
    m_connection.vendor = 'sqlite'

    with patch('django_celery_outbox.relay._relay.connections', {'default': m_connection}):
        with patch('django_celery_outbox.relay._relay.CeleryOutbox') as m_model:
            m_model.objects.db = 'default'

            with pytest.raises(RuntimeError, match='does not support SELECT FOR UPDATE SKIP LOCKED'):
                Relay(app=m_celery_app, config=RelayConfig.init(max_retries=3))


def test_relay_init_accepts_when_skip_locked_supported(m_celery_app: MagicMock) -> None:
    m_connection = MagicMock()
    m_connection.features.has_select_for_update_skip_locked = True

    with patch('django_celery_outbox.relay._relay.connections', {'default': m_connection}):
        with patch('django_celery_outbox.relay._relay.CeleryOutbox') as m_model:
            m_model.objects.db = 'default'
            relay = Relay(app=m_celery_app, config=RelayConfig.init(max_retries=3))

    assert relay is not None
    assert isinstance(relay._publisher, RelayPublisher)
    assert isinstance(relay._mutations, RelayMutations)


@pytest.mark.django_db
def test_select_messages_skips_future_versions(f_message_selector: MessageSelector) -> None:
    msg_v1 = CeleryOutbox.objects.create(
        task_id='task-v1',
        task_name='app.task',
        schema_version=1,
    )
    CeleryOutbox.objects.create(
        task_id='task-v2',
        task_name='app.task',
        schema_version=2,
    )

    messages = f_message_selector.run()

    assert len(messages) == 1
    assert messages[0].id == msg_v1.id


@pytest.mark.django_db
def test_select_messages_skips_deprecated_versions(f_message_selector: MessageSelector) -> None:
    CeleryOutbox.objects.create(
        task_id='task-v0',
        task_name='app.task',
        schema_version=0,
    )
    msg_v1 = CeleryOutbox.objects.create(
        task_id='task-v1',
        task_name='app.task',
        schema_version=1,
    )

    messages = f_message_selector.run()

    assert len(messages) == 1
    assert messages[0].id == msg_v1.id


@pytest.mark.django_db
def test_failed_message_includes_exception_type_in_metrics(
    f_relay: Relay,
    m_metrics: MagicMock,
) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=0,
    )

    with patch.object(f_relay._publisher, 'publish', side_effect=ConnectionError('broker down')):
        f_relay._process_messages([msg])

    m_metrics.increment.assert_any_call(
        'messages.failed',
        tags={'task_name': msg.task_name, 'exception_type': 'connection'},
    )


@pytest.mark.django_db
def test_exceeded_message_includes_exception_type_in_metrics(
    f_relay: Relay,
    m_metrics: MagicMock,
) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=f_relay._config.max_retries - 1,
    )

    with patch.object(f_relay._publisher, 'publish', side_effect=ConnectionError('broker down')):
        f_relay._process_messages([msg])

    m_metrics.increment.assert_any_call(
        'messages.exceeded',
        tags={'task_name': msg.task_name, 'exception_type': 'connection'},
    )


@pytest.mark.django_db
def test_broker_outage_at_max_retries_does_not_increment_failed_or_exceeded_metrics(
    f_relay: Relay,
    m_metrics: MagicMock,
) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=f_relay._config.max_retries - 1,
    )

    with patch.object(f_relay._publisher, 'publish', side_effect=TimeoutError('timeout')):
        published, failed, exceeded, deferred_due_to_outage, shutdown_aborted = f_relay._process_messages([msg])

    assert published == []
    assert failed == []
    assert exceeded == []
    assert deferred_due_to_outage == [msg.id]
    assert shutdown_aborted == []
    metric_names = [c[0][0] for c in m_metrics.increment.call_args_list]
    assert 'messages.failed' not in metric_names
    assert 'messages.exceeded' not in metric_names


@pytest.mark.django_db
def test_published_message_uses_cardinality_control(
    f_relay: Relay,
    m_metrics: MagicMock,
) -> None:
    with override_settings(CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS=True):
        CeleryOutbox.objects.create(
            task_id='task-1',
            task_name='some.task',
            args=[],
            kwargs={},
            options={},
        )
        with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
            with patch('django_celery_outbox.relay._relay.time.sleep'):
                with patch('django_celery_outbox.relay._relay.close_old_connections'):
                    f_relay._processing()

    published_calls = [c for c in m_metrics.increment.call_args_list if c[0][0] == 'messages.published']
    assert len(published_calls) == 1
    assert published_calls[0][1].get('tags', {}) == {}


@pytest.mark.django_db
def test_exceeded_pre_send_uses_cardinality_control(
    f_relay: Relay,
    m_metrics: MagicMock,
) -> None:
    with override_settings(CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS=True):
        msg = CeleryOutbox.objects.create(
            task_id='task-1',
            task_name='some.task',
            retries=f_relay._config.max_retries,
        )

        with patch.object(f_relay._publisher, 'publish') as m_publish:
            f_relay._process_messages([msg])

    exceeded_calls = [c for c in m_metrics.increment.call_args_list if c[0][0] == 'messages.exceeded']
    assert len(exceeded_calls) == 1
    tags = exceeded_calls[0][1].get('tags', {})
    assert 'task_name' not in tags
    assert tags.get('exception_type') == 'pre_exceeded'
    m_publish.assert_not_called()


@pytest.mark.django_db
def test_oldest_pending_age_seconds_emitted(
    f_relay: Relay,
    m_metrics: MagicMock,
) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='test-id',
        task_name='test.task',
        args=[],
        kwargs={},
        options={},
        updated_at=None,
        retry_after=None,
    )
    CeleryOutbox.objects.filter(pk=msg.pk).update(
        created_at=django_timezone.now() - timedelta(seconds=60),
    )

    with patch.object(f_relay._selector, 'run', return_value=[]):
        with patch('django_celery_outbox.relay._relay.time.sleep'):
            with patch('django_celery_outbox.relay._relay.close_old_connections'):
                f_relay._processing()

    gauge_calls = [c for c in m_metrics.gauge.call_args_list if c[0][0] == 'oldest_pending_age_seconds']
    assert len(gauge_calls) == 1
    assert 55 < gauge_calls[0][0][1] < 65


@pytest.mark.django_db
def test_oldest_pending_age_seconds_zero_when_empty(
    f_relay: Relay,
    m_metrics: MagicMock,
) -> None:
    with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
        with patch('django_celery_outbox.relay._relay.time.sleep'):
            with patch('django_celery_outbox.relay._relay.close_old_connections'):
                f_relay._processing()

    gauge_calls = [c for c in m_metrics.gauge.call_args_list if c[0][0] == 'oldest_pending_age_seconds']
    assert len(gauge_calls) == 1
    assert gauge_calls[0][0][1] == 0


@pytest.mark.django_db
def test_exception_logging_includes_traceback_by_default(
    f_relay: Relay,
    m_metrics: MagicMock,
) -> None:
    CeleryOutbox.objects.create(
        task_id='test-id',
        task_name='test.task',
        args=[],
        kwargs={},
        options={},
    )

    with override_settings(CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK=True):
        with patch.object(f_relay._publisher, 'publish', side_effect=ValueError('test error')):
            with patch('django_celery_outbox.relay._relay._logger') as m_logger:
                f_relay._process_messages(list(CeleryOutbox.objects.all()))

                error_calls = [c for c in m_logger.error.call_args_list if c[0][0] == 'celery_outbox_send_failed']
                assert len(error_calls) == 1
                assert error_calls[0][1].get('exc_info') is True


@pytest.mark.django_db
def test_exception_logging_excludes_traceback_when_disabled(
    f_relay: Relay,
    m_metrics: MagicMock,
) -> None:
    CeleryOutbox.objects.create(
        task_id='test-id',
        task_name='test.task',
        args=[],
        kwargs={},
        options={},
    )

    with override_settings(CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK=False):
        with patch.object(f_relay._publisher, 'publish', side_effect=ValueError('test error')):
            with patch('django_celery_outbox.relay._relay._logger') as m_logger:
                f_relay._process_messages(list(CeleryOutbox.objects.all()))

                error_calls = [c for c in m_logger.error.call_args_list if c[0][0] == 'celery_outbox_send_failed']
                assert len(error_calls) == 1
                assert 'exc_info' not in error_calls[0][1]
                assert error_calls[0][1]['exception_type'] == 'unknown'
                assert error_calls[0][1]['exception_message'] == 'test error'


@pytest.mark.django_db
def test_send_latency_ms_emitted_on_success(
    f_relay: Relay,
    m_metrics: MagicMock,
) -> None:
    msg = CeleryOutbox.objects.create(
        task_id='test-id',
        task_name='test.task',
        args=[],
        kwargs={},
        options={},
    )
    CeleryOutbox.objects.filter(pk=msg.pk).update(
        created_at=django_timezone.now() - timedelta(seconds=2),
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
        with patch('django_celery_outbox.relay._relay.time.sleep'):
            with patch('django_celery_outbox.relay._relay.close_old_connections'):
                f_relay._processing()

    timing_calls = [c for c in m_metrics.timing.call_args_list if c[0][0] == 'send_latency_ms']
    assert len(timing_calls) == 1
    assert 1900 < timing_calls[0][0][1] < 2500


def test_setup_delayed_delivery_calls_declare(f_relay: Relay) -> None:
    m_connection = MagicMock()
    m_context = MagicMock()
    m_context.__enter__ = MagicMock(return_value=m_connection)
    m_context.__exit__ = MagicMock(return_value=None)
    f_relay._app.connection_for_write.return_value = m_context
    f_relay._app.conf.broker_native_delayed_delivery_queue_type = 'quorum'

    with patch('django_celery_outbox.relay._relay.declare_native_delayed_delivery_exchanges_and_queues') as m_declare:
        f_relay._setup_delayed_delivery()

    m_declare.assert_called_once_with(m_connection, 'quorum')


def test_setup_delayed_delivery_uses_quorum_as_default(f_relay: Relay) -> None:
    m_connection = MagicMock()
    m_context = MagicMock()
    m_context.__enter__ = MagicMock(return_value=m_connection)
    m_context.__exit__ = MagicMock(return_value=None)
    f_relay._app.connection_for_write.return_value = m_context
    f_relay._app.conf.broker_native_delayed_delivery_queue_type = None

    with patch('django_celery_outbox.relay._relay.declare_native_delayed_delivery_exchanges_and_queues') as m_declare:
        f_relay._setup_delayed_delivery()

    m_declare.assert_called_once_with(m_connection, 'quorum')


def test_setup_delayed_delivery_logs_warning_on_failure(f_relay: Relay) -> None:
    f_relay._app.connection_for_write.side_effect = ConnectionError('broker down')

    with patch('django_celery_outbox.relay._relay._logger') as m_logger:
        f_relay._setup_delayed_delivery()

    m_logger.warning.assert_called_once()
    assert m_logger.warning.call_args[0][0] == 'celery_outbox_delayed_delivery_setup_failed'
