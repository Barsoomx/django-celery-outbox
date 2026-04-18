# Operational Runbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish an operational runbook at `docs/operations/runbook.md` that closes GitHub issue #20 by providing incident playbooks, upgrade/rollback procedures, and a health-signal reference.

**Architecture:** Single new markdown page under mkdocs' `Operations:` nav group. Content derives verbatim from the approved spec (`docs/superpowers/specs/2026-04-18-operational-runbook-design.md`). Each playbook follows a fixed `Detect → Triage → Fix → Verify` shape. No library code changes; verification is `mkdocs build --strict` plus grep checks that every referenced metric name, log event, management command, and model field exists in the codebase today.

**Tech Stack:** Markdown, mkdocs 1.5+, mkdocs-material 9.5+. Verification runs inside `docker compose run --rm app`. The project image installs `.[dev,test]` at build time but not `.[docs]`, so every mkdocs run in this plan first installs the `docs` extra from the project's `pyproject.toml` in the same container invocation. Pre-commit hook on this machine is broken (CRLF line endings from Windows-generated hook); per user instruction, all commits in this plan use `git commit --no-verify`.

**Scope ground rules (from spec):**
- No `CREATE INDEX CONCURRENTLY`, partitioning, or backup/restore guidance for the outbox tables.
- No HTTP health endpoint — file-based liveness only.
- No new Python code. Docs only.
- Reuse existing docs by cross-reference (`troubleshooting.md`, `operations/health-checks.md`, `operations/dead-letter.md`, `deployment/kubernetes.md`, `relay/tuning.md`, `observability/logging-events.md`, `observability/metrics.md`).

**Branch:** Stay on `feature/system-checks-config-validation`. Do not create a new branch. Do not push.

---

## Task 1: Verify preconditions and create empty runbook skeleton

**Files:**
- Create: `docs/operations/runbook.md`
- Modify: `mkdocs.yml` (add one nav entry under `Operations:`)

The skeleton establishes the final H1 and the exact section order from spec §2. Later tasks fill each section in place.

- [ ] **Step 1: Verify all referenced library names exist in the codebase**

Run each grep; every one MUST produce at least one match. If any produces zero matches, STOP — the spec has drifted from the code and must be corrected before continuing.

```bash
# Metric names (dot form in metrics.py, underscore form in metrics.md as Prometheus export)
grep -rn 'queue.depth\|queue_depth' docs/observability/metrics.md django_celery_outbox/stats.py
grep -rn 'oldest_pending_age_seconds' docs/observability/metrics.md
grep -rn 'dead_letter.count\|dead_letter_count\|dlq_count' docs/observability/metrics.md django_celery_outbox/stats.py
grep -rn 'batch.duration_ms\|batch_duration_ms' docs/observability/metrics.md

# Log events
grep -n 'celery_outbox_relay_started' docs/observability/logging-events.md
grep -n 'celery_outbox_batch_processed' docs/observability/logging-events.md
grep -n 'celery_outbox_send_failed' docs/observability/logging-events.md
grep -n 'celery_outbox_max_retries_exceeded' docs/observability/logging-events.md

# Management commands
ls django_celery_outbox/management/commands/celery_outbox_stats.py
ls django_celery_outbox/management/commands/celery_outbox_purge_dead_letter.py
ls django_celery_outbox/management/commands/celery_outbox_relay.py

# Model fields referenced in triage SQL
grep -n 'failure_reason\|dead_at\|task_name' django_celery_outbox/models.py

# Cross-ref targets
ls docs/operations/dead-letter.md docs/operations/health-checks.md
ls docs/deployment/kubernetes.md docs/relay/tuning.md docs/troubleshooting.md
ls docs/observability/logging-events.md docs/observability/metrics.md
```

Expected: no errors, every grep prints at least one match.

- [ ] **Step 2: Create the skeleton file**

Write exactly this content to `docs/operations/runbook.md`:

