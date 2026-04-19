# Changelog

All notable changes to this project will be documented in this file.
This project adheres to [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- Release artifacts now exclude internal `*_tests.py` modules from built wheels and source distributions.
- Release publishing now runs built-artifact and changelog contract checks before PyPI upload.
- CI now includes a dedicated live RabbitMQ smoke lane for Django 5.0 and 5.1.


## [0.3.0] — 2026-04-19

### Added
- **Public pytest plugin**: `pytest11` entry point and reusable fixtures for package consumers, including `outbox`, `drain_outbox`, `fake_relay`, and `assert_task_sent`
- **Django system checks**: validation for `CELERY_OUTBOX_APP`, `CELERY_OUTBOX_EXCLUDE_TASKS`, database capabilities, and migration/schema state before runtime failures reach production
- **Relay resilience controls**: broker outage circuit breaker, configurable send timeout, capped backoff, broker-outage cooldown, and bounded shutdown drain window
- **Operational runbook coverage**: new troubleshooting and operations docs for relay behavior, health checks, and failure recovery

### Changed
- **Relay internals**: split the relay into focused selector, publisher, mutation, runtime, and policy components for easier testing and safer evolution
- **Producer contract hardening**: `outbox_message_created` now uses `send_robust()`, receiver failures log `celery_outbox_signal_error` instead of aborting enqueue, and `messages.enqueued` is emitted only after commit
- **Failure handling semantics**: broker outages are now deferred without consuming retry budget, while non-outage failures continue through normal retry/dead-letter flow
- **Tracing compatibility**: `sentry_baggage` now persists as `TextField` storage in both outbox and dead-letter tables so valid long baggage values are preserved
- **Testing story**: package-level pytest integration is now documented and exercised through wheel/plugin tests, making third-party integration tests easier to write
- **Dependency maintenance**: bumped `pytest` from `9.0.2` to `9.0.3`

### Fixed
- **Build cache reliability**: wheel/build cache handling is more predictable in local and CI packaging flows
- **Relay robustness**: top-level relay loop now survives iteration failures, keeps liveness/metrics fresh during breaker cooldowns, and respects shutdown deadlines while draining
- **Configuration feedback**: invalid `CELERY_OUTBOX_PII_REDACTOR`, invalid `CELERY_OUTBOX_DLQ_RETENTION`, and unsupported database setups now fail fast with explicit Django check output instead of surfacing later as runtime surprises


## [0.2.0] — 2026-04-13

### Added
- **Dead letter support**: Messages exceeding max retries are moved to `CeleryOutboxDeadLetter` table instead of being deleted
- **Operator CLI commands**: `celery_outbox_stats` for queue metrics and `purge_dead_letter` for dead letter cleanup
- **Observability**: StatsD/DogStatsD metrics (messages_sent, send_latency, queue_depth, dead_letter_count, etc.)
- **Schema versioning**: `schema_version` field for safe format migrations
- **Example project**: Full Django + Celery + RabbitMQ example in `examples/minimal_django/`
- **MkDocs documentation**: Comprehensive docs site with operations, observability, and tuning guides
- **CI security scanning**: CodeQL, pip-audit, and Bandit integration
- **Database validation**: Startup checks for required database features
- **Native delayed delivery**: Relay auto-declares Celery delayed exchanges for countdown/ETA tasks
- **Django signals**: `outbox_message_created`, `outbox_message_sent`, `outbox_message_failed`, `outbox_message_dead_lettered`
- **Cardinality control**: Limit unique tag values to prevent metric explosion

### Changed
- **Relay refactoring**: Extracted `MessageSelector`, `MessageProcessor`, `MetricsEmitter` for better testability
- **Retry logic**: Improved exponential backoff with jitter
- **Graceful shutdown**: Enhanced SIGTERM/SIGINT handling with drain timeout

### Fixed
- Celery 5.6 compatibility: Use `dict(sig)` instead of removed `Signature.as_dict()`
- GitHub Actions workflow permissions for code scanning
- Documentation build and deployment


## [0.1.0] — 2025-01-15

### Added
- `CeleryOutbox` model with JSON fields for args, kwargs, options
- `OutboxCelery(Celery)` app class that intercepts `send_task()` and writes to outbox
- Relay worker with `select_for_update(skip_locked=True)` for concurrent safety
- Sentry trace propagation (traceparent + baggage headers)
- django-structlog context propagation via `bound_contextvars`
- Management command `celery_outbox_relay` with configurable batch-size, idle-time, backoff-time, max-retries
- Readonly Django admin for debugging
- `CELERY_OUTBOX_EXCLUDE_TASKS` setting for selective bypass
- Automatic `countdown` to absolute `eta` conversion
- Partial index on pending messages for fast relay queries
