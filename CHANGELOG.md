# Changelog

All notable changes to this project will be documented in this file.
This project adheres to [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).


## [0.2.0] — 2026-04-13

### Added
- **Dead letter support**: Messages exceeding max retries are moved to `CeleryOutboxDeadLetter` table instead of being deleted
- **Operator CLI commands**: `celery_outbox_stats` for queue metrics and `purge_dead_letter` for dead letter cleanup
- **Observability**: StatsD/DogStatsD metrics (messages_sent, send_latency, queue_depth, dead_letter_count, etc.)
- **PII redaction**: Configurable payload scrubbing for sensitive data in logs (`CELERY_OUTBOX_REDACT_FIELDS`)
- **Log sampling**: Reduce log volume with configurable sampling rates (`CELERY_OUTBOX_LOG_SAMPLE_RATE`)
- **Health check endpoint**: `/health/` returns queue_depth, oldest_pending, dead_letter_count
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
