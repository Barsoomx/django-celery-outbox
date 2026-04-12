# Documentation & Example Project Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create mkdocs-material documentation site and realistic example project with Docker Compose

**Architecture:** mkdocs-material site deployed to GitHub Pages via GitHub Actions. Example project demonstrates Order processing with PostgreSQL + RabbitMQ. Docs migrate content from existing README.md and ARCHITECTURE.md.

**Tech Stack:** mkdocs-material, GitHub Pages, Docker Compose, PostgreSQL 15, RabbitMQ 3.13

---

## File Structure

### mkdocs Infrastructure
- Create: `mkdocs.yml`
- Modify: `pyproject.toml` (add docs optional-dependency)

### Example Project
- Create: `examples/minimal_django/Dockerfile`
- Create: `examples/minimal_django/docker-compose.yml`
- Create: `examples/minimal_django/requirements.txt`
- Create: `examples/minimal_django/manage.py`
- Create: `examples/minimal_django/minimal_django/__init__.py`
- Create: `examples/minimal_django/minimal_django/settings.py`
- Create: `examples/minimal_django/minimal_django/celery.py`
- Create: `examples/minimal_django/minimal_django/urls.py`
- Create: `examples/minimal_django/minimal_django/wsgi.py`
- Create: `examples/minimal_django/orders/__init__.py`
- Create: `examples/minimal_django/orders/models.py`
- Create: `examples/minimal_django/orders/tasks.py`
- Create: `examples/minimal_django/orders/views.py`
- Create: `examples/minimal_django/orders/admin.py`
- Create: `examples/minimal_django/README.md`

### Documentation Pages
- Create: `docs/index.md`
- Create: `docs/getting-started.md`
- Create: `docs/concepts.md`
- Create: `docs/configuration.md`
- Create: `docs/usage/basic-tasks.md`
- Create: `docs/usage/task-options.md`
- Create: `docs/usage/excluded-tasks.md`
- Create: `docs/usage/outside-transactions.md`
- Create: `docs/relay/overview.md`
- Create: `docs/relay/command-reference.md`
- Create: `docs/relay/tuning.md`
- Create: `docs/relay/multiple-instances.md`
- Create: `docs/observability/logging-events.md`
- Create: `docs/observability/metrics.md`
- Create: `docs/observability/structlog.md`
- Create: `docs/observability/sentry.md`
- Create: `docs/operations/dead-letter.md`
- Create: `docs/operations/admin-interface.md`
- Create: `docs/operations/health-checks.md`
- Create: `docs/deployment/kubernetes.md`
- Create: `docs/deployment/database-setup.md`
- Create: `docs/security.md`
- Create: `docs/troubleshooting.md`
- Create: `docs/architecture.md`

### CI/CD
- Create: `.github/workflows/docs.yml`
- Create: `.github/workflows/example.yml`

---

## Task 1: mkdocs Infrastructure

**Files:**
- Create: `mkdocs.yml`
- Modify: `pyproject.toml`

- [ ] **Step 1: Create mkdocs.yml**

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

- [ ] **Step 2: Add docs dependency to pyproject.toml**

Add to `[project.optional-dependencies]` section:

```toml
docs = [
    "mkdocs>=1.5",
    "mkdocs-material>=9.5",
]
```

- [ ] **Step 3: Create minimal index.md placeholder**

Create `docs/index.md`:

```markdown
# django-celery-outbox

Transactional Outbox pattern for Celery tasks in Django.

!!! note "Documentation in progress"
    This documentation site is under construction.
```

- [ ] **Step 4: Verify mkdocs builds**

Run: `pip install mkdocs-material && mkdocs build`
Expected: Build completes without errors

- [ ] **Step 5: Commit**

```bash
git add mkdocs.yml pyproject.toml docs/index.md
git commit -m "feat(docs): add mkdocs infrastructure"
```

---

## Task 2: Example Project Foundation

**Files:**
- Create: `examples/minimal_django/Dockerfile`
- Create: `examples/minimal_django/docker-compose.yml`
- Create: `examples/minimal_django/requirements.txt`

- [ ] **Step 1: Create Dockerfile**

Create `examples/minimal_django/Dockerfile`:

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

- [ ] **Step 2: Create requirements.txt**

Create `examples/minimal_django/requirements.txt`:

```
Django>=4.2,<5.3
celery>=5.3,<5.7
psycopg[binary]>=3.1
django-celery-outbox @ file:../..
```

- [ ] **Step 3: Create docker-compose.yml**

Create `examples/minimal_django/docker-compose.yml`:

```yaml
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
      - "15672:15672"
    healthcheck:
      test: ['CMD', 'rabbitmq-diagnostics', 'check_running']
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

- [ ] **Step 4: Commit**

```bash
git add examples/minimal_django/Dockerfile examples/minimal_django/docker-compose.yml examples/minimal_django/requirements.txt
git commit -m "feat(examples): add docker infrastructure for minimal_django"
```

---

## Task 3: Example Project Django Config

**Files:**
- Create: `examples/minimal_django/manage.py`
- Create: `examples/minimal_django/minimal_django/__init__.py`
- Create: `examples/minimal_django/minimal_django/settings.py`
- Create: `examples/minimal_django/minimal_django/celery.py`
- Create: `examples/minimal_django/minimal_django/urls.py`
- Create: `examples/minimal_django/minimal_django/wsgi.py`

- [ ] **Step 1: Create manage.py**

Create `examples/minimal_django/manage.py`:

```python
#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'minimal_django.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Create minimal_django/__init__.py**

Create `examples/minimal_django/minimal_django/__init__.py`:

```python
from minimal_django.celery import app as celery_app

__all__ = ('celery_app',)
```

- [ ] **Step 3: Create minimal_django/settings.py**

Create `examples/minimal_django/minimal_django/settings.py`:

