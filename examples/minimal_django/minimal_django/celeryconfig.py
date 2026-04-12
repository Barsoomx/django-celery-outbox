import os

from kombu import Exchange, Queue

broker_url = os.environ.get('CELERY_BROKER_URL', 'amqp://guest:guest@localhost:5672//')
result_backend = None
task_always_eager = False

broker_transport_options = {
    'confirm_publish': True,
}
broker_native_delayed_delivery_queue_type = 'quorum'
worker_detect_quorum_queues = True

task_default_queue = 'minimal-default'
task_default_exchange = task_default_queue
task_default_exchange_type = 'topic'
task_default_routing_key = task_default_queue
task_default_queue_type = 'quorum'
task_create_missing_queues = False
task_queues = (
    Queue(
        'minimal-default',
        Exchange('minimal-default', type='topic'),
        routing_key='minimal-default',
        queue_arguments={'x-queue-type': 'quorum'},
    ),
    Queue(
        'minimal-batch',
        Exchange('minimal-batch', type='topic'),
        routing_key='minimal-batch',
        queue_arguments={'x-queue-type': 'quorum'},
    ),
)
