from unittest.mock import MagicMock, patch

import pytest
from celery import Celery

from django_celery_outbox.factories import CeleryOutboxFactory
from django_celery_outbox.relay import Relay
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
        with patch.object(f_relay, '_send_task'):
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
        with patch.object(f_relay, '_send_task', side_effect=RuntimeError('broker down')):
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
        batch_size=10,
        idle_time=0.01,
        backoff_time=120,
        max_retries=3,
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
        with patch('django_celery_outbox.relay.Celery.send_task'):
            with patch('django_celery_outbox.relay.time.sleep'):
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
        with patch.object(f_relay, '_send_task', side_effect=RuntimeError('fail')):
            f_relay._process_messages([msg])
    finally:
        outbox_message_failed.disconnect(handler)

    assert len(received) == 0


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
        with patch.object(f_relay, '_send_task', side_effect=RuntimeError('fail')):
            f_relay._process_messages([msg])
    finally:
        outbox_message_sent.disconnect(handler)

    assert len(received) == 0
