# Documentation & Example Project Design

**Date:** 2026-04-12
**Issues:** #32
**Status:** Draft

## Overview

This spec covers the documentation site and example project for django-celery-outbox:

- mkdocs-material docs site deployed to GitHub Pages
- Full documentation structure (~18 pages)
- Realistic example project with Order processing scenario
- Docker Compose with PostgreSQL + RabbitMQ

**Note:** Current README.md (446 lines) and ARCHITECTURE.md (38KB) remain as-is until mkdocs site is fully populated. Content will be migrated incrementally.

## New Structure

```
django-celery-outbox/
├── docs/                          # mkdocs source
│   ├── index.md
│   ├── getting-started.md
│   ├── concepts.md
│   ├── configuration.md
│   ├── usage/
│   │   ├── basic-tasks.md
│   │   ├── task-options.md
│   │   ├── excluded-tasks.md
│   │   └── outside-transactions.md
│   ├── relay/
│   │   ├── overview.md
│   │   ├── command-reference.md
│   │   ├── tuning.md
│   │   └── multiple-instances.md
│   ├── observability/             # From Spec #1
│   │   ├── logging-events.md
│   │   ├── metrics.md
│   │   ├── structlog.md
│   │   ├── sentry.md
│   │   └── grafana-dashboard.json
│   ├── operations/
│   │   ├── dead-letter.md
│   │   ├── admin-interface.md
│   │   └── health-checks.md
│   ├── deployment/
│   │   ├── kubernetes.md
│   │   └── database-setup.md
│   ├── security.md                # From Spec #1
│   ├── troubleshooting.md
│   └── architecture.md            # Migrated from ARCHITECTURE.md
├── examples/
│   └── minimal_django/
│       ├── README.md
│       ├── docker-compose.yml
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── manage.py
│       ├── minimal_django/
│       │   ├── __init__.py
│       │   ├── settings.py
│       │   ├── celery.py
│       │   ├── urls.py
│       │   └── wsgi.py
│       └── orders/
│           ├── __init__.py
│           ├── models.py
│           ├── views.py
│           ├── tasks.py
│           └── admin.py
├── mkdocs.yml
└── README.md                      # Updated with docs link
```

## mkdocs Configuration

### mkdocs.yml

```yaml
site_name: django-celery-outbox
site_description: Transactional Outbox pattern for Celery tasks in Django
site_url: https://barsoomx.github.io/django-celery-outbox/
repo_url: https://github.com/Barsoomx/django-celery-outbox
repo_name: Barsoomx/django-celery-outbox
edit_uri: edit/master/docs/

theme:
  name: material
  features:
    - navigation.instant
    - navigation.tabs
    - navigation.sections
    - navigation.expand
    - navigation.top
    - toc.follow
    - content.code.copy
    - content.code.select
  palette:
    - scheme: default
      primary: blue
      accent: blue

markdown_extensions:
  - admonition
  - pymdownx.details
  - pymdownx.superfences
  - pymdownx.highlight:
      use_pygments: true
      anchor_linenums: true
  - pymdownx.tabbed:
      alternate_style: true
  - tables
  - toc:
      permalink: true

nav:
  - Home: index.md
  - Getting Started: getting-started.md
  - Concepts: concepts.md
  - Configuration: configuration.md
  - Usage:
    - Basic Tasks: usage/basic-tasks.md
    - Task Options: usage/task-options.md
    - Excluded Tasks: usage/excluded-tasks.md
    - Outside Transactions: usage/outside-transactions.md
  - Relay:
    - Overview: relay/overview.md
    - Command Reference: relay/command-reference.md
    - Tuning: relay/tuning.md
    - Multiple Instances: relay/multiple-instances.md
  - Observability:
    - Logging Events: observability/logging-events.md
    - Metrics: observability/metrics.md
    - Structlog: observability/structlog.md
    - Sentry: observability/sentry.md
  - Operations:
    - Dead Letter Queue: operations/dead-letter.md
    - Admin Interface: operations/admin-interface.md
    - Health Checks: operations/health-checks.md
  - Deployment:
    - Kubernetes: deployment/kubernetes.md
    - Database Setup: deployment/database-setup.md
  - Security: security.md
  - Troubleshooting: troubleshooting.md
  - Architecture: architecture.md

extra:
  social:
    - icon: fontawesome/brands/github
      link: https://github.com/Barsoomx/django-celery-outbox
```

