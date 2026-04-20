# Minimal Django + Celery Outbox Example

Demonstrates the transactional outbox pattern with:
- Order creation with multiple Celery tasks
- Tasks with countdown (delayed execution)
- Tasks with links (callbacks)
- Relay daemon processing
- RabbitMQ publisher confirms + quorum queues

## Services

- **app** — Django web server (port 8000)
- **relay** — Outbox relay daemon
- **worker** — Celery worker
- **postgres** — PostgreSQL database
- **rabbitmq** — RabbitMQ broker (management UI at port 15672)

The example declares RabbitMQ quorum queues explicitly and enables publisher confirms:
- `CELERY_BROKER_TRANSPORT_OPTIONS = {'confirm_publish': True}`
- `CELERY_BROKER_NATIVE_DELAYED_DELIVERY_QUEUE_TYPE = 'quorum'`
- explicit `CELERY_TASK_QUEUES` with `x-queue-type=quorum`
- Celery runtime config lives in `minimal_django/celeryconfig.py`
- Celery app bootstrap lives in `minimal_django/celery_app.py`

## Quick Start

The compose services install the built wheel from `/package/dist/example`, so build the package from the repository root before starting the example.

```bash
# From the repository root
rm -rf dist/example
python -m pip install -q build
python -Im build --outdir dist/example

# Start all services
docker compose -f examples/minimal_django/docker-compose.yml up -d

# Create an order (triggers tasks via outbox)
curl -X POST http://localhost:8000/orders/create/ \
  -H "Content-Type: application/json" \
  -d '{"email": "customer@example.com", "total": "99.99"}'

# View orders
curl http://localhost:8000/orders/

# Watch relay logs
docker compose -f examples/minimal_django/docker-compose.yml logs -f relay

# Watch worker logs
docker compose -f examples/minimal_django/docker-compose.yml logs -f worker

# RabbitMQ Management UI
# http://localhost:15672/ (guest/guest)

# Inspect outbox via Django admin
# http://localhost:8000/admin/ (create superuser first)
docker compose -f examples/minimal_django/docker-compose.yml exec app python manage.py createsuperuser
```

## What Happens

1. POST to `/orders/create/` creates an Order inside a transaction
2. Three tasks are queued to the outbox table (same transaction)
3. Transaction commits — tasks are now visible to relay
4. Relay picks up tasks, sends to RabbitMQ broker
5. Worker executes tasks

If the transaction rolls back, no tasks are sent — guaranteed consistency.
