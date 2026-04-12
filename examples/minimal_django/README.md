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
