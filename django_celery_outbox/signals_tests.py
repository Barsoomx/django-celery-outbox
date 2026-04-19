from unittest.mock import MagicMock, patch

import pytest
from celery import Celery
from django.db import connections

from django_celery_outbox.factories import CeleryOutboxFactory
from django_celery_outbox.models import CeleryOutbox
from django_celery_outbox.relay import Relay, RelayConfig
from django_celery_outbox.signals import (
    outbox_message_created,
    outbox_message_dead_lettered,
    outbox_message_failed,
    outbox_message_sent,
)


@pytest.fixture()
def m_celery_app() -> MagicMock:
    app = MagicMock(spec=Celery)
    app.send_task = MagicMock()
    return app


def _enable_relay_for_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = connections[CeleryOutbox.objects.db]
    monkeypatch.setattr(connection.features, 'has_select_for_update_skip_locked', True, raising=False)


@pytest.fixture()
def f_relay(m_celery_app: MagicMock, monkeypatch: pytest.MonkeyPatch) -> Relay:
    _enable_relay_for_sqlite(monkeypatch)
    config = RelayConfig.init(
        batch_size=10,
        idle_time=0.01,
        backoff_time=120,
        max_retries=3,
    )
    return Relay(
        app=m_celery_app,
        config=config,
    )


@pytest.mark.django_db
def test_outbox_message_created_fires_on_send_task() -> None:
    from django_celery_outbox.app import OutboxCelery

    app = OutboxCelery('test')
    received = []

    def handler(sender: type, **kwargs: object) -> None:
        received.append(kwargs)

    outbox_message_created.connect(handler)
    try:
        app.send_task('my.task', task_id='test-id-1')
    finally:
        outbox_message_created.disconnect(handler)

    assert len(received) == 1
    assert received[0]['task_id'] == 'test-id-1'
    assert received[0]['task_name'] == 'my.task'


@pytest.mark.django_db
def test_outbox_message_sent_fires_on_successful_relay(f_relay: Relay) -> None:
    msg = CeleryOutboxFactory.create(
        task_id='sent-task-1',
        task_name='some.task',
        options={},
        retries=0,
    )

    received = []

    def handler(sender: type, **kwargs: object) -> None:
        received.append(kwargs)

    outbox_message_sent.connect(handler)
    try:
        with patch.object(f_relay._publisher, 'publish'):
            f_relay._process_messages([msg])
    finally:
        outbox_message_sent.disconnect(handler)

    assert len(received) == 1
    assert received[0]['task_id'] == 'sent-task-1'
    assert received[0]['task_name'] == 'some.task'


@pytest.mark.django_db
def test_outbox_message_failed_fires_on_relay_failure(f_relay: Relay) -> None:
    msg = CeleryOutboxFactory.create(
        task_id='fail-task-1',
        task_name='some.task',
        options={},
        retries=0,
    )

    received = []

    def handler(sender: type, **kwargs: object) -> None:
        received.append(kwargs)

    outbox_message_failed.connect(handler)
    try:
        with patch.object(f_relay._publisher, 'publish', side_effect=RuntimeError('broker down')):
            f_relay._process_messages([msg])
    finally:
        outbox_message_failed.disconnect(handler)

    assert len(received) == 1
    assert received[0]['task_id'] == 'fail-task-1'
    assert received[0]['task_name'] == 'some.task'
    assert received[0]['retries'] == 0


@pytest.mark.django_db
def test_outbox_message_dead_lettered_fires_on_exceeded(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(batch_size=10, idle_time=0.01, backoff_time=120, max_retries=3),
    )
    CeleryOutboxFactory.create(
        task_id='dead-task-1',
        task_name='some.dead_task',
        options={},
        retries=3,
    )

    received = []

    def handler(sender: type, **kwargs: object) -> None:
        received.append(kwargs)

    outbox_message_dead_lettered.connect(handler)
    try:
        with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
            with patch('django_celery_outbox.relay._relay.time.sleep'):
                with patch('django_celery_outbox.relay._relay.close_old_connections'):
                    relay._processing()
    finally:
        outbox_message_dead_lettered.disconnect(handler)

    assert len(received) == 1
    assert 'dead-task-1' in received[0]['task_ids']  # type: ignore[operator]
    assert 'some.dead_task' in received[0]['task_names']  # type: ignore[operator]


