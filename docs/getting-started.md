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

### 2. Replace Celery app

In your `myproject/celery.py`:

```python
from django_celery_outbox import OutboxCelery

app = OutboxCelery('myproject')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

### 3. Configure outbox app path

In your Django settings:

```python
CELERY_OUTBOX_APP = 'myproject.celery.app'
```

### 4. Run migrations

```bash
python manage.py migrate
```

### 5. Start the relay

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
