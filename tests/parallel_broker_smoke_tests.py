import os
from unittest.mock import patch
from uuid import uuid4

import pytest
from kombu import Connection

from django_celery_outbox import OutboxCelery
from django_celery_outbox.relay import Relay, RelayConfig

pytestmark = pytest.mark.live_broker_smoke


@pytest.mark.django_db(transaction=True)
def test_parallel_publish_smoke_to_live_rabbitmq() -> None:
    broker_url = os.environ['CELERY_BROKER_URL']
    queue_name = f'parallel-smoke-{uuid4().hex}'
    task_ids = ['parallel-smoke-1', 'parallel-smoke-2', 'parallel-smoke-3', 'parallel-smoke-4']

    app = OutboxCelery('parallel-smoke')
    app.conf.broker_url = broker_url
    app.conf.task_default_queue = queue_name
    app.conf.task_default_exchange = queue_name
    app.conf.task_default_routing_key = queue_name

    for task_id in task_ids:
        app.send_task('smoke.task', task_id=task_id)

    relay = Relay(
        app=app,
        config=RelayConfig.init(batch_size=4, idle_time=0, max_retries=1, publish_concurrency=2),
    )
    with patch.object(relay, '_process_messages_parallel', wraps=relay._process_messages_parallel) as m_parallel:
        with patch.object(relay, '_process_messages_serial', wraps=relay._process_messages_serial) as m_serial:
            relay._processing()

    m_parallel.assert_called_once()
    m_serial.assert_not_called()

    with Connection(broker_url) as connection:
        queue = connection.SimpleQueue(queue_name)
        messages = [queue.get(timeout=10) for _ in task_ids]
        try:
            assert {message.headers['id'] for message in messages} == set(task_ids)
        finally:
            for message in messages:
                message.ack()
            queue.close()