### pyproject.toml additions

```toml
[project.optional-dependencies]
docs = [
    "mkdocs>=1.5",
    "mkdocs-material>=9.5",
]
```

### GitHub Actions for docs deployment

```yaml
# .github/workflows/docs.yml
name: Deploy Docs

on:
  push:
    branches: [master]
    paths: ['docs/**', 'mkdocs.yml']

permissions:
  contents: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install mkdocs-material
      - run: mkdocs gh-deploy --force
```

## Example Project

### docker-compose.yml

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
    environment:
      DEBUG: "True"
      DATABASE_URL: postgres://postgres:postgres@postgres:5432/minimal_django
      CELERY_BROKER_URL: amqp://guest:guest@rabbitmq:5672//
    volumes:
      - .:/app
    command: >
      sh -c "python manage.py migrate &&
             python manage.py runserver 0.0.0.0:8000"

  relay:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
    environment:
      DATABASE_URL: postgres://postgres:postgres@postgres:5432/minimal_django
      CELERY_BROKER_URL: amqp://guest:guest@rabbitmq:5672//
    volumes:
      - .:/app
    command: python manage.py celery_outbox_relay --batch-size 10 --idle-time 1.0

  worker:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
    environment:
      DATABASE_URL: postgres://postgres:postgres@postgres:5432/minimal_django
      CELERY_BROKER_URL: amqp://guest:guest@rabbitmq:5672//
    volumes:
      - .:/app
    command: celery -A minimal_django worker -l info

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: minimal_django
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U postgres']
      interval: 5s
      timeout: 5s
      retries: 5
    volumes:
      - postgres_data:/var/lib/postgresql/data

  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    ports:
      - "15672:15672"  # Management UI
    healthcheck:
      test: ['CMD', 'rabbitmq-diagnostics', 'check_running']
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
```

### requirements.txt

```
Django>=4.2,<5.3
celery>=5.3,<5.7
psycopg[binary]>=3.1
django-celery-outbox @ file:../..
```

### minimal_django/celery.py

```python
import os

from django_celery_outbox import OutboxCelery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'minimal_django.settings')

app = OutboxCelery('minimal_django')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

### minimal_django/settings.py (key parts)

```python
import os

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_celery_outbox',
    'orders',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'minimal_django',
        'USER': 'postgres',
        'PASSWORD': 'postgres',
        'HOST': os.environ.get('DB_HOST', 'postgres'),
        'PORT': '5432',
    }
}

# Celery
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'amqp://guest:guest@localhost:5672//')
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = False

# RabbitMQ publisher confirms (recommended for outbox)
CELERY_BROKER_TRANSPORT_OPTIONS = {
    'confirm_publish': True,
}

# Outbox
CELERY_OUTBOX_APP = 'minimal_django.celery.app'
CELERY_OUTBOX_EXCLUDE_TASKS = set()
CELERY_OUTBOX_STRUCTLOG_ENABLED = False  # Keep example simple
```

## Orders App (Realistic Example)

### orders/models.py

```python
from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CONFIRMED = 'confirmed', 'Confirmed'
        SHIPPED = 'shipped', 'Shipped'

    customer_email = models.EmailField()
    total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Order #{self.pk} - {self.customer_email}'
```

### orders/tasks.py

```python
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def send_order_confirmation(order_id: int, email: str):
    """Send confirmation email to customer."""
    logger.info('Sending confirmation email for order %s to %s', order_id, email)
    return {'order_id': order_id, 'email': email, 'status': 'sent'}


@shared_task
def notify_warehouse(order_id: int):
    """Notify warehouse to prepare shipment."""
    logger.info('Notifying warehouse about order %s', order_id)
    return {'order_id': order_id, 'status': 'notified'}


@shared_task
def schedule_shipping_reminder(order_id: int):
    """Remind customer about shipping (delayed task demo)."""
    logger.info('Sending shipping reminder for order %s', order_id)
    return {'order_id': order_id, 'status': 'reminded'}
```

### orders/views.py

