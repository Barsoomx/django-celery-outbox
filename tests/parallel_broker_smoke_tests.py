import os
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

    app = OutboxCelery('parallel-smoke')
    app.conf.broker_url = broker_url
    app.conf.task_default_queue = queue_name
    app.conf.task_default_exchange = queue_name
    app.conf.task_default_routing_key = queue_name

    app.send_task('smoke.task', task_id='parallel-smoke-1')

    relay = Relay(
        app=app,
        config=RelayConfig.init(batch_size=1, idle_time=0, max_retries=1, publish_concurrency=2),
    )
    relay._processing()

    with Connection(broker_url) as connection:
        queue = connection.SimpleQueue(queue_name)
        message = queue.get(timeout=10)
        try:
            assert message.headers['id'] == 'parallel-smoke-1'
        finally:
            message.ack()
            queue.close()
