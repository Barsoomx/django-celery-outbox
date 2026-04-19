# review-codex

Validated against current `HEAD` by direct code review plus container checks. This file intentionally lists only confirmed issues and confirmed operational gaps. Documented trade-offs and speculative claims from `review-claude-opus.md` are not copied here.

## Verification Basis

- `docker compose run --rm app python -m pytest` -> `466 passed`
- `docker compose run --rm app python -m ruff check .` -> pass
- `docker compose run --rm app python -m ruff format --check .` -> pass
- `docker compose run --rm app python -m mypy -p django_celery_outbox --config-file=pyproject.toml` -> pass
- `docker compose run --rm -e DB_ENGINE=mysql -e DB_HOST=mysql app python -m pytest django_celery_outbox/checks_tests.py tests/relay_tests.py` -> `94 passed`
- Targeted smoke-check in `docker compose`:
  - receiver exception on `outbox_message_created` raised `RuntimeError` while the outbox row was already persisted (`OUTBOX_COUNT 1`)
  - patched 3000-char `sentry_baggage` raised `DataError: value too long for type character varying(2048)`
- Built wheel inspected inside container: published artifact currently includes internal `*_tests.py` modules

## Confirmed From `review-claude-opus.md`

### Correctness and Reliability

1. `outbox_message_created` is emitted via plain `.send()` after the row insert and is not shielded from receiver exceptions.
   Evidence:
   - `django_celery_outbox/app.py:199-217`
   - `ARCHITECTURE.md:525-533`
   Impact:
   - outside `transaction.atomic()`, a receiver exception can bubble to the caller after durable enqueue; caller retry can create duplicate rows

2. `sentry_baggage` can break enqueue on legitimate long values because the model stores it in `CharField(max_length=2048)` with no truncation or validation.
   Evidence:
   - `django_celery_outbox/models.py:20-23`
   - `django_celery_outbox/app.py:208-210`
   Impact:
   - `send_task()` can fail with `DataError`, aborting the user transaction path

3. The relay breaker incorrectly defers remaining selected rows without re-checking `retries`, so already-exceeded rows can be pushed back instead of moving to DLQ.
   Evidence:
   - `django_celery_outbox/relay/_relay.py:280-290`
   - `django_celery_outbox/relay/_relay.py:301-313`
   Impact:
   - under persistent broker outage, pre-exceeded rows can stay in outbox indefinitely

4. The outage streak resets at the start of every batch, making the circuit breaker effectively batch-local.
   Evidence:
   - `django_celery_outbox/relay/_policy.py:31-32`
   - `django_celery_outbox/relay/_relay.py:259`
   Impact:
   - low-volume deployments or `batch_size=1` may never accumulate enough consecutive outages to enter cooldown

### Docs and Release Integrity

5. `CHANGELOG.md` for `0.2.0` advertises features that are not implemented in the codebase.
   Evidence:
   - `CHANGELOG.md:33-35` mentions `CELERY_OUTBOX_REDACT_FIELDS`, `CELERY_OUTBOX_LOG_SAMPLE_RATE`, and a built-in `/health/`
   - grep across `django_celery_outbox`, `docs`, and `README.md` finds no implementation for the first two
   - `docs/operations/health-checks.md:71-81` explicitly says the package does not ship an HTTP health endpoint
   Impact:
   - operators can configure against features that do not exist

6. Kubernetes deployment docs recommend `terminationGracePeriodSeconds: 30`, which is shorter than the package's own documented shutdown requirement.
   Evidence:
   - `docs/deployment/kubernetes.md:81-86`
   - `docs/operations/runbook.md:202-204`
   Impact:
   - users following the short example can force SIGKILL during drain and trigger duplicate-tolerant recovery on every rollout

7. The published wheel currently includes internal test modules because packaging is too broad.
   Evidence:
   - `pyproject.toml:76-77`
   - inspected wheel contains `django_celery_outbox/admin_tests.py`, `integration_tests.py`, `fixtures_plugin_tests.py`, and other `*_tests.py` modules
   Impact:
   - unnecessary package bloat and risk of downstream pytest collection surprises

8. The publish workflow validates metadata but does not install and smoke-test the built artifact before publishing to PyPI.
   Evidence:
   - `.github/workflows/publish.yml:26-37`
   Impact:
   - packaging regressions can ship even if source-tree tests are green

### Ops and Performance

9. Dead-letter replay has no built-in CLI path; the documented supported replay path is Django admin only.
   Evidence:
   - `docs/operations/dead-letter.md:38-49`
   Impact:
   - large DLQ replay during incidents is awkward to automate

