# Changelog

All notable changes to this project will be documented in this file.
This project adheres to [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- The package test suite collects with every `pytest-django` release allowed by the `test` extra (`>=4.5`): `checks_tests` imports `DjangoDbBlocker` only for type checking, since `pytest-django` 4.5–4.7 does not export it.
- `celery_outbox.E005`/`E006` no longer walk the call stack unless the outbox alias is selected, so plain `check`, `makemigrations`, and `runserver` on Django < 6.1 skip the `migrate` detection entirely. The stack walk starts at the caller's frame and drops its frame reference on exit, so it no longer leaves a frame reference cycle for the garbage collector.

### Documentation
- The database checks (`celery_outbox.E001`, `E005`, `E006`) run for selected databases, not only with `--database`: on Django 6.1+, `python manage.py check --tag database` without `--database` selects every configured database and runs them against the outbox alias; on Django < 6.1 the same command skips them. Getting started, configuration, and architecture docs now say so.


## [0.4.1] — 2026-10-04

### Changed
- Plain `python manage.py check` (without `--database`) no longer verifies `SKIP LOCKED` support or the outbox schema. Deployment pipelines that relied on it to gate releases on the outbox schema must run `python manage.py check --database <alias>` with the alias that stores the outbox tables.

### Fixed
- Database system checks (`celery_outbox.E001`, `E005`, `E006`) honour the `databases` argument of the Django check framework: they only inspect the outbox database when its alias is explicitly selected (`check --database <alias>`, the Django test runner, and `migrate` for `E001`). On Django < 6.1, where `run_checks()` still calls database-tagged checks when no database is selected, a fresh, unmigrated, or unreachable database no longer fails `check` without `--database`, `makemigrations` (including `makemigrations --check`), `runserver`, and other commands that run all system checks (`requires_system_checks = '__all__'`) with `celery_outbox.E006`. Django 6.1 already skips database-tagged checks when no database is selected and no tag is requested.
- `migrate` detection for skipping `E005`/`E006` is exact: the schema checks are skipped only when `migrate` is the management subcommand (`manage.py migrate`, `django-admin migrate`, `python -m django migrate`) or when a `migrate` command instance is running, including programmatic `call_command('migrate')` on Django 5.2+, where system checks run before `handle()`. A `migrate` token elsewhere on the command line, such as `check --database migrate`, no longer suppresses them.


## [0.4.0] — 2026-04-20

### Added
- Bounded parallel publish mode via `--publish-concurrency` (default `1`; serial remains the default).
- `--queue-snapshot-refresh-seconds` knob for sampled queue-wide gauge cadence.
- `celery_outbox_replay_dead_letter` management command for DLQ recovery (explicit IDs, `--limit`, shared helper with admin bulk action).
- Producer-side `messages.enqueued` counter emitted on commit.
- System checks `celery_outbox.E007` (invalid `CELERY_OUTBOX_PII_REDACTOR`) and `E008` (invalid `CELERY_OUTBOX_DLQ_RETENTION`).
- Admin summary exposes `live_backlog` and `never_attempted` counts aligned with relay selector semantics.
- Inspection-time nested signature redaction for `link`, `link_error`, `chain`, and `chord` payloads.
- Live RabbitMQ smoke CI lane and parallel broker smoke lane gating release.
- Built-artifact smoke (`scripts/smoke_installed_wheel.py`) and changelog contract check (`scripts/check_release_contract.py`).
- Codecov coverage reporting.

### Changed
- Release artifacts exclude internal `*_tests.py` modules from built wheels and source distributions.
- Release publishing runs built-artifact and changelog contract checks before PyPI upload.
- CI covers dedicated Django 5.0/5.1 compatibility smoke, live RabbitMQ smoke, and release-gating parallel broker smoke.
- Relay queue-wide gauges (`queue.depth`, `dead_letter.count`, `oldest_pending_age_seconds`) are now sampled snapshots with bounded refresh cadence instead of exact per-batch recomputations.
- `celery_outbox_stats` defaults to `--top=0`, making the expensive live `GROUP BY task_name` drilldown opt-in.
- Broker-outage streak tracking accumulates across batch boundaries until a successful publish or cooldown reset.
- Dead-letter purge executes ordered chunked deletes instead of one large transaction.
- All package-owned signal emission goes through `send_robust()` with receiver tracebacks preserved in `celery_outbox_signal_error` logs.
- `sentry_baggage` storage widened to `TextField` in outbox and dead-letter tables.
- Public pytest fixtures delegate to a package-owned `_fixture_support` module; no private internals imported.
- Example workflow installs the built wheel artifact instead of the source tree.
- GitHub Actions pinned to immutable SHAs across release-critical workflows.
- DB setup docs reworked to least-privilege roles; alert rules standardized on rolling-window dead-letter signal.
- Kubernetes `terminationGracePeriodSeconds` example aligned with shutdown + send timeouts.

### Fixed
- Breaker trip mid-batch correctly routes already-exceeded rows to DLQ instead of deferring them with the rest.
- `replay_dead_letters()` uses the outbox DB alias and `select_for_update` for multi-DB and concurrent safety.
- `celery_outbox_purge_dead_letter` reuses the validated DLQ retention parser instead of reading settings directly.
- Duplicate `retry_after` index removed (migration `0006`, superseded by `(retry_after, id)`).
- Long `sentry_baggage` values no longer raise `DataError` on enqueue.
- Connection-recycling patches no longer applied globally across the test suite.

### Removed
- `up{job="celery-outbox-relay"}` from bundled alert examples (package does not provide that scrape target).
- Ghost CHANGELOG entries that advertised unshipped features (PII redaction, log sampling, health endpoint).


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
