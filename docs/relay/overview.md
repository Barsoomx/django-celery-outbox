# Relay Overview

The relay daemon is the core component that moves tasks from the database to the message broker.

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                    PROCESSING LOOP                      │
│                                                         │
│  1. If breaker is open, sleep until cooldown expires    │
│  2. SELECT batch of messages (FOR UPDATE SKIP LOCKED)   │
│  3. Publish selected messages                           │
│     - Serial by default                                 │
│     - Optional bounded sliding window                   │
│     - Stop starting new sends after shutdown deadline   │
│     - Stop refilling after consecutive broker outages   │
│     - Worker threads publish prepared broker payloads   │
│     - Main thread classifies outcomes and mutates DB    │
│  4. Delete published messages                           │
│  5. Apply retry backoff / dead-letter / outage deferral │
│  6. Touch liveness file                                 │
│  7. Sleep if queue was empty or batch was short         │
│  8. Repeat                                              │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Starting the Relay

```bash
python manage.py celery_outbox_relay
```

Optional advanced tuning:

```bash
python manage.py celery_outbox_relay --publish-concurrency 2
```

Keep `--publish-concurrency=1` as the baseline unless you have broker-backed verification for your
deployment path.

## Graceful Shutdown

The relay handles SIGTERM and SIGINT gracefully:

1. `SIGTERM` or `SIGINT` starts draining mode.
2. The relay stops starting new sends after `--shutdown-timeout`.
3. An already-running publish is bounded only by `--send-timeout`.
4. Already-selected but not-yet-started rows recover later through stale-timeout selection.

This lets container orchestrators stop the process without dropping committed rows, while still
leaving duplicate-tolerant recovery semantics in place if a row is reclaimed later.

## Broker Outage Handling

Broker outages are handled differently from ordinary task publish failures:

- Publish attempts are still bounded by `--send-timeout`.
- Broker-outage rows are deferred by `--broker-outage-cooldown` instead of consuming retry budget.
- After two consecutive broker outages in one batch, the process-local breaker opens and the
  relay stops starting new batch attempts until the cooldown expires.
- In parallel publish mode, the relay also stops refilling the worker window until the already
  in-flight results are classified.
- The breaker is not shared across relay processes.