10. Each relay cycle performs repeated queue-wide aggregation work: outbox count, DLQ count, and oldest-pending lookup.
    Evidence:
    - `django_celery_outbox/relay/_relay.py:137-147`
    Impact:
    - under large backlog this adds repeated scan cost to the hot path

11. Queue stats command performs the same expensive patterns and adds a `GROUP BY task_name` over the live outbox.
    Evidence:
    - `django_celery_outbox/stats.py:65-85`
    Impact:
    - safe for snapshots, but not cheap at large table sizes

12. Index coverage is insufficient for the full pending/retry/stale selector and for DLQ retention queries.
    Evidence:
    - pending selector: `django_celery_outbox/relay/_message_selector.py:12-16`
    - outbox indexes: `django_celery_outbox/models.py:29-35`
    - DLQ model lacks indexes on `dead_at` / `created_at`: `django_celery_outbox/models.py:49-74`
    - initial migration matches that shape: `django_celery_outbox/migrations/0001_initial.py:33-63`
    Impact:
    - retry/stale backlog and purge workloads can devolve into broader scans than necessary

13. The packaged alert example uses `up{job="celery-outbox-relay"}`, but the package does not ship a scrape target that would create that series.
    Evidence:
    - `docs/observability/alert-rules.yml:42-49`
    - `docs/operations/runbook.md:57-60`
    Impact:
    - copied alert rules can silently never fire

14. The package has no producer-side enqueue metric.
    Evidence:
    - `django_celery_outbox/app.py:195-222` writes the row and emits the signal, but no metrics call exists
    - `docs/observability/metrics.md:23-32` lists only relay-side queue/send/failure metrics
    Impact:
    - operators cannot compare `enqueued` vs `published` without building their own instrumentation

15. Package integration tests do not exercise the real broker send path and globally patch connection recycling.
    Evidence:
    - `django_celery_outbox/integration_tests.py:47-56`
    Impact:
    - broker semantics and some database-connection behaviors are not covered by the current "integration" suite

## Additional Confirmed Findings (Codex)

1. Observability docs and bundled alerts do not cover the relay's top-level generic failure event.
   Evidence:
   - code emits `celery_outbox_relay_iteration_failed`: `django_celery_outbox/relay/_relay.py:79-91`
   - logging catalog omits it: `docs/observability/logging-events.md:1-184`
   - runbook triage event list omits it: `docs/operations/runbook.md:45-55`
   - bundled alerts omit it: `docs/observability/alert-rules.yml:1-49`
   Impact:
   - the relay can fail in its most generic way without a first-class documented operator workflow

2. Metrics and alert guidance under-cover broker-outage states.
   Evidence:
   - outage path defers messages without incrementing `messages.failed`: `django_celery_outbox/relay/_relay.py:301-314`
   - metrics docs recommend `messages.failed > 0` to check broker connectivity: `docs/observability/metrics.md:76-80`
   - bundled alerts do not include breaker-open/trip or delayed-delivery-setup-failed conditions: `docs/observability/alert-rules.yml:1-49`
   Impact:
   - a healthy-but-not-delivering relay can be missed unless users add their own log-based alerting

3. Django admin undercounts live backlog by treating only `updated_at IS NULL` rows as pending.
   Evidence:
   - admin summary: `django_celery_outbox/admin.py:69-79`
   - relay also uses deferred/retry/in-flight rows: `django_celery_outbox/relay/_message_selector.py:12-16`, `django_celery_outbox/relay/_mutations.py:37-54`
   Impact:
   - operators can see a small "pending" count while substantial retry/deferred backlog still exists

4. Database setup docs conflict with the security guide.
   Evidence:
   - setup docs recommend `GRANT ALL PRIVILEGES`: `docs/deployment/database-setup.md:13-17`, `docs/deployment/database-setup.md:35-39`
   - security guide recommends minimal permissions: `docs/security.md:77-80`
   Impact:
   - the official operator path currently points to over-privileged database accounts

5. Compatibility metadata overstates what CI actually verifies.
   Evidence:
   - package classifiers claim Django `5.0` and `5.1`: `pyproject.toml:27-32`
   - CI matrix only tests `4.2` and `5.2`: `.github/workflows/tests.yml:67-70`
   Impact:
   - users may rely on compatibility that is declared but not continuously tested

6. GitHub Actions are pinned to moving tags instead of immutable SHAs.
   Evidence:
   - `.github/workflows/tests.yml:24-27`, `.github/workflows/tests.yml:43-48`, `.github/workflows/tests.yml:129-135`
   - `.github/workflows/publish.yml:20-24`, `.github/workflows/publish.yml:34-35`
   - `.github/workflows/docs.yml:18-21`
   Impact:
   - CI and release pipeline inherit upstream tag-retargeting risk