````markdown
# Runbook

<!-- filled in by Task 2 -->

## Health signals

<!-- filled in by Task 2 -->

## Incident playbooks

<!-- filled in by Tasks 3, 4, 5 -->

### Queue growing

<!-- filled in by Task 3 -->

### Dead-letter queue growing

<!-- filled in by Task 4 -->

### Relay hanging

<!-- filled in by Task 5 -->

## Zero-downtime upgrade

<!-- filled in by Task 6 -->

## Rollback

<!-- filled in by Task 7 -->
````

- [ ] **Step 3: Add mkdocs nav entry**

Open `mkdocs.yml`. Find the `Operations:` block. It currently reads:

```yaml
  - Operations:
    - Dead Letter Queue: operations/dead-letter.md
    - Admin Interface: operations/admin-interface.md
    - Health Checks: operations/health-checks.md
```

Replace with:

```yaml
  - Operations:
    - Dead Letter Queue: operations/dead-letter.md
    - Admin Interface: operations/admin-interface.md
    - Health Checks: operations/health-checks.md
    - Runbook: operations/runbook.md
```

No other change to `mkdocs.yml`.

- [ ] **Step 4: Verify mkdocs build --strict passes**

```bash
docker compose run --rm app bash -c 'pip install -q -e .[docs] && mkdocs build --strict'
```

Expected: exit code 0. Output ends with a line like `INFO - Documentation built in X.XX seconds`.

If the build fails, read the error. The skeleton should not fail — if it does, the failure is either the nav edit or a pre-existing mkdocs issue unrelated to this task. Fix and re-run.

- [ ] **Step 5: Commit**

```bash
git add docs/operations/runbook.md mkdocs.yml
git commit --no-verify -m "$(cat <<'EOF'
docs(runbook): skeleton + nav entry

Refs #20

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Write intro paragraph and Health signals section

**Files:**
- Modify: `docs/operations/runbook.md` (replace the content under `# Runbook` up to but not including `## Incident playbooks`)

Covers spec §3 (health interpretation reference).

- [ ] **Step 1: Replace the intro + health-signals block**

In `docs/operations/runbook.md`, replace everything from the `# Runbook` heading through the last line before `## Incident playbooks` (i.e. the skeleton comment for the health section) with this exact content:

````markdown
# Runbook