```python
import json

from django.db import transaction
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from orders.models import Order
from orders.tasks import send_order_confirmation, notify_warehouse, schedule_shipping_reminder


@method_decorator(csrf_exempt, name='dispatch')
class OrderCreateView(View):
    def post(self, request):
        data = json.loads(request.body)

        with transaction.atomic():
            # Create order
            order = Order.objects.create(
                customer_email=data['email'],
                total=data['total'],
            )

            # Queue tasks — all within transaction
            # Basic task
            send_order_confirmation.delay(order.id, order.customer_email)

            # Task with link (callback)
            notify_warehouse.apply_async(
                args=[order.id],
                link=schedule_shipping_reminder.s(order.id),
            )

            # Task with countdown (delayed execution)
            schedule_shipping_reminder.apply_async(
                args=[order.id],
                countdown=3600,  # 1 hour delay
            )

        return JsonResponse({
            'id': order.id,
            'status': order.status,
            'message': 'Order created, tasks queued via outbox',
        }, status=201)


class OrderListView(View):
    def get(self, request):
        orders = Order.objects.all().order_by('-created_at')[:20]
        return JsonResponse({
            'orders': [
                {
                    'id': o.id,
                    'email': o.customer_email,
                    'total': str(o.total),
                    'status': o.status,
                    'created_at': o.created_at.isoformat(),
                }
                for o in orders
            ]
        })
```

### orders/admin.py

```python
from django.contrib import admin

from orders.models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer_email', 'total', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['customer_email']
```

### minimal_django/urls.py

```python
from django.contrib import admin
from django.urls import path

from orders.views import OrderCreateView, OrderListView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('orders/', OrderListView.as_view(), name='order-list'),
    path('orders/create/', OrderCreateView.as_view(), name='order-create'),
]
```

### examples/minimal_django/README.md

```markdown
# Minimal Django + Celery Outbox Example

Demonstrates the transactional outbox pattern with:
- Order creation with multiple Celery tasks
- Tasks with countdown (delayed execution)
- Tasks with links (callbacks)
- Relay daemon processing

## Services

- **app** — Django web server (port 8000)
- **relay** — Outbox relay daemon
- **worker** — Celery worker
- **postgres** — PostgreSQL database
- **rabbitmq** — RabbitMQ broker (management UI at port 15672)

## Quick Start

```bash
# Start all services
docker compose up -d

# Create an order (triggers tasks via outbox)
curl -X POST http://localhost:8000/orders/create/ \
  -H "Content-Type: application/json" \
  -d '{"email": "customer@example.com", "total": "99.99"}'

# View orders
curl http://localhost:8000/orders/

# Watch relay logs
docker compose logs -f relay

# Watch worker logs
docker compose logs -f worker

# RabbitMQ Management UI
# http://localhost:15672/ (guest/guest)

# Inspect outbox via Django admin
# http://localhost:8000/admin/ (create superuser first)
docker compose exec app python manage.py createsuperuser
```

## What Happens

1. POST to `/orders/create/` creates an Order inside a transaction
2. Three tasks are queued to the outbox table (same transaction)
3. Transaction commits — tasks are now visible to relay
4. Relay picks up tasks, sends to RabbitMQ broker
5. Worker executes tasks

If the transaction rolls back, no tasks are sent — guaranteed consistency.
```

## Docs Content Migration Plan

### Sources → Destinations