@pytest.mark.django_db
def test_outbox_message_failed_not_fired_when_max_retries_exceeded(f_relay: Relay) -> None:
    msg = CeleryOutboxFactory.create(
        task_id='exceed-task-1',
        task_name='some.task',
        options={},
        retries=2,
    )

    received = []

    def handler(sender: type, **kwargs: object) -> None:
        received.append(kwargs)

    outbox_message_failed.connect(handler)
    try:
        with patch.object(f_relay._publisher, 'publish', side_effect=RuntimeError('fail')):
            f_relay._process_messages([msg])
    finally:
        outbox_message_failed.disconnect(handler)

    assert len(received) == 0


@pytest.mark.django_db
def test_outbox_message_failed_not_fired_on_broker_outage_deferral(f_relay: Relay) -> None:
    msg1 = CeleryOutboxFactory.create(
        task_id='outage-signal-1',
        task_name='some.task',
        options={},
        retries=0,
    )
    msg2 = CeleryOutboxFactory.create(
        task_id='outage-signal-2',
        task_name='some.task',
        options={},
        retries=0,
    )

    received = []

    def handler(sender: type, **kwargs: object) -> None:
        received.append(kwargs)

    outbox_message_failed.connect(handler)
    try:
        with patch.object(
            f_relay._publisher,
            'publish',
            side_effect=[TimeoutError('timed out'), TimeoutError('timed out again')],
        ):
            f_relay._process_messages([msg1, msg2])
    finally:
        outbox_message_failed.disconnect(handler)

    assert received == []


@pytest.mark.django_db
def test_shutdown_deadline_aborted_rows_emit_no_relay_signals(f_relay: Relay) -> None:
    CeleryOutboxFactory.create(
        task_id='shutdown-signal-1',
        task_name='some.task',
        options={},
        retries=0,
    )
    CeleryOutboxFactory.create(
        task_id='shutdown-signal-2',
        task_name='some.task',
        options={},
        retries=0,
    )

    sent_received = []
    failed_received = []
    dead_lettered_received = []

    def sent_handler(sender: type, **kwargs: object) -> None:
        sent_received.append(kwargs)

    def failed_handler(sender: type, **kwargs: object) -> None:
        failed_received.append(kwargs)

    def dead_lettered_handler(sender: type, **kwargs: object) -> None:
        dead_lettered_received.append(kwargs)

    f_relay._policy.begin_shutdown(now_monotonic=0.0)

    outbox_message_sent.connect(sent_handler)
    outbox_message_failed.connect(failed_handler)
    outbox_message_dead_lettered.connect(dead_lettered_handler)
    try:
        with patch.object(f_relay._publisher, 'publish'):
            with patch(
                'django_celery_outbox.relay._relay.time.monotonic',
                side_effect=[0.0, 0.0, 0.0, 31.0, 31.0],
            ):
                with patch('django_celery_outbox.relay._relay.close_old_connections'):
                    with patch('django_celery_outbox.relay._relay.time.sleep'):
                        f_relay._processing()
    finally:
        outbox_message_sent.disconnect(sent_handler)
        outbox_message_failed.disconnect(failed_handler)
        outbox_message_dead_lettered.disconnect(dead_lettered_handler)

    assert [item['task_id'] for item in sent_received] == ['shutdown-signal-1']
    assert failed_received == []
    assert dead_lettered_received == []


@pytest.mark.django_db
def test_outbox_message_sent_not_fired_on_failure(f_relay: Relay) -> None:
    msg = CeleryOutboxFactory.create(
        task_id='no-sent-task',
        task_name='some.task',
        options={},
        retries=0,
    )

    received = []

    def handler(sender: type, **kwargs: object) -> None:
        received.append(kwargs)

    outbox_message_sent.connect(handler)
    try:
        with patch.object(f_relay._publisher, 'publish', side_effect=RuntimeError('fail')):
            f_relay._process_messages([msg])
    finally:
        outbox_message_sent.disconnect(handler)

    assert len(received) == 0