```python
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-example-key-do-not-use-in-production'

DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

ALLOWED_HOSTS = ['*']

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

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'minimal_django.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'minimal_django.wsgi.application'

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

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'amqp://guest:guest@localhost:5672//')
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = False
CELERY_BROKER_TRANSPORT_OPTIONS = {
    'confirm_publish': True,
}

CELERY_OUTBOX_APP = 'minimal_django.celery.app'
CELERY_OUTBOX_EXCLUDE_TASKS = set()
CELERY_OUTBOX_STRUCTLOG_ENABLED = False
```

- [ ] **Step 4: Create minimal_django/celery.py**

Create `examples/minimal_django/minimal_django/celery.py`:

```python
import os

from django_celery_outbox import OutboxCelery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'minimal_django.settings')

app = OutboxCelery('minimal_django')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

- [ ] **Step 5: Create minimal_django/urls.py**

Create `examples/minimal_django/minimal_django/urls.py`:

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

- [ ] **Step 6: Create minimal_django/wsgi.py**

Create `examples/minimal_django/minimal_django/wsgi.py`:

```python
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'minimal_django.settings')

application = get_wsgi_application()
```

- [ ] **Step 7: Commit**

```bash
git add examples/minimal_django/manage.py examples/minimal_django/minimal_django/
git commit -m "feat(examples): add Django configuration for minimal_django"
```

---

## Task 4: Example Project Orders App

**Files:**
- Create: `examples/minimal_django/orders/__init__.py`
- Create: `examples/minimal_django/orders/models.py`
- Create: `examples/minimal_django/orders/tasks.py`
- Create: `examples/minimal_django/orders/views.py`
- Create: `examples/minimal_django/orders/admin.py`

- [ ] **Step 1: Create orders/__init__.py**

Create `examples/minimal_django/orders/__init__.py`:

```python
```

- [ ] **Step 2: Create orders/models.py**

Create `examples/minimal_django/orders/models.py`:

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

- [ ] **Step 3: Create orders/tasks.py**

Create `examples/minimal_django/orders/tasks.py`:

```python
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def send_order_confirmation(order_id: int, email: str):
    logger.info('Sending confirmation email for order %s to %s', order_id, email)
    return {'order_id': order_id, 'email': email, 'status': 'sent'}


@shared_task
def notify_warehouse(order_id: int):
    logger.info('Notifying warehouse about order %s', order_id)
    return {'order_id': order_id, 'status': 'notified'}


@shared_task
def schedule_shipping_reminder(order_id: int):
    logger.info('Sending shipping reminder for order %s', order_id)
    return {'order_id': order_id, 'status': 'reminded'}
```

- [ ] **Step 4: Create orders/views.py**

Create `examples/minimal_django/orders/views.py`:

```python
import json

from django.db import transaction
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from orders.models import Order
from orders.tasks import notify_warehouse, schedule_shipping_reminder, send_order_confirmation


