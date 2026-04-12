# Getting Started

## Requirements

- Python 3.10+
- Django 4.2+
- Celery 5.3+
- PostgreSQL 9.5+ or MySQL 8.0.1+

!!! warning "SQLite Not Supported"
    django-celery-outbox requires `SELECT FOR UPDATE SKIP LOCKED`, which SQLite does not support.

## Installation

```bash
pip install django-celery-outbox
```

## Configuration

### 1. Add to INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    'django_celery_outbox',
]
```

### 2. Add Celery config

In `myproject/celeryconfig.py`:

```python
from kombu import Exchange, Queue

broker_transport_options = {
    'confirm_publish': True,
}
broker_native_delayed_delivery_queue_type = 'quorum'
worker_detect_quorum_queues = True

task_default_queue = 'myproject-default'
task_default_exchange = task_default_queue
task_default_exchange_type = 'topic'
task_default_routing_key = task_default_queue
task_default_queue_type = 'quorum'
task_create_missing_queues = False
task_queues = (
    Queue(
        'myproject-default',
        Exchange('myproject-default', type='topic'),
        routing_key='myproject-default',
        queue_arguments={'x-queue-type': 'quorum'},
    ),
)
```

### 3. Create Celery app bootstrap

In `myproject/celery_app.py`:

```python
import os

from django_celery_outbox import OutboxCelery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

app = OutboxCelery('myproject')
app.config_from_object('myproject.celeryconfig')
app.autodiscover_tasks()
```

### 4. Export the app from your package

In `myproject/__init__.py`:

```python
from myproject.celery_app import app as celery_app

__all__ = ('celery_app',)
```

### 5. Configure outbox app path

In your Django settings:

```python
CELERY_OUTBOX_APP = 'myproject.celery_app.app'
```

### 6. Run migrations

```bash
python manage.py migrate
```

### 7. Start the relay

```bash
python manage.py celery_outbox_relay
```

## Verify It Works

Create an order (or any model) within a transaction:

```python
from django.db import transaction

with transaction.atomic():
    order = Order.objects.create(...)
    send_confirmation_email.delay(order.id)
```

Check the outbox table:

```bash
python manage.py celery_outbox_stats
```

Watch the relay pick it up:

```bash
python manage.py celery_outbox_relay --batch-size 10
```