| Source | Destination | Action |
|--------|-------------|--------|
| README.md (Quick Start) | docs/getting-started.md | Expand with more detail |
| README.md (Configuration) | docs/configuration.md | Full settings reference table |
| README.md (Usage Examples) | docs/usage/*.md | Split by topic |
| README.md (Relay) | docs/relay/*.md | Split into 4 pages |
| README.md (Metrics) | docs/observability/metrics.md | Expand |
| README.md (Security) | docs/security.md | From Spec #1 |
| ARCHITECTURE.md | docs/architecture.md | Direct migration |
| ARCHITECTURE.md (Data Flow) | docs/concepts.md | Extract core concepts |

### New Content (not from existing files)

| Page | Content |
|------|---------|
| docs/index.md | Overview, features list, badges, quick links |
| docs/usage/outside-transactions.md | Warning about using outbox outside tx |
| docs/operations/admin-interface.md | Django admin screenshots, actions |
| docs/deployment/kubernetes.md | k8s manifests, liveness probes |
| docs/deployment/database-setup.md | PostgreSQL vs MySQL notes |
| docs/troubleshooting.md | Common issues & solutions |

### README.md after migration

```markdown
# django-celery-outbox

[![PyPI](https://img.shields.io/pypi/v/django-celery-outbox.svg)](...)
[![Docs](https://img.shields.io/badge/docs-latest-blue.svg)](https://barsoomx.github.io/django-celery-outbox/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](...)

Transactional Outbox pattern for Celery tasks in Django.

## Features

- At-least-once delivery guarantee
- Automatic retry with exponential backoff
- Dead letter queue for failed messages
- Structlog & Sentry trace propagation
- StatsD metrics
- Django admin integration

## Quick Start

```bash
pip install django-celery-outbox
```

```python
# settings.py
INSTALLED_APPS = [..., 'django_celery_outbox']
CELERY_OUTBOX_APP = 'myproject.celery.app'

# celery.py
from django_celery_outbox import OutboxCelery
app = OutboxCelery('myproject')
```

```bash
python manage.py migrate
python manage.py celery_outbox_relay
```

**[Full Documentation →](https://barsoomx.github.io/django-celery-outbox/)**

## License

MIT
```

## Acceptance Criteria

From issue #32:

- [ ] `examples/minimal_django/` with working docker compose
- [ ] `docker compose up` → "send a task, see it in outbox, see relay flush it"
- [ ] Docs site (mkdocs-material) with full navigation
- [ ] Published to GitHub Pages
- [ ] README links to docs site

### Docs Site Checklist

| Page | Status |
|------|--------|
| index.md | Required |
| getting-started.md | Required |
| concepts.md | Required |
| configuration.md | Required |
| usage/basic-tasks.md | Required |
| usage/task-options.md | Required |
| usage/excluded-tasks.md | Required |
| usage/outside-transactions.md | Required |
| relay/overview.md | Required |
| relay/command-reference.md | Required |
| relay/tuning.md | Required |
| relay/multiple-instances.md | Required |
| observability/logging-events.md | From Spec #1 |
| observability/metrics.md | Required |
| observability/structlog.md | Required |
| observability/sentry.md | Required |
| operations/dead-letter.md | Required |
| operations/admin-interface.md | Required |
| operations/health-checks.md | Required |
| deployment/kubernetes.md | Required |
| deployment/database-setup.md | Required |
| security.md | From Spec #1 |
| troubleshooting.md | Required |
| architecture.md | Migrate from ARCHITECTURE.md |

### Example Project Smoke Test

```bash
# Manual verification steps
cd examples/minimal_django

# 1. Start services
docker compose up -d

# 2. Wait for healthy
docker compose ps  # all services "healthy" or "running"

# 3. Create order
curl -X POST http://localhost:8000/orders/create/ \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "total": "42.00"}'
# Expected: {"id": 1, "status": "pending", "message": "Order created..."}

# 4. Check outbox was flushed
docker compose exec app python manage.py shell -c "
from django_celery_outbox.models import CeleryOutbox
print(f'Pending: {CeleryOutbox.objects.count()}')
"
# Expected: Pending: 0 (relay processed all)

# 5. Check worker received tasks
docker compose logs worker | grep "send_order_confirmation"
# Expected: Task received and executed

# 6. Cleanup
docker compose down -v
```

### CI Integration

```yaml
# .github/workflows/example.yml
name: Test Example Project

on:
  push:
    paths: ['examples/**']
  pull_request:
    paths: ['examples/**']

jobs:
  test-example:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Start services
        working-directory: examples/minimal_django
        run: docker compose up -d --wait
      - name: Create order
        run: |
          curl -f -X POST http://localhost:8000/orders/create/ \
            -H "Content-Type: application/json" \
            -d '{"email": "ci@test.com", "total": "1.00"}'
      - name: Verify outbox empty
        working-directory: examples/minimal_django
        run: |
          sleep 5
          docker compose exec -T app python manage.py shell -c "
          from django_celery_outbox.models import CeleryOutbox
          assert CeleryOutbox.objects.count() == 0, 'Outbox not flushed'
          "
      - name: Cleanup
        working-directory: examples/minimal_django
        run: docker compose down -v
```