@method_decorator(csrf_exempt, name='dispatch')
class OrderCreateView(View):
    def post(self, request):
        data = json.loads(request.body)

        with transaction.atomic():
            order = Order.objects.create(
                customer_email=data['email'],
                total=data['total'],
            )

            send_order_confirmation.delay(order.id, order.customer_email)

            notify_warehouse.apply_async(
                args=[order.id],
                link=schedule_shipping_reminder.s(order.id),
            )

            schedule_shipping_reminder.apply_async(
                args=[order.id],
                countdown=3600,
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

- [ ] **Step 5: Create orders/admin.py**

Create `examples/minimal_django/orders/admin.py`:

```python
from django.contrib import admin

from orders.models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer_email', 'total', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['customer_email']
```

- [ ] **Step 6: Commit**

```bash
git add examples/minimal_django/orders/
git commit -m "feat(examples): add orders app with models, tasks, views"
```

---

## Task 5: Example Project README

**Files:**
- Create: `examples/minimal_django/README.md`

- [ ] **Step 1: Create README.md**

Create `examples/minimal_django/README.md`:

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

- [ ] **Step 2: Commit**

```bash
git add examples/minimal_django/README.md
git commit -m "docs(examples): add README for minimal_django example"
```

---

## Task 6: Core Documentation Pages

**Files:**
- Create: `docs/index.md`
- Create: `docs/getting-started.md`
- Create: `docs/concepts.md`
- Create: `docs/configuration.md`

- [ ] **Step 1: Create docs/index.md**

```markdown
# django-celery-outbox

[![PyPI](https://img.shields.io/pypi/v/django-celery-outbox.svg)](https://pypi.org/project/django-celery-outbox/)
[![Tests](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/tests.yml/badge.svg)](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Transactional Outbox pattern for Celery tasks in Django.

## Why Use This?

When you call `task.delay()` inside a database transaction, two things can go wrong:

1. **Message lost**: The task is sent to the broker, but the transaction rolls back. The task runs with data that doesn't exist.
2. **Message never sent**: The transaction commits, but the broker connection fails. The task is never executed.

django-celery-outbox solves both problems by storing tasks in a database table within the same transaction as your business data. A separate relay process reads the table and sends tasks to the broker asynchronously, guaranteeing **at-least-once delivery**.

## Features

- Drop-in replacement for `celery.Celery`
- At-least-once delivery guarantee
- Automatic retry with exponential backoff
- Dead letter queue for failed messages
- Sentry trace propagation
- structlog context propagation
- StatsD metrics
- Django admin integration
- Health check endpoint

## Quick Links

- [Getting Started](getting-started.md) — Install and configure in 5 minutes
- [Concepts](concepts.md) — How the outbox pattern works
- [Configuration](configuration.md) — All settings reference
- [Example Project](https://github.com/Barsoomx/django-celery-outbox/tree/master/examples/minimal_django) — Working Docker Compose setup
```

- [ ] **Step 2: Create docs/getting-started.md**

```markdown
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
```

- [ ] **Step 3: Create docs/concepts.md**

```markdown
# Concepts

## The Problem

Traditional Celery task dispatch has a fundamental race condition:

```python
with transaction.atomic():
    order = Order.objects.create(...)
    send_email.delay(order.id)  # Task sent NOW, before commit
# Transaction commits HERE
```

If the transaction rolls back after the task is sent, the worker receives a task for an order that doesn't exist.

## The Solution: Transactional Outbox

Instead of sending tasks directly to the broker, we write them to a database table within the same transaction:

```
┌─────────────────────────────────────────────────────────┐
│                    TRANSACTION                          │
│  ┌─────────────┐    ┌─────────────────────────────┐    │
│  │ Order.save()│ →  │ CeleryOutbox.create(task)   │    │
│  └─────────────┘    └─────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼ COMMIT
┌─────────────────────────────────────────────────────────┐
│                    RELAY DAEMON                         │
│  ┌─────────────────────────┐    ┌─────────────────┐    │
│  │ SELECT FOR UPDATE       │ →  │ app.send_task() │    │
│  │ SKIP LOCKED             │    │ to broker       │    │
│  └─────────────────────────┘    └─────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

## Delivery Guarantees

**At-least-once delivery**: Once the transaction commits, the task will eventually be delivered to the broker. If the relay crashes, it will retry on next startup.

**No duplicate prevention**: The same task may be delivered multiple times if the relay crashes after sending but before deleting from the outbox. Your tasks should be idempotent.

## Components

### OutboxCelery

Drop-in replacement for `celery.Celery`. Intercepts `send_task()` calls and writes to the outbox table instead of the broker.

### Relay Daemon

Management command (`celery_outbox_relay`) that:

1. Polls the outbox table for pending messages
2. Sends them to the broker via Celery's `send_task()`
3. Deletes successfully sent messages
4. Retries failed messages with exponential backoff
5. Moves permanently failed messages to dead letter queue

### Dead Letter Queue

Messages that exceed `max_retries` are moved to `CeleryOutboxDeadLetter` for manual inspection and replay.
```

- [ ] **Step 4: Create docs/configuration.md**

```markdown
# Configuration

All settings are prefixed with `CELERY_OUTBOX_`.

## Required Settings

| Setting | Type | Description |
|---------|------|-------------|
| `CELERY_OUTBOX_APP` | `str` | Dotted path to your Celery app instance. Example: `'myproject.celery.app'` |

## Optional Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `CELERY_OUTBOX_EXCLUDE_TASKS` | `set[str]` | `set()` | Task names to bypass the outbox (sent directly to broker) |
| `CELERY_OUTBOX_STRUCTLOG_ENABLED` | `bool` | `True` | Enable structlog context propagation |
| `CELERY_OUTBOX_STRUCTLOG_FILTER_KEYS` | `set[str]` | `set()` | structlog keys to exclude from propagation |
| `CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK` | `bool` | `True` | Include full traceback in exception logs |
| `CELERY_OUTBOX_PII_REDACTOR` | `str` | `None` | Dotted path to PII redaction callable |

## Relay Command Options

```bash
python manage.py celery_outbox_relay [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--batch-size` | `100` | Messages per batch |
| `--idle-time` | `1.0` | Seconds to sleep when queue is empty |
| `--backoff-time` | `5.0` | Base seconds for exponential backoff |
| `--max-retries` | `5` | Retries before dead letter |
| `--liveness-file` | `None` | File to touch after each batch (for k8s probes) |

## Metrics Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `CELERY_OUTBOX_STATSD_HOST` | `str` | `'localhost'` | StatsD server host |
| `CELERY_OUTBOX_STATSD_PORT` | `int` | `8125` | StatsD server port |
| `CELERY_OUTBOX_STATSD_PREFIX` | `str` | `'celery_outbox'` | Metric name prefix |
| `CELERY_OUTBOX_STATSD_TAGS` | `dict` | `{}` | Default tags for all metrics |
```

- [ ] **Step 5: Verify mkdocs builds**

Run: `mkdocs build`
Expected: Build completes without errors

- [ ] **Step 6: Commit**

```bash
git add docs/index.md docs/getting-started.md docs/concepts.md docs/configuration.md
git commit -m "docs: add core documentation pages"
```

---

## Task 7: Usage Documentation

**Files:**
- Create: `docs/usage/basic-tasks.md`
- Create: `docs/usage/task-options.md`
- Create: `docs/usage/excluded-tasks.md`
- Create: `docs/usage/outside-transactions.md`

- [ ] **Step 1: Create docs/usage/basic-tasks.md**

```markdown
# Basic Tasks

## Sending Tasks

With `OutboxCelery`, tasks are sent exactly like regular Celery:

```python
from myproject.celery import app

@app.task
def send_email(user_id: int, template: str):
    ...

# All these work:
send_email.delay(123, 'welcome')
send_email.apply_async(args=[123, 'welcome'])
send_email.apply_async(kwargs={'user_id': 123, 'template': 'welcome'})
```

## Inside Transactions

The outbox pattern only makes sense inside transactions:

```python
from django.db import transaction

with transaction.atomic():
    user = User.objects.create(email='test@example.com')
    send_email.delay(user.id, 'welcome')
# Both committed together
```

If the transaction rolls back, the task is never sent.

## Task Signatures

Celery signatures are fully supported:

```python
from celery import signature, chain, group, chord

# Signature
sig = send_email.s(123, 'welcome')
sig.delay()

# Chain
chain(step1.s(), step2.s(), step3.s()).delay()

# Group (parallel execution)
group(task.s(i) for i in range(10)).delay()

# Chord (group + callback)
chord(group(task.s(i) for i in range(10)), callback.s()).delay()
```
```

- [ ] **Step 2: Create docs/usage/task-options.md**

```markdown
# Task Options

## Supported Options

All standard Celery task options work through the outbox:

| Option | Description |
|--------|-------------|
| `countdown` | Delay execution by N seconds |
| `eta` | Execute at specific datetime |
| `expires` | Discard if not executed by this time |
| `link` | Callback task on success |
| `link_error` | Callback task on failure |
| `time_limit` | Hard time limit |
| `soft_time_limit` | Soft time limit (raises `SoftTimeLimitExceeded`) |

## Examples

### Countdown

```python
# Execute 60 seconds from now
send_email.apply_async(args=[user.id], countdown=60)
```

!!! note "Countdown vs ETA"
    `countdown` is converted to absolute `eta` at intercept time. This ensures the task runs at the correct time regardless of relay delay.

### ETA

```python
from datetime import datetime, timedelta

# Execute at specific time
send_email.apply_async(
    args=[user.id],
    eta=datetime.now() + timedelta(hours=1)
)
```

### Callbacks

```python
# Execute step2 after step1 completes
step1.apply_async(args=[data], link=step2.s())

# Execute error_handler if step1 fails
step1.apply_async(args=[data], link_error=error_handler.s())
```

### Time Limits

```python
# Kill task after 30 seconds
long_task.apply_async(args=[data], time_limit=30)

# Raise SoftTimeLimitExceeded after 25 seconds
long_task.apply_async(args=[data], soft_time_limit=25)
```
```

- [ ] **Step 3: Create docs/usage/excluded-tasks.md**

```markdown
# Excluded Tasks

## Bypassing the Outbox

Some tasks should bypass the outbox and go directly to the broker:

- Real-time notifications that can't wait for relay
- Tasks that don't need transactional guarantees
- High-volume tasks where relay latency matters

## Configuration

```python
# settings.py
CELERY_OUTBOX_EXCLUDE_TASKS = {
    'myapp.tasks.send_push_notification',
    'myapp.tasks.log_analytics',
}
```

## Behavior

Excluded tasks are sent directly to the broker using the original `Celery.send_task()`:

```python
# This goes through outbox
order_created.delay(order.id)

# This bypasses outbox (if in EXCLUDE_TASKS)
send_push_notification.delay(user.id, 'Order shipped!')
```

!!! warning "No Transactional Guarantee"
    Excluded tasks can be lost if the broker connection fails, or executed with uncommitted data if called inside a transaction.
```

- [ ] **Step 4: Create docs/usage/outside-transactions.md**

```markdown
# Outside Transactions

## Warning

Using the outbox outside a transaction defeats its purpose:

```python
# BAD: Not in a transaction
order = Order.objects.create(...)
send_email.delay(order.id)  # Written to outbox, but not atomic with Order
```

The relay logs a warning when this happens:

```
celery_outbox_not_in_transaction task_name=myapp.tasks.send_email
```

## When It's Acceptable

Outside transactions may be acceptable for:

- Background jobs that don't need atomicity
- Tasks triggered by management commands
- Testing and development

## Recommendations

1. **Use transactions**: Wrap related operations in `transaction.atomic()`
2. **Enable warnings**: Check logs for `celery_outbox_not_in_transaction`
3. **Consider excluded tasks**: If a task doesn't need transactional guarantees, add it to `CELERY_OUTBOX_EXCLUDE_TASKS`
```

- [ ] **Step 5: Commit**

```bash
git add docs/usage/
git commit -m "docs: add usage documentation pages"
```

---

## Task 8: Relay Documentation

**Files:**
- Create: `docs/relay/overview.md`
- Create: `docs/relay/command-reference.md`
- Create: `docs/relay/tuning.md`
- Create: `docs/relay/multiple-instances.md`

- [ ] **Step 1: Create docs/relay/overview.md**

```markdown
# Relay Overview

The relay daemon is the core component that moves tasks from the database to the message broker.

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                    PROCESSING LOOP                       │
│                                                          │
│  1. SELECT batch of messages (FOR UPDATE SKIP LOCKED)   │
│  2. For each message:                                    │
│     - Send to broker via Celery.send_task()             │
│     - Mark as published or failed                        │
│  3. Delete published messages                            │
│  4. Update retry count for failed messages               │
│  5. Move exceeded messages to dead letter               │
│  6. Sleep if queue was empty                             │
│  7. Repeat                                               │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## Starting the Relay

```bash
python manage.py celery_outbox_relay
```

## Graceful Shutdown

The relay handles SIGTERM and SIGINT gracefully:

1. Completes current batch
2. Closes database connections
3. Exits cleanly

This makes it safe for container orchestrators like Kubernetes.
```

- [ ] **Step 2: Create docs/relay/command-reference.md**

```markdown
# Command Reference

## celery_outbox_relay

Main relay daemon command.

```bash
python manage.py celery_outbox_relay [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--batch-size` | int | 100 | Maximum messages per batch |
| `--idle-time` | float | 1.0 | Seconds to sleep when queue empty |
| `--backoff-time` | float | 5.0 | Base seconds for exponential backoff |
| `--max-retries` | int | 5 | Retries before dead letter |
| `--liveness-file` | path | None | File to touch after each batch |

### Examples

```bash
# Development (fast polling)
python manage.py celery_outbox_relay --batch-size 10 --idle-time 0.5

# Production (larger batches)
python manage.py celery_outbox_relay --batch-size 500 --idle-time 2.0

# With liveness probe
python manage.py celery_outbox_relay --liveness-file /tmp/relay-alive
```

## celery_outbox_stats

Show outbox statistics.

```bash
python manage.py celery_outbox_stats
```

Output:

```
Pending:      42
Dead Letter:  3
Oldest:       2024-01-15 10:30:00 (5m ago)
```

## celery_outbox_dead_letter_purge

Purge old dead letter entries.

```bash
python manage.py celery_outbox_dead_letter_purge --older-than 30
```

Deletes entries older than 30 days.
```

- [ ] **Step 3: Create docs/relay/tuning.md**

```markdown
# Relay Tuning

## Batch Size

Controls how many messages are processed per database round-trip.

| Scenario | Recommended | Rationale |
|----------|-------------|-----------|
| Low volume (<100/min) | 10-50 | Lower latency |
| Medium volume | 100-200 | Balance |
| High volume (>1000/min) | 500-1000 | Throughput |

```bash
--batch-size 500
```

## Idle Time

How long to sleep when the queue is empty.

| Scenario | Recommended | Rationale |
|----------|-------------|-----------|
| Real-time required | 0.1-0.5 | Sub-second latency |
| Standard | 1.0-2.0 | Balance |
| Background jobs | 5.0-10.0 | Reduce DB load |

```bash
--idle-time 1.0
```

## Backoff Time

Base seconds for exponential backoff on failed messages.

Formula: `delay = backoff_time * 2^retries + jitter`

| Retries | Delay (5s base) |
|---------|-----------------|
| 0 | 5s |
| 1 | 10s |
| 2 | 20s |
| 3 | 40s |
| 4 | 80s |

```bash
--backoff-time 5.0
```

## Max Retries

After this many failures, the message moves to dead letter.

```bash
--max-retries 5
```

## Monitoring Metrics

The relay emits these StatsD metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `queue.depth` | gauge | Messages waiting |
| `dead_letter.count` | gauge | Dead letter entries |
| `batch.duration_ms` | timing | Batch processing time |
| `messages.published` | counter | Successfully sent |
| `messages.failed` | counter | Failed (will retry) |
| `messages.exceeded` | counter | Moved to dead letter |
```

- [ ] **Step 4: Create docs/relay/multiple-instances.md**

```markdown
# Multiple Relay Instances

## Scaling Horizontally

You can run multiple relay instances safely thanks to `SELECT FOR UPDATE SKIP LOCKED`:

```bash
# Instance 1
python manage.py celery_outbox_relay --batch-size 100

# Instance 2
python manage.py celery_outbox_relay --batch-size 100

# Instance 3
python manage.py celery_outbox_relay --batch-size 100
```

Each instance locks different rows, preventing double-processing.

## Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: celery-outbox-relay
spec:
  replicas: 3  # Scale as needed
  selector:
    matchLabels:
      app: celery-outbox-relay
  template:
    spec:
      containers:
        - name: relay
          image: myapp:latest
          command:
            - python
            - manage.py
            - celery_outbox_relay
            - --batch-size=100
            - --liveness-file=/tmp/alive
          livenessProbe:
            exec:
              command:
                - test
                - -f
                - /tmp/alive
            initialDelaySeconds: 10
            periodSeconds: 30
```

## Considerations

1. **Database connections**: Each instance uses one connection
2. **Lock contention**: More instances = more lock attempts
3. **Diminishing returns**: Beyond 3-5 instances, gains are minimal
4. **Monitoring**: Track `messages.published` per instance
```

- [ ] **Step 5: Commit**

```bash
git add docs/relay/
git commit -m "docs: add relay documentation pages"
```

---

## Task 9: Observability Documentation

**Files:**
- Create: `docs/observability/logging-events.md`
- Create: `docs/observability/metrics.md`
- Create: `docs/observability/structlog.md`
- Create: `docs/observability/sentry.md`

- [ ] **Step 1: Create docs/observability/logging-events.md**

```markdown
# Logging Events

The relay emits structured log events via structlog.

## Event Reference

| Event | Level | When |
|-------|-------|------|
| `celery_outbox_relay_started` | INFO | Relay daemon starts |
| `celery_outbox_relay_shutdown` | INFO | SIGTERM/SIGINT received |
| `celery_outbox_batch_processed` | INFO | Batch completed |
| `celery_outbox_send_failed` | ERROR | Broker send failed |
| `celery_outbox_max_retries_exceeded` | WARNING | Message dead-lettered |
| `celery_outbox_not_in_transaction` | WARNING | Task sent outside transaction |

## Batch Processed Event

Most useful for monitoring:

```json
{
  "event": "celery_outbox_batch_processed",
  "published": 42,
  "failed": 1,
  "exceeded": 0,
  "queue_depth": 15
}
```

## Log Aggregation

Configure structlog to output JSON for log aggregation:

```python
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
```
```

- [ ] **Step 2: Create docs/observability/metrics.md**

```markdown
# Metrics

The relay emits StatsD metrics for monitoring.

## Configuration

```python
# settings.py
CELERY_OUTBOX_STATSD_HOST = 'localhost'
CELERY_OUTBOX_STATSD_PORT = 8125
CELERY_OUTBOX_STATSD_PREFIX = 'celery_outbox'
CELERY_OUTBOX_STATSD_TAGS = {
    'env': 'production',
    'service': 'myapp',
}
```

## Metric Reference

| Metric | Type | Tags | Description |
|--------|------|------|-------------|
| `queue.depth` | gauge | - | Pending messages |
| `dead_letter.count` | gauge | - | Dead letter entries |
| `batch.duration_ms` | timing | - | Processing time |
| `messages.published` | counter | `task_name` | Successfully sent |
| `messages.failed` | counter | `task_name` | Failed (will retry) |
| `messages.exceeded` | counter | `task_name` | Dead-lettered |

## Grafana Dashboard

Example PromQL queries (via StatsD exporter):

```promql
# Queue depth
celery_outbox_queue_depth

# Throughput (messages/sec)
rate(celery_outbox_messages_published_total[5m])

# Error rate
rate(celery_outbox_messages_failed_total[5m]) /
rate(celery_outbox_messages_published_total[5m])

# P95 batch duration
histogram_quantile(0.95, celery_outbox_batch_duration_ms_bucket)
```

## Alerting

Recommended alerts:

| Condition | Severity | Action |
|-----------|----------|--------|
| `queue.depth > 1000` for 5m | Warning | Check relay health |
| `dead_letter.count > 10` | Warning | Investigate failures |
| `messages.failed > 0` for 10m | Warning | Check broker connectivity |
```

- [ ] **Step 3: Create docs/observability/structlog.md**

```markdown
# Structlog Integration

The outbox propagates structlog context from producer to consumer.

## How It Works

1. Producer captures `structlog.contextvars.get_contextvars()`
2. Context is stored in `CeleryOutbox.structlog_context` as JSON
3. Relay restores context before sending to broker
4. Worker receives context in task headers

## Configuration

```python
# settings.py
CELERY_OUTBOX_STRUCTLOG_ENABLED = True  # Default

# Optional: filter sensitive keys
CELERY_OUTBOX_STRUCTLOG_FILTER_KEYS = {
    'password',
    'api_key',
    'access_token',
}
```

## Example

```python
import structlog

log = structlog.get_logger()

with structlog.contextvars.bound_contextvars(
    request_id='abc-123',
    user_id=42,
):
    with transaction.atomic():
        order = Order.objects.create(...)
        send_email.delay(order.id)
        # Context captured: {'request_id': 'abc-123', 'user_id': 42}
```

Worker logs will include `request_id` and `user_id`.

## Disabling

```python
CELERY_OUTBOX_STRUCTLOG_ENABLED = False
```

When disabled, no context is captured or propagated.
```

- [ ] **Step 4: Create docs/observability/sentry.md**

```markdown
# Sentry Integration

The outbox propagates Sentry trace context across the transaction boundary.

## How It Works

1. Producer captures `sentry_sdk.get_traceparent()` and `sentry_sdk.get_baggage()`
2. Trace IDs are stored in `CeleryOutbox.sentry_trace_id` and `sentry_baggage`
3. Relay sends them as `sentry-trace` and `baggage` headers
4. Worker continues the trace

## Configuration

No configuration needed. If Sentry SDK is installed and initialized, trace propagation is automatic.

```python
# settings.py or wsgi.py
import sentry_sdk

sentry_sdk.init(
    dsn="...",
    traces_sample_rate=1.0,
)
```

## Trace Continuity

```
Producer Transaction
    └── celery_outbox.intercept (span)
            │
         [DATABASE]
            │
Relay Transaction
    └── celery_outbox.relay.send (span)
            │
         [BROKER]
            │
Worker Transaction
    └── task.execute (span)
```

## Sentry Dashboard

In Sentry, you'll see:

1. **Producer transaction**: Original HTTP request that created the task
2. **Relay span**: `celery_outbox.relay.send` with message ID
3. **Worker transaction**: Task execution linked to producer

This gives you end-to-end visibility from HTTP request to task completion.
```

- [ ] **Step 5: Commit**

```bash
git add docs/observability/
git commit -m "docs: add observability documentation pages"
```

---

## Task 10: Operations Documentation

**Files:**
- Create: `docs/operations/dead-letter.md`
- Create: `docs/operations/admin-interface.md`
- Create: `docs/operations/health-checks.md`

- [ ] **Step 1: Create docs/operations/dead-letter.md**

```markdown
# Dead Letter Queue

Messages that exceed `max_retries` are moved to `CeleryOutboxDeadLetter`.

## Viewing Dead Letters

### Django Admin

Navigate to Django Admin > Celery Outbox > Dead Letter Queue

### Management Command

```bash
python manage.py celery_outbox_stats
```

Output includes dead letter count.

## Investigating Failures

Each dead letter entry contains:

| Field | Description |
|-------|-------------|
| `task_name` | The failed task |
| `task_id` | Celery task ID |
| `args`, `kwargs` | Task arguments |
| `retries` | Number of attempts |
| `failure_reason` | Why it failed |
| `created_at` | Original queue time |
| `moved_at` | When dead-lettered |

## Replaying Dead Letters

Currently manual. Copy task data and re-queue:

```python
from django_celery_outbox.models import CeleryOutboxDeadLetter
from myproject.celery import app

dl = CeleryOutboxDeadLetter.objects.get(pk=123)
app.send_task(dl.task_name, args=dl.args, kwargs=dl.kwargs)
dl.delete()
```

## Purging Old Entries

```bash
# Delete entries older than 30 days
python manage.py celery_outbox_dead_letter_purge --older-than 30
```

## Retention Policy

Dead letters should be reviewed and purged regularly. Recommended:

1. **Alert** on `dead_letter.count > 0`
2. **Investigate** within 24 hours
3. **Purge** entries older than 30 days
```

- [ ] **Step 2: Create docs/operations/admin-interface.md**

```markdown
# Admin Interface

django-celery-outbox includes read-only Django Admin views.

## Setup

Add to your `INSTALLED_APPS` (already done if following Quick Start):

```python
INSTALLED_APPS = [
    # ...
    'django_celery_outbox',
]
```

## Available Views

### Celery Outbox

Lists pending messages:

| Column | Description |
|--------|-------------|
| ID | Database primary key |
| Task Name | Celery task name |
| Task ID | Celery task UUID |
| Retries | Current retry count |
| Created At | When queued |
| Retry After | Next retry time (if failed) |

### Dead Letter Queue

Lists failed messages:

| Column | Description |
|--------|-------------|
| ID | Database primary key |
| Task Name | Celery task name |
| Task ID | Celery task UUID |
| Retries | Final retry count |
| Failure Reason | Why it failed |
| Created At | When originally queued |

## Read-Only

Admin views are read-only by design. Modifying outbox entries could cause:

- Duplicate task execution
- Lost tasks
- Inconsistent state

Use management commands for operations.
```

- [ ] **Step 3: Create docs/operations/health-checks.md**

```markdown
# Health Checks

## Relay Liveness Probe

The relay supports file-based liveness probes for Kubernetes:

```bash
python manage.py celery_outbox_relay --liveness-file /tmp/relay-alive
```

After each batch, the relay touches this file. Configure your probe:

```yaml
livenessProbe:
  exec:
    command:
      - test
      - -f
      - /tmp/relay-alive
  initialDelaySeconds: 10
  periodSeconds: 30
  failureThreshold: 3
```

If the file isn't touched for 90 seconds (30s * 3), Kubernetes restarts the pod.

## Queue Depth Check

Monitor queue depth via stats command:

```bash
python manage.py celery_outbox_stats
```

Or via StatsD metric:

```promql
celery_outbox_queue_depth > 1000
```

## Health Endpoint

For load balancer health checks, add a view:

```python
from django.http import JsonResponse
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter

def health(request):
    return JsonResponse({
        'status': 'ok',
        'queue_depth': CeleryOutbox.objects.count(),
        'dead_letter_count': CeleryOutboxDeadLetter.objects.count(),
    })
```

```python
# urls.py
path('health/', health),
```
```

- [ ] **Step 4: Commit**

```bash
git add docs/operations/
git commit -m "docs: add operations documentation pages"
```

---

## Task 11: Deployment Documentation

**Files:**
- Create: `docs/deployment/kubernetes.md`
- Create: `docs/deployment/database-setup.md`

- [ ] **Step 1: Create docs/deployment/kubernetes.md**

```markdown
# Kubernetes Deployment

## Deployment Manifest

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: celery-outbox-relay
spec:
  replicas: 2
  selector:
    matchLabels:
      app: celery-outbox-relay
  template:
    metadata:
      labels:
        app: celery-outbox-relay
    spec:
      containers:
        - name: relay
          image: myapp:latest
          command:
            - python
            - manage.py
            - celery_outbox_relay
            - --batch-size=100
            - --idle-time=1.0
            - --liveness-file=/tmp/alive
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: myapp-secrets
                  key: database-url
            - name: CELERY_BROKER_URL
              valueFrom:
                secretKeyRef:
                  name: myapp-secrets
                  key: broker-url
          livenessProbe:
            exec:
              command: ["test", "-f", "/tmp/alive"]
            initialDelaySeconds: 10
            periodSeconds: 30
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "256Mi"
              cpu: "500m"
```

## Scaling

The relay scales horizontally. Each instance locks different rows via `SELECT FOR UPDATE SKIP LOCKED`.

Recommended: 2-3 replicas for high availability.

## Graceful Shutdown

The relay handles SIGTERM gracefully. Kubernetes sends SIGTERM during pod termination.

Set `terminationGracePeriodSeconds` to allow batch completion:

```yaml
spec:
  terminationGracePeriodSeconds: 30
```

## Resource Requirements

| Workload | Memory | CPU |
|----------|--------|-----|
| Low volume | 128Mi | 100m |
| Medium volume | 256Mi | 250m |
| High volume | 512Mi | 500m |

Relay is I/O bound (database + broker), not CPU bound.
```

- [ ] **Step 2: Create docs/deployment/database-setup.md**

```markdown
# Database Setup

## Supported Databases

| Database | Minimum Version | Notes |
|----------|-----------------|-------|
| PostgreSQL | 9.5 | Recommended |
| MySQL | 8.0.1 | Supported |
| SQLite | - | Not supported |

## PostgreSQL Setup

```sql
CREATE DATABASE myapp;
CREATE USER myapp WITH PASSWORD 'secret';
GRANT ALL PRIVILEGES ON DATABASE myapp TO myapp;
```

```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'myapp',
        'USER': 'myapp',
        'PASSWORD': 'secret',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```

## MySQL Setup

```sql
CREATE DATABASE myapp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'myapp'@'%' IDENTIFIED BY 'secret';
GRANT ALL PRIVILEGES ON myapp.* TO 'myapp'@'%';
```

```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'myapp',
        'USER': 'myapp',
        'PASSWORD': 'secret',
        'HOST': 'localhost',
        'PORT': '3306',
        'OPTIONS': {
            'charset': 'utf8mb4',
        }
    }
}
```

## Multi-Database Setup

If using a separate database for the outbox:

```python
DATABASE_ROUTERS = ['myapp.routers.OutboxRouter']
```

```python
# myapp/routers.py
class OutboxRouter:
    def db_for_read(self, model, **hints):
        if model._meta.app_label == 'django_celery_outbox':
            return 'outbox'
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == 'django_celery_outbox':
            return 'outbox'
        return None
```

## Migrations

```bash
python manage.py migrate django_celery_outbox
```

Creates two tables:

- `celery_outbox` — Pending messages
- `celery_outbox_dead_letter` — Failed messages
```

- [ ] **Step 3: Commit**

```bash
git add docs/deployment/
git commit -m "docs: add deployment documentation pages"
```

---

## Task 12: Standalone Documentation Pages

**Files:**
- Create: `docs/security.md`
- Create: `docs/troubleshooting.md`
- Create: `docs/architecture.md`

- [ ] **Step 1: Create docs/security.md**

```markdown
# Security

## PII in Task Arguments

Task arguments are stored in the database. If they contain PII:

1. **Minimize data**: Pass IDs, not full objects
2. **Use PII redactor**: Configure `CELERY_OUTBOX_PII_REDACTOR`
3. **Encrypt sensitive fields**: Before passing to tasks

### PII Redactor

```python
# settings.py
CELERY_OUTBOX_PII_REDACTOR = 'myapp.utils.redact_pii'
```

```python
# myapp/utils.py
def redact_pii(args: list, kwargs: dict) -> tuple[list, dict]:
    redacted_kwargs = kwargs.copy()
    if 'email' in redacted_kwargs:
        redacted_kwargs['email'] = '***@***.***'
    return args, redacted_kwargs
```

## structlog Context

Filter sensitive keys from propagated context:

```python
CELERY_OUTBOX_STRUCTLOG_FILTER_KEYS = {
    'password',
    'api_key',
    'access_token',
    'credit_card',
}
```

## Exception Tracebacks

By default, full tracebacks are logged. Disable for production:

```python
CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK = False
```

## Dead Letter Retention

Dead letters may contain sensitive data. Purge regularly:

```bash
python manage.py celery_outbox_dead_letter_purge --older-than 30
```

## Database Access

- Grant minimal permissions to application user
- Use separate credentials for relay if possible
- Enable TLS for database connections
```

- [ ] **Step 2: Create docs/troubleshooting.md**

```markdown
# Troubleshooting

## Tasks Not Being Sent

### Check queue depth

```bash
python manage.py celery_outbox_stats
```

If queue is growing, relay may not be running.

### Check relay logs

```bash
docker compose logs relay
```

Look for `celery_outbox_relay_started` and `celery_outbox_batch_processed`.

### Check broker connectivity

```bash
celery -A myproject inspect ping
```

## Tasks Sent But Not Executed

### Check worker logs

```bash
celery -A myproject worker -l info
```

### Verify broker has messages

RabbitMQ Management UI: http://localhost:15672/

## High Queue Depth

1. Scale relay instances
2. Increase batch size
3. Check for slow broker

## Messages Going to Dead Letter

### Check failure reasons

```python
from django_celery_outbox.models import CeleryOutboxDeadLetter

for dl in CeleryOutboxDeadLetter.objects.all()[:10]:
    print(dl.task_name, dl.failure_reason)
```

### Common causes

- Broker connection refused
- Invalid task name (task not registered)
- Serialization errors

## "Not in transaction" Warnings

```
celery_outbox_not_in_transaction task_name=myapp.tasks.send_email
```

Task was sent outside `transaction.atomic()`. Either:

1. Wrap in transaction
2. Add to `CELERY_OUTBOX_EXCLUDE_TASKS`

## Database Lock Contention

If using many relay instances, you may see lock waits. Reduce instances or batch size.

```sql
-- PostgreSQL: check for locks
SELECT * FROM pg_locks WHERE relation = 'celery_outbox'::regclass;
```
```

- [ ] **Step 3: Create docs/architecture.md**

Migrate from existing `ARCHITECTURE.md`. Read the file first:

```bash
cat ARCHITECTURE.md
```

Then create `docs/architecture.md` with the content adapted for mkdocs format.

- [ ] **Step 4: Commit**

```bash
git add docs/security.md docs/troubleshooting.md docs/architecture.md
git commit -m "docs: add security, troubleshooting, architecture pages"
```

---

## Task 13: GitHub Actions Workflows

**Files:**
- Create: `.github/workflows/docs.yml`
- Create: `.github/workflows/example.yml`

- [ ] **Step 1: Create .github/workflows/docs.yml**

```yaml
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

- [ ] **Step 2: Create .github/workflows/example.yml**

```yaml
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
        run: docker compose up -d --wait --wait-timeout 120

      - name: Wait for services
        run: sleep 10

      - name: Create order
        run: |
          curl -f -X POST http://localhost:8000/orders/create/ \
            -H "Content-Type: application/json" \
            -d '{"email": "ci@test.com", "total": "1.00"}'

      - name: Verify outbox processed
        working-directory: examples/minimal_django
        run: |
          sleep 5
          docker compose exec -T app python manage.py shell -c "
          from django_celery_outbox.models import CeleryOutbox
          count = CeleryOutbox.objects.count()
          print(f'Pending: {count}')
          assert count == 0, f'Outbox not flushed: {count} pending'
          "

      - name: Cleanup
        working-directory: examples/minimal_django
        if: always()
        run: docker compose down -v
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/docs.yml .github/workflows/example.yml
git commit -m "ci: add docs deployment and example test workflows"
```

---

## Task 14: Final Verification

**Files:**
- Verify all docs build
- Verify example project works
- Update main README with docs link

- [ ] **Step 1: Build docs locally**

Run: `mkdocs build --strict`
Expected: Build completes without warnings or errors

- [ ] **Step 2: Serve docs locally**

Run: `mkdocs serve`
Expected: Site accessible at http://127.0.0.1:8000/

- [ ] **Step 3: Verify all navigation links work**

Click through all nav items in the local preview.

- [ ] **Step 4: Test example project**

```bash
cd examples/minimal_django
docker compose up -d --wait
curl -X POST http://localhost:8000/orders/create/ \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "total": "42.00"}'
sleep 3
docker compose exec app python manage.py shell -c "
from django_celery_outbox.models import CeleryOutbox
print(f'Pending: {CeleryOutbox.objects.count()}')
"
docker compose down -v
```

Expected: `Pending: 0`

- [ ] **Step 5: Add docs badge to README.md**

Add after existing badges in `README.md`:

```markdown
[![Docs](https://img.shields.io/badge/docs-latest-blue.svg)](https://barsoomx.github.io/django-celery-outbox/)
```

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: add docs badge to README"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | mkdocs Infrastructure | mkdocs.yml, pyproject.toml, docs/index.md |
| 2 | Example Project Foundation | Dockerfile, docker-compose.yml, requirements.txt |
| 3 | Example Django Config | manage.py, settings.py, celery.py, urls.py, wsgi.py |
| 4 | Orders App | models.py, tasks.py, views.py, admin.py |
| 5 | Example README | examples/minimal_django/README.md |
| 6 | Core Docs | index.md, getting-started.md, concepts.md, configuration.md |
| 7 | Usage Docs | 4 pages in docs/usage/ |
| 8 | Relay Docs | 4 pages in docs/relay/ |
| 9 | Observability Docs | 4 pages in docs/observability/ |
| 10 | Operations Docs | 3 pages in docs/operations/ |
| 11 | Deployment Docs | 2 pages in docs/deployment/ |
| 12 | Standalone Docs | security.md, troubleshooting.md, architecture.md |
| 13 | GitHub Actions | docs.yml, example.yml |
| 14 | Final Verification | Build, test, README update |