7. Example-project CI runs only when `examples/**` changes.
   Evidence:
   - `.github/workflows/example.yml:3-7`
   Impact:
   - a library change can break the documented example with no CI signal

8. Alert thresholds for dead letters are inconsistent across docs.
   Evidence:
   - metrics guide says `dead_letter.count > 10`: `docs/observability/metrics.md:78-80`
   - dead-letter ops page says alert on `dead_letter.count > 0`: `docs/operations/dead-letter.md:109-113`
   Impact:
   - operators get conflicting alert policy depending on which doc they follow

## Validated Important Nice-to-Haves

These are not current defects. They are reasonable follow-up improvements that fit this codebase and would materially improve production-readiness without drifting into obvious overengineering.

1. Collapse selector claim + mark-in-flight into a single SQL step where the backend allows it.
   Evidence:
   - selector currently does a read phase and then a separate update phase: `django_celery_outbox/relay/_message_selector.py:24-43`
   Why it matters:
   - removes one DB round trip from every batch and narrows the time window between claim and in-flight marking

2. Add a bounded parallel publish mode for high-throughput deployments, e.g. via `ThreadPoolExecutor`.
   Evidence:
   - relay publish path is strictly serial today: `django_celery_outbox/relay/_relay.py:261-357`
   Why it matters:
   - current throughput scales roughly with broker round-trip time; bounded parallelism is the clearest path to materially higher publish throughput

3. Reduce redactor-path copy cost when a PII redactor is configured.
   Evidence:
   - producer path always `deepcopy()`s args and kwargs before calling the redactor: `django_celery_outbox/app.py:174-180`
   Why it matters:
   - this is avoidable producer-side CPU and allocation overhead on every send when redaction is enabled

4. Add a Django system check for `CELERY_OUTBOX_PII_REDACTOR` importability and callable shape.
   Evidence:
   - current checks validate app path, excluded tasks, DB capability, and migrations, but nothing for the redactor: `django_celery_outbox/checks.py:43-180`
   - the redactor is resolved lazily from settings at send time: `django_celery_outbox/app.py:18-25`
   Why it matters:
   - catches bad redactor configuration at startup instead of failing on the first production enqueue

5. Add startup validation for `CELERY_OUTBOX_DLQ_RETENTION`.
   Evidence:
   - invalid retention is discovered only when the purge task or purge command runs: `django_celery_outbox/tasks.py:11-23`, `django_celery_outbox/management/commands/celery_outbox_purge_dead_letter.py:37-52`
   - current system checks do not cover it: `django_celery_outbox/checks.py:43-180`
   Why it matters:
   - prevents "first failure happens at 3am when the scheduled purge starts" class of operational surprise

6. Stabilize the public pytest-plugin dependency surface instead of relying on private internals.
   Evidence:
   - packaged pytest plugin entry point is public: `pyproject.toml:70-71`
   - plugin fixtures import private `_settings.load_celery_app_setting`: `django_celery_outbox/fixtures.py:206`, `django_celery_outbox/fixtures.py:261`
   - plugin also patches private relay/publisher internals: `django_celery_outbox/fixtures.py:251-254`, `django_celery_outbox/fixtures.py:276-278`
   Why it matters:
   - once the plugin is part of the public package, private implementation churn can break the library's own supported testing surface

7. Document the signal kwargs contract explicitly.
   Evidence:
   - public signals are bare `Signal()` declarations: `django_celery_outbox/signals.py:1-6`
   - the package exposes them from the top-level module: `django_celery_outbox/__init__.py:11-24`
   Why it matters:
   - signals are public API, but consumers currently have to reverse-engineer payload shape from implementation and tests

8. Implement chunked dead-letter purge for large delete workloads.
   Evidence:
   - purge currently aggregates once and then executes a single `queryset.delete()`: `django_celery_outbox/purge.py:75-81`
   Why it matters:
   - safer for large DLQ tables, WAL growth, replication lag, and long-running delete transactions

9. Extend redaction coverage to serialized callback signatures, not only top-level task args/kwargs.
   Evidence:
   - producer redaction hook only sees `task_name`, `args`, and `kwargs`: `django_celery_outbox/app.py:27-40`
   - callbacks and chains are serialized separately into `options`: `django_celery_outbox/serialization.py:174-181`, `django_celery_outbox/serialization.py:194-204`
   Why it matters:
   - users can still persist sensitive payloads indirectly through `link`, `link_error`, `chain`, or `chord` even when they configured a redactor
