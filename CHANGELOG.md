Changelog
=========

All notable changes to this project will be documented in this file.
This project adheres to Keep a Changelog and semantic versioning.

0.1.0 — Unreleased
-------------------

Added
- `CeleryOutbox` model with JSON fields for args, kwargs, options.
- `OutboxCelery(Celery)` app class that intercepts `send_task()` and writes to outbox.
- Relay worker with `select_for_update(skip_locked=True)` for concurrent safety.
- Sentry trace propagation (traceparent + baggage headers).
- django-structlog context propagation via `bound_contextvars`.
- Management command `celery_outbox_relay` with configurable batch-size, idle-time, backoff-time, max-retries.
- Readonly Django admin for debugging.
- `CELERY_OUTBOX_EXCLUDE_TASKS` setting for selective bypass.
- Automatic `countdown` to absolute `eta` conversion.
- Partial index on pending messages for fast relay queries.
