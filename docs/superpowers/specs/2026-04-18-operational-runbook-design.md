# Operational Runbook - Design Spec

**Issue:** [#20](https://github.com/Barsoomx/django-celery-outbox/issues/20)
**Date:** 2026-04-18
**Status:** Approved

## Problem

Operators running `django-celery-outbox` in production have no playbook for incidents. When the outbox queue grows, the dead-letter table fills, or the relay stops processing, they must reconstruct the diagnosis path from first principles each time. There is also no written guidance on zero-downtime upgrades or rollback.

The existing docs cover the library's surface area (configuration, logging events, metrics, dead-letter purge), but do not connect those signals to the incident-response workflow that uses them.

The README's original "Health check endpoint for load balancer / k8s probes" feature claim has already been corrected in a prior change; this spec covers only the runbook gap.

## Goals

- One page an operator can open at 3am and follow without context.
- Cover the three incidents this library's design actually produces: queue growing, dead-letter-queue growing, relay hanging.
- Document zero-downtime upgrade and rollback with both deployment-agnostic principles and a concrete Kubernetes example.
- Provide a fast health-signal reference so every playbook can link back to it.
- Reuse existing docs via cross-reference; do not duplicate `troubleshooting.md`, `operations/health-checks.md`, `operations/dead-letter.md`, `deployment/kubernetes.md`, or `relay/tuning.md`.

## Non-Goals

- No `CREATE INDEX CONCURRENTLY` guidance. The `celery_outbox` table is near-empty in steady state; if it has grown enough to need concurrent indexing, the incident is "relay is down," not "the migration is slow." `CREATE INDEX CONCURRENTLY` also cannot run inside a transaction, which makes it fragile under Django migrate + Helm pre-upgrade hooks: a failed run leaves an `INVALID` index that blocks retries and requires manual `DROP INDEX` cleanup. Scope change is recorded on issue #20.
- No partitioning guidance for the outbox table, for the same reason.
- No backup/restore guidance specific to outbox tables. Standard Postgres backup covers `celery_outbox_dead_letter`.
- No library-shipped HTTP health endpoint. File-based liveness is the only one the package provides. An example user-built Django view is documented at `operations/health-checks.md` for load-balancer use.
- No auto-remediation scripts. The runbook tells operators what to do, not the system.
- No new library code. Documentation only.

## Decision

Single page, `docs/operations/runbook.md`, added to the mkdocs navigation under `Operations:`.

Page opens with a health-signal reference table so every playbook can link back. Incident playbooks follow a fixed shape (`Detect -> Triage -> Fix -> Verify`) for skim-under-pressure use. Upgrade and rollback are sibling sections, each written as "principles first, Kubernetes worked example second."

Length target: roughly 400-500 lines. Each incident playbook is approximately 60 lines. Upgrade and rollback carry more weight because of the worked examples.

## Design

### 1. File placement and navigation

- New file: `docs/operations/runbook.md`.
- `mkdocs.yml` nav gets one new entry at the end of the `Operations:` group, after `Health Checks: operations/health-checks.md`:

  ```yaml
  Operations:
    - Dead Letter Queue: operations/dead-letter.md
    - Admin Interface: operations/admin-interface.md
    - Health Checks: operations/health-checks.md
    - Runbook: operations/runbook.md
  ```

- No existing pages are renamed, split, or deleted.

### 2. Page structure

Top to bottom:

1. Intro paragraph - how to use the page (skim for the matching symptom, not read cover-to-cover).
2. Health interpretation reference - three compact tables plus a log-event pointer.
3. Incident playbooks - three self-contained sections.
4. Zero-downtime upgrade.
5. Rollback.

### 3. Health interpretation reference

Purely reference material. No prose between tables except a one-line caption.

**Table: Liveness file**

| Signal                       | Healthy                               | Stale                                                    |
| ---------------------------- | ------------------------------------- | -------------------------------------------------------- |
| mtime of `--liveness-file`   | within the configured freshness threshold | older -> relay stalled or dead -> "Relay hanging" playbook |

**Table: `celery_outbox_stats` snapshot**

| Field                         | Meaning                                     | Abnormal -> playbook                      |
| ----------------------------- | ------------------------------------------- | ----------------------------------------- |
| `queue_depth`                 | rows in `celery_outbox` awaiting send       | trending up -> "Queue growing"            |
| `oldest_pending_seconds`      | age of the oldest pending row (delivery latency) | above operator SLO -> "Queue growing" |
| `dlq_count`                   | rows in `celery_outbox_dead_letter`         | delta from baseline -> "DLQ growing"      |

Caption: "Point-in-time snapshot. Not a substitute for metrics over time."

**Table: Metrics for graphing and alerting**

StatsD names shown with the default `MONITORING_STATSD_PREFIX = 'celery_outbox'`. Prometheus-exported names (via statsd-exporter) replace dots with underscores.

| StatsD metric                         | Prometheus                                 | Type    | Use                                                                                |
| ------------------------------------- | ------------------------------------------ | ------- | ---------------------------------------------------------------------------------- |
| `celery_outbox.queue.depth`           | `celery_outbox_queue_depth`                | gauge   | Chart as time series; sawtooth is healthy, monotonic rise means queue is growing.  |
| `celery_outbox.oldest_pending_age_seconds` | `celery_outbox_oldest_pending_age_seconds` | gauge   | Alert on crossing SLO. Suggested starting point: 60s. Operator tunes to app need. |
| `celery_outbox.dead_letter.count`     | `celery_outbox_dead_letter_count`          | gauge   | Alert on delta after the baseline stabilizes.                                      |
| `celery_outbox.batch.duration_ms`     | `celery_outbox_batch_duration_ms`          | timing  | Chart to see per-batch processing time. Absence of new samples = relay stalled.    |

**Log events referenced in triage** (pointer bullet list, links to `observability/logging-events.md`):
- `celery_outbox_relay_started`
- `celery_outbox_batch_processed` (absence during steady send is a stall signal)
- `celery_outbox_send_failed`
- `celery_outbox_max_retries_exceeded`

**Explicit non-goals for this section** (one line each at the end of the reference):
- The library does not ship an HTTP health endpoint. File-based liveness is the only one provided; see `operations/health-checks.md` for a user-built view example.
- No auto-remediation. This page is for humans.

### 4. Incident playbook shape

Every playbook uses this fixed layout:

- **Detect** - the signal that fires this playbook.
- **Triage** - ordered checks, cheapest first. Numbered list so the operator can step through them.
- **Fix** - branching by triage result. Bulleted list with one-line action per branch.
- **Verify** - the signal that confirms recovery.

#### 4.1 Queue growing

**Detect**: `celery_outbox_oldest_pending_age_seconds` exceeds the operator's SLO (suggest 60s as a starting threshold). Secondary signal: `celery_outbox_queue_depth` trending up over 5-10 minutes.

**Triage** (cheapest first):

1. Relay running? Check pod status plus `--liveness-file` mtime.
2. Broker reachable from the relay? `celery -A <app> inspect ping` from inside the relay container.
3. One task type dominating the pending set? Run `celery_outbox_stats` or `SELECT task_name, COUNT(*) FROM celery_outbox GROUP BY task_name ORDER BY 2 DESC LIMIT 10`.
4. Did the app's send rate spike? Cross-check with app-level producer metrics.
5. Broker itself under load? Check broker admin UI.

**Fix**:

- Relay down -> jump to "Relay hanging" playbook.
- Broker unreachable -> operations-side issue on the broker; relay recovers on next poll when broker returns.
- One task dominating -> fix the producing code, or add the task to `CELERY_OUTBOX_EXCLUDE_TASKS` temporarily if the library is not a fit for that workload.
- Legitimate throughput -> scale relay replicas and/or increase `batch_size`. Cross-ref `relay/tuning.md`.

**Verify**: `celery_outbox_oldest_pending_age_seconds` trending down; `celery_outbox_queue_depth` draining.

#### 4.2 DLQ growing

**Detect**: `celery_outbox_dead_letter_count` grows beyond the operator's established baseline delta.

**Triage**:

1. Group by `failure_reason` - one error class or many?
2. Group by `task_name` - scoped to one task or broad?
3. Time distribution of `dead_at` - ongoing or a past spike already over?
4. Cross-reference with recent deploys, config changes, or broker incidents.

The first three are visible from Django admin filters or SQL. Item 4 comes from deploy/config/broker history outside the package.

**Fix**:

- Past broker outage, now recovered -> purge old records with `python manage.py celery_outbox_purge_dead_letter --older-than-dead 7d`. Cross-ref `operations/dead-letter.md`.
- Task name not registered on workers -> roll workers forward to include the task, or revert the producer deploy.
- Serialization errors -> fix the producing code and redeploy.
- **Re-injection is possible via the Django admin.** `CeleryOutboxDeadLetter` admin exposes the `retry_selected` action, which bulk-copies selected rows back into `celery_outbox` for another attempt. See `operations/admin-interface.md`. There is no management-command equivalent; admin or a custom management command are the supported paths.

**Verify**: `celery_outbox_dead_letter_count` flat; top `failure_reason` values no longer appearing in new rows.

#### 4.3 Relay hanging

**Detect**:

- Liveness probe failing (pod restart loop).
- `--liveness-file` mtime older than the configured freshness threshold.
- `celery_outbox_batch_processed` log event absent from the relay log.
- `celery_outbox_queue_depth` flat but non-zero while the app is still producing.

**Triage**:

1. Last log event and its timestamp from the relay pod - tells you where execution stalled.
2. DB lock contention:
   - PostgreSQL: `SELECT * FROM pg_locks WHERE relation = 'celery_outbox'::regclass`
   - MySQL 8: `SELECT * FROM performance_schema.data_locks WHERE OBJECT_NAME = 'celery_outbox'`
3. Broker send-ack blocking - is the relay waiting on network I/O to the broker?
4. Multiple-replica lock contention (already documented in `troubleshooting.md` - cross-ref it).

**Fix**:

- Lock contention with multiple relay replicas -> reduce replica count or `batch_size`.
- Broker-blocked -> broker recovery; relay resumes on next poll.
- Python-level hang -> restart the pod. If recurring, collect a `py-spy dump` trace next time for diagnosis.

**Verify**: liveness file touched recently; `celery_outbox_batch_processed` log events resumed.

### 5. Zero-downtime upgrade

**Principles** (platform-agnostic):

1. The relay must never run against a DB schema it does not understand. Migrate runs *before* new relay pods start.
2. Migrations should be additive when possible: add column, add table, add index. Additive changes let old and new relay versions coexist during a rolling update. For destructive changes (drop column, change type), use the two-release dance - first release stops using the field, second release removes it. Runbook states this so operators do not collapse it into one release.
3. SIGTERM must reach the relay. The relay's graceful-shutdown path drains the current batch and exits cleanly. Whatever platform runs the relay must deliver SIGTERM and wait, not SIGKILL.
4. Terminate grace period must be at least one batch duration plus margin. Otherwise the orchestrator kills the relay mid-batch, the at-least-once guarantee still holds but the operator sees spurious restarts.

**Kubernetes worked example**:

- Helm chart runs `python manage.py migrate` in a `pre-upgrade` hook (or a one-shot `Job` with an `helm.sh/hook: pre-upgrade` annotation). Concrete YAML snippet in the runbook.
- Relay `Deployment` uses `strategy: RollingUpdate` with `maxUnavailable: 0`.
- `terminationGracePeriodSeconds` set to at least one batch's worst-case duration, with margin.
- Liveness probe checks file freshness, not just file existence.
- Deployment spec fragment with the relevant fields annotated (template, not a drop-in).
- Verification steps after the upgrade: liveness file mtime refreshes, `celery_outbox_batch_processed` log events appear with the new pod names, metrics continue reporting.

### 6. Rollback

**Principles**:

1. Rolling back code is cheap. Rolling back schema is not. `helm rollback` (or equivalent) reverts image and config, not the database. The library's migrations use standard reversible Django operations (add column, add table, add index), so `python manage.py migrate django_celery_outbox <previous_migration>` can roll the schema back — but destructive reverses (dropping a column that now holds data) still lose rows. Verify the reverse is safe before running it.
2. Three scenarios, three procedures:
   - **Bad image, schema fine** -> standard rollback. Works because migrations are additive.
   - **Bad schema, needs reversal** -> run the reverse migration with `manage.py migrate django_celery_outbox <previous_migration>` *after* confirming it does not drop data you need. For non-trivial reverses (data transformations, dropping columns that have been written to) write a forward-fix migration instead.
   - **Corruption or data loss** -> out of scope. Point at standard Postgres point-in-time recovery and stop.
3. Watch the DLQ during rollback. A rollback that triggers incompatibility (workers on old code cannot deserialize tasks produced by the newer relay) shows up as DLQ growth. Link to the DLQ-growing playbook.

**Kubernetes worked example**:

- `helm rollback <release> <revision>` command.
- Verification: relay image tag reverted, `celery_outbox_batch_processed` log events continue, `celery_outbox_dead_letter_count` does not climb.
- Explicit warning box: "If your rollback involves schema, stop. Write a forward-fix migration instead."

### 7. Cross-references

The runbook links out rather than duplicates:

- `troubleshooting.md` - for symptom-to-command-snippet content that already exists.
- `operations/health-checks.md` - for the file-based liveness probe details.
- `operations/dead-letter.md` - for the purge command's full option surface.
- `deployment/kubernetes.md` - for general Kubernetes deployment layout.
- `relay/tuning.md` - for batch-size and replica-count guidance.
- `observability/logging-events.md` - for the full log-event catalogue.
- `observability/metrics.md` - for the full metric catalogue.

## Testing / verification

- Mkdocs strict build succeeds with the new file and nav entry. Run inside the project container with the `docs` extra installed: `docker compose run --rm app bash -c 'pip install -q -e .[docs] && mkdocs build --strict'`. The project Dockerfile installs `.[dev,test]` but not `.[docs]`, so this step installs the docs tooling on the fly.
- All internal links in the new page resolve to existing files.
- All referenced metric names match `docs/observability/metrics.md` and the Prometheus export convention (`celery_outbox_queue_depth`, `celery_outbox_oldest_pending_age_seconds`, `celery_outbox_dead_letter_count`, `celery_outbox_batch_duration_ms`).
- All referenced log event names exist in the current library (grep the strings in `django_celery_outbox/`).
- All referenced management commands exist (`celery_outbox_stats`, `celery_outbox_purge_dead_letter`, `celery_outbox_relay`).

No code changes, no unit tests. Verification is docs-build plus manual link and name check.

## Rollout

- One commit adds the new file and the mkdocs nav entry.
- PR references issue #20 with "Closes #20" in the description.
