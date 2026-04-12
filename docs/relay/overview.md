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