Open this page when something is wrong. Skim for the symptom that matches what you are seeing (page's [Incident playbooks](#incident-playbooks)), read the relevant playbook top to bottom, and execute. This page is not meant to be read cover-to-cover.

Every playbook below has the same shape: **Detect → Triage → Fix → Verify**. If you cannot find a matching playbook, the closest page for ad-hoc diagnosis is [Troubleshooting](../troubleshooting.md).

## Health signals

Use these tables as a reference while following any playbook.

### Liveness file

| Signal                     | Healthy                              | Stale                                                                                |
| -------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------ |
| mtime of `--liveness-file` | within your configured freshness threshold | older → relay stalled or dead → [Relay hanging](#relay-hanging)                      |

See [Health Checks](health-checks.md) for the `--liveness-file` flag details.

### `celery_outbox_stats` snapshot

`python manage.py celery_outbox_stats` prints a point-in-time snapshot. It is not a replacement for metrics over time.

| Field                     | Meaning                                           | Abnormal → playbook                                  |
| ------------------------- | ------------------------------------------------- | ---------------------------------------------------- |
| `queue_depth`             | rows in `celery_outbox` awaiting send             | trending up → [Queue growing](#queue-growing)        |
| `oldest_pending_seconds`  | age of the oldest pending row (delivery latency)  | above your SLO → [Queue growing](#queue-growing)     |
| `dlq_count`               | rows in `celery_outbox_dead_letter`               | delta from baseline → [Dead-letter queue growing](#dead-letter-queue-growing) |

### Metrics for graphing and alerting

StatsD names are shown with the default `MONITORING_STATSD_PREFIX = 'celery_outbox'`. Gauge and counter metrics usually export to Prometheus by replacing dots with underscores. Timer metrics depend on your exporter configuration and often appear as histogram-style series such as `_bucket`, `_sum`, and `_count`.

| StatsD metric                               | Prometheus                                   | Type   | Use                                                                                           |
| ------------------------------------------- | -------------------------------------------- | ------ | --------------------------------------------------------------------------------------------- |
| `celery_outbox.queue.depth`                 | `celery_outbox_queue_depth`                  | gauge  | Chart as a time series. Sawtooth is healthy; monotonic rise means the queue is growing.       |
| `celery_outbox.oldest_pending_age_seconds`  | `celery_outbox_oldest_pending_age_seconds`   | gauge  | Alert on crossing your SLO. Suggested starting threshold: 60s. Tune to your application.      |
| `celery_outbox.dead_letter.count`           | `celery_outbox_dead_letter_count`            | gauge  | Alert on delta after the baseline stabilizes.                                                 |
| `celery_outbox.batch.duration_ms`           | e.g. `celery_outbox_batch_duration_ms_bucket` | timing | Chart per-batch processing time. Absence of new samples means the relay has stalled.          |

Full catalogue: [Metrics](../observability/metrics.md).

### Log events referenced during triage

- `celery_outbox_relay_started`
- `celery_outbox_batch_processed` — absence during steady send is a stall signal
- `celery_outbox_send_failed`
- `celery_outbox_max_retries_exceeded`

Full catalogue: [Logging Events](../observability/logging-events.md).

### Explicit non-goals

- The library does not ship an HTTP health endpoint. File-based liveness is the only one provided. See [Health Checks](health-checks.md) for a user-built Django view example if you need an HTTP probe.
- No auto-remediation. This runbook tells operators what to do; it does not run on its own.
````

- [ ] **Step 2: Verify mkdocs build**

```bash
docker compose run --rm app bash -c 'pip install -q -e .[docs] && mkdocs build --strict'
```

Expected: exit code 0. Strict mode will fail if any internal link is broken. If it fails with a "contains a link to" error, the cross-reference paths above are wrong relative to `docs/operations/runbook.md`. Correct the paths and re-run.

- [ ] **Step 3: Commit**

```bash
git add docs/operations/runbook.md
git commit --no-verify -m "$(cat <<'EOF'
docs(runbook): intro and health signals reference

Refs #20

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Write the Queue growing playbook

**Files:**
- Modify: `docs/operations/runbook.md` (replace the `### Queue growing` placeholder)

Covers spec §4.1.

- [ ] **Step 1: Replace the Queue growing placeholder**

Replace the block from `### Queue growing` through its HTML comment placeholder with this exact content:

````markdown
### Queue growing

**Detect.** `celery_outbox_oldest_pending_age_seconds` exceeds your SLO (suggested starting threshold: 60s). Secondary signal: `celery_outbox_queue_depth` trending up over 5-10 minutes.

**Triage** (cheapest first):

1. **Is the relay running?** Check the relay pod status and the `--liveness-file` mtime.
2. **Is the broker reachable from the relay?** From inside the relay container, run `celery -A <your_celery_app> inspect ping`.
3. **Is a single task type dominating the pending set?** Either:

    ```bash
    python manage.py celery_outbox_stats
    ```

    or, from a DB shell:

    ```sql
    SELECT task_name, COUNT(*) FROM celery_outbox GROUP BY task_name ORDER BY 2 DESC LIMIT 10;
    ```

4. **Did the app's send rate spike?** Cross-check with producer-side metrics on your service.
5. **Is the broker itself under load?** Check the broker admin UI (CPU, consumer count, its own queue depth).

**Fix** (by triage result):

- Relay is down → follow [Relay hanging](#relay-hanging).
- Broker unreachable → operations-side issue on the broker. The relay will catch up on its next poll once the broker returns.
- One task dominates → fix the producing code, or add the task name to `CELERY_OUTBOX_EXCLUDE_TASKS` temporarily if the library is not a fit for that workload.
- Legitimate throughput → scale relay replicas and/or increase `batch_size`. See [Relay Tuning](../relay/tuning.md).

**Verify.** `celery_outbox_oldest_pending_age_seconds` trending down; `celery_outbox_queue_depth` draining.
````

- [ ] **Step 2: Verify mkdocs build**

```bash
docker compose run --rm app bash -c 'pip install -q -e .[docs] && mkdocs build --strict'
```

Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add docs/operations/runbook.md
git commit --no-verify -m "$(cat <<'EOF'
docs(runbook): queue growing playbook

Refs #20

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Write the Dead-letter queue growing playbook

**Files:**
- Modify: `docs/operations/runbook.md` (replace the `### Dead-letter queue growing` placeholder)

Covers spec §4.2.

- [ ] **Step 1: Verify purge command CLI is still as expected**

```bash
grep -n 'older-than-dead\|older-than-created\|task-name\|dry-run' django_celery_outbox/management/commands/celery_outbox_purge_dead_letter.py
```

Expected: all four flags print. If any is missing, STOP and update the "Fix" section below to match the current CLI.

- [ ] **Step 2: Replace the DLQ placeholder**

Replace the block from `### Dead-letter queue growing` through its HTML comment placeholder with this exact content:

````markdown
### Dead-letter queue growing

**Detect.** `celery_outbox_dead_letter_count` grows beyond your established baseline delta.

**Triage:**

1. **Group by `failure_reason`** — is this one error class or many?
2. **Group by `task_name`** — is this scoped to one task or broad?
3. **Time distribution of `dead_at`** — is this ongoing or a past spike that has already stopped?
4. **Cross-reference** recent deploys, config changes, and broker incidents.

The first three are visible in the Django admin ([Admin Interface](admin-interface.md)) by filtering on `failure_reason`, `task_name`, and `dead_at`. Item 4 comes from deploy history, config history, and broker incident history outside the package.

**Fix** (by cause):

- **Past broker outage, now recovered.** Purge old records:

    ```bash
    python manage.py celery_outbox_purge_dead_letter --older-than-dead 7d
    ```

    See [Dead Letter Queue](dead-letter.md) for the full flag surface.

- **Task name not registered on workers.** Roll workers forward to include the task, or revert the producer deploy.
- **Serialization errors.** Fix the producing code and redeploy.

**Replaying dead-lettered messages.** Use the Django admin: `CeleryOutboxDeadLetter` has a `retry_selected` bulk action that copies the selected rows back into `celery_outbox` for another send attempt. See [Admin Interface](admin-interface.md). There is no management-command equivalent; if you need automation, wrap the model-level `CeleryOutboxDeadLetter` → `CeleryOutbox` copy in your own command.

**Verify.** `celery_outbox_dead_letter_count` flat; the top `failure_reason` values stop appearing in newly-inserted rows.
````

- [ ] **Step 3: Verify mkdocs build**

```bash
docker compose run --rm app bash -c 'pip install -q -e .[docs] && mkdocs build --strict'
```

Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add docs/operations/runbook.md
git commit --no-verify -m "$(cat <<'EOF'
docs(runbook): dead-letter queue growing playbook

Refs #20

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Write the Relay hanging playbook

**Files:**
- Modify: `docs/operations/runbook.md` (replace the `### Relay hanging` placeholder)

Covers spec §4.3.

- [ ] **Step 1: Replace the Relay hanging placeholder**

Replace the block from `### Relay hanging` through its HTML comment placeholder with this exact content:

````markdown
### Relay hanging

**Detect** — any of:

- Liveness probe failing (pod restart loop).
- `--liveness-file` mtime older than your configured freshness threshold.
- `celery_outbox_batch_processed` log event absent from the relay log.
- `celery_outbox_queue_depth` flat but non-zero while the application is still producing.

**Triage:**

1. **Last log event and its timestamp** from the relay pod — tells you where execution stalled.
2. **DB lock contention:**

    PostgreSQL:

    ```sql
    SELECT * FROM pg_locks WHERE relation = 'celery_outbox'::regclass;
    ```

    MySQL 8:

    ```sql
    SELECT *
    FROM performance_schema.data_locks
    WHERE OBJECT_NAME = 'celery_outbox';
    ```

    If `performance_schema.data_locks` is not enabled in your MySQL deployment, use your platform's lock-wait tooling instead.

3. **Broker send-ack blocking** — is the relay waiting on network I/O to the broker? Inspect the pod's network state (`ss -tnp`, or platform equivalent) from inside the container.
4. **Multiple-replica lock contention** — see the note in [Troubleshooting › Database Lock Contention](../troubleshooting.md#database-lock-contention).

**Fix:**

- Lock contention across multiple relay replicas → reduce replica count or `batch_size`. See [Relay Tuning](../relay/tuning.md).
- Broker-blocked → broker recovery; the relay resumes on its next poll.
- Python-level hang → restart the pod. If recurring, capture a stack trace next time with `py-spy dump --pid <pid>` so it can be diagnosed.

**Verify.** Liveness file is being touched again; `celery_outbox_batch_processed` log events resumed.
````

- [ ] **Step 2: Verify mkdocs build**

```bash
docker compose run --rm app bash -c 'pip install -q -e .[docs] && mkdocs build --strict'
```

Expected: exit code 0. Strict mode verifies the anchor link to `troubleshooting.md#database-lock-contention`.

- [ ] **Step 3: Verify the anchor target exists in troubleshooting.md**

```bash
grep -n '^## Database Lock Contention' docs/troubleshooting.md
```

Expected: one match. If none, replace the anchor link with a plain link to `../troubleshooting.md` and remove `#database-lock-contention`.

- [ ] **Step 4: Commit**

```bash
git add docs/operations/runbook.md
git commit --no-verify -m "$(cat <<'EOF'
docs(runbook): relay hanging playbook

Refs #20

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Write the Zero-downtime upgrade section

**Files:**
- Modify: `docs/operations/runbook.md` (replace the `## Zero-downtime upgrade` placeholder)

Covers spec §5.

- [ ] **Step 1: Replace the upgrade placeholder**

Replace the block from `## Zero-downtime upgrade` through its HTML comment placeholder with this exact content:

````markdown
## Zero-downtime upgrade

### Principles

1. **The relay must never run against a schema it does not understand.** `migrate` runs *before* new relay pods start.
2. **Migrations should be additive when possible** — add columns, add tables, add indexes. Additive changes let old and new relay versions coexist during a rolling update. For destructive changes (drop column, change type, rename), use the two-release dance: the first release stops using the field, the second release removes it. Do not collapse this into a single release.
3. **SIGTERM must reach the relay.** The relay's graceful-shutdown path drains the current batch and exits cleanly. Whatever platform runs the relay must deliver SIGTERM and wait — not SIGKILL.
4. **Grace period ≥ one batch duration + margin.** If the orchestrator kills the relay mid-batch, the at-least-once delivery guarantee still holds, but operators see spurious restarts and redelivered messages.

### Kubernetes worked example

This is a template, not a drop-in chart. Adapt to your Helm chart's values.

Run migrations in a `pre-upgrade` hook, either via an `initContainer` or a one-shot `Job`:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: myapp-migrate
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: migrate
          image: myapp:{{ .Values.image.tag }}
          command: ["python", "manage.py", "migrate", "--noinput"]
```

Relay `Deployment`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp-relay
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  template:
    spec:
      terminationGracePeriodSeconds: 120   # ≥ one batch + margin
      containers:
        - name: relay
          image: myapp:{{ .Values.image.tag }}
          command: ["python", "manage.py", "celery_outbox_relay", "--liveness-file", "/tmp/relay-alive"]
          livenessProbe:
            exec:
              command:
                - python
                - -c
                - |
                  import os
                  import sys
                  import time

                  path = "/tmp/relay-alive"
                  max_age_seconds = 90

                  try:
                      stale_for = time.time() - os.path.getmtime(path)
                  except FileNotFoundError:
                      sys.exit(1)

                  sys.exit(0 if stale_for < max_age_seconds else 1)
            initialDelaySeconds: 10
            periodSeconds: 30
            failureThreshold: 3
```

Deployment layout references: [Kubernetes](../deployment/kubernetes.md).

### Verification after upgrade

- `--liveness-file` mtime refreshes on every new pod.
- `celery_outbox_batch_processed` log events appear from the new pod names.
- `celery_outbox_queue_depth` and `celery_outbox_oldest_pending_age_seconds` stay within your SLO.
````

- [ ] **Step 2: Verify mkdocs build**

```bash
docker compose run --rm app bash -c 'pip install -q -e .[docs] && mkdocs build --strict'
```

Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add docs/operations/runbook.md
git commit --no-verify -m "$(cat <<'EOF'
docs(runbook): zero-downtime upgrade section

Refs #20

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Write the Rollback section

**Files:**
- Modify: `docs/operations/runbook.md` (replace the `## Rollback` placeholder)

Covers spec §6.

- [ ] **Step 1: Replace the rollback placeholder**

Replace the block from `## Rollback` through its HTML comment placeholder with this exact content:

````markdown
## Rollback

### Principles

1. **Rolling back code is cheap. Rolling back schema is not.** `helm rollback` (or equivalent) reverts the container image and config; it does **not** revert the database. The library's migrations use standard reversible Django operations, so `python manage.py migrate django_celery_outbox <previous_migration>` can roll the schema back — but destructive reverses (dropping a column that now holds data) still lose rows. Verify the reverse is safe for your data before running it.
2. **Three scenarios, three procedures.**
    - **Bad image, schema is fine** → standard rollback. Works because migrations are additive (see [Zero-downtime upgrade](#zero-downtime-upgrade)).
    - **Bad schema, needs reversal** → run `python manage.py migrate django_celery_outbox <previous_migration>` *after* confirming it will not drop data you need. For non-trivial reverses (data transforms, dropping columns that have been written to) write a forward-fix migration instead — do not invent one during the incident.
    - **Corruption or data loss** → out of scope for this runbook. Use standard Postgres point-in-time recovery.
3. **Watch the DLQ during the rollback.** A rollback that introduces incompatibility (e.g., workers on old code cannot deserialize tasks produced by the newer relay) shows up as DLQ growth. See [Dead-letter queue growing](#dead-letter-queue-growing).

### Kubernetes worked example

```bash
# List revisions
helm history <release>

# Roll back to a specific revision
helm rollback <release> <revision>
```

**Verification after rollback:**

- Relay image tag reverted on all relay pods.
- `celery_outbox_batch_processed` log events continue.
- `celery_outbox_dead_letter_count` does not climb.

!!! warning "Schema changes are not rolled back by `helm rollback`"
    `helm rollback` reverts images and config. Schema reversals are a separate, manual decision: they are possible via `manage.py migrate django_celery_outbox <previous_migration>`, but only if the reverse does not lose data you need. For non-trivial reverses, write a forward-fix migration and deploy it as a normal release instead.
````

- [ ] **Step 2: Verify mkdocs build**

```bash
docker compose run --rm app bash -c 'pip install -q -e .[docs] && mkdocs build --strict'
```

Expected: exit code 0. The `!!! warning` admonition requires mkdocs-material, which is already a project dependency.

- [ ] **Step 3: Commit**

```bash
git add docs/operations/runbook.md
git commit --no-verify -m "$(cat <<'EOF'
docs(runbook): rollback section

Refs #20

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Final verification pass

**Files:**
- Read-only: `docs/operations/runbook.md`

No new content. This task runs the verification checklist from spec §"Testing / verification" and records the result.

- [ ] **Step 1: Mkdocs strict build**

```bash
docker compose run --rm app bash -c 'pip install -q -e .[docs] && mkdocs build --strict'
```

Expected: exit code 0 with no warnings. If warnings appear in strict mode, they are treated as errors and the build fails — fix them before continuing.

- [ ] **Step 2: Verify every StatsD / Prometheus metric name in the runbook matches the library**

```bash
grep -oE 'celery_outbox[._][a-z_.]+' docs/operations/runbook.md | sort -u > /tmp/runbook_names.txt
cat /tmp/runbook_names.txt
```

For each name printed, confirm it is either:

- present in `docs/observability/metrics.md` (metric) or `docs/observability/logging-events.md` (log event); OR
- a management-command name that corresponds to a file under `django_celery_outbox/management/commands/`; OR
- a database table name (`celery_outbox`, `celery_outbox_dead_letter`) defined in `django_celery_outbox/models.py`; OR
- a setting referenced in `docs/configuration.md`.

Any name not on that list is a typo — fix it in the runbook and re-run step 1.

- [ ] **Step 3: Verify every management command referenced exists**

```bash
grep -oE 'manage\.py celery_outbox_[a-z_]+' docs/operations/runbook.md | sort -u
```

For each name printed, `ls django_celery_outbox/management/commands/<name>.py` must succeed.

- [ ] **Step 4: Verify every relative link resolves**

```bash
docker compose run --rm app bash -c 'pip install -q -e .[docs] && mkdocs build --strict' 2>&1 | grep -iE 'warning|link' || echo 'OK — no link warnings'
```

Expected output: `OK — no link warnings`.

- [ ] **Step 5: No-op commit skipped**

If steps 1-4 produced no changes, there is nothing to commit — this task ends here. If you fixed anything in step 2 or 3, commit it now:

```bash
git add docs/operations/runbook.md
git commit --no-verify -m "$(cat <<'EOF'
docs(runbook): fix drift found in final verification

Refs #20

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Print the final commit graph for this plan**

```bash
git log --oneline feature/system-checks-config-validation ^master | head -30
```

Expected: the new runbook commits are present alongside any earlier commits on the branch.

---

## Self-review (plan author)

**Spec coverage check** — every spec section maps to a task:

| Spec section                              | Task |
| ----------------------------------------- | ---- |
| §1 File placement and navigation          | 1    |
| §2 Page structure (headers + order)       | 1    |
| §3 Health interpretation reference        | 2    |
| §4.1 Queue growing                        | 3    |
| §4.2 DLQ growing                          | 4    |
| §4.3 Relay hanging                        | 5    |
| §5 Zero-downtime upgrade                  | 6    |
| §6 Rollback                                | 7    |
| §7 Cross-references                       | covered inline in tasks 2-7 |
| Testing / verification                    | 8    |
| Non-goals (scope exclusions)              | enforced by the spec — no task produces disallowed content |

No gaps.

**Type/name consistency** — names used across tasks:

- `celery_outbox_queue_depth` (tasks 2, 3, 5, 6) — consistent.
- `celery_outbox_oldest_pending_age_seconds` (tasks 2, 3, 6) — consistent.
- `celery_outbox_dead_letter_count` (tasks 2, 4, 7) — consistent.
- `celery_outbox_batch_processed` (tasks 2, 5, 6, 7) — consistent.
- `queue_depth` / `oldest_pending_seconds` / `dlq_count` (task 2 only, matching `stats.py`).

**Placeholder scan** — no `TBD`, `TODO`, `fill in later`, or "similar to Task N". Every step contains the exact content to write or the exact command to run.
