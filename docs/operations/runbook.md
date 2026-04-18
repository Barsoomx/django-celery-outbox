# Runbook

Open this page when something is wrong. Jump to the [Incident playbooks](#incident-playbooks) section, find the playbook that matches the symptom you are seeing, read it top to bottom, and execute. This page is not meant to be read cover-to-cover.

Every playbook below has the same shape: **Detect → Triage → Fix → Verify**. If you cannot find a matching playbook, the closest page for ad-hoc diagnosis is [Troubleshooting](../troubleshooting.md).

## Health signals

Use these tables as a reference while following any playbook.

### Liveness file

| Signal                     | Healthy                                               | Stale                                                  |
| -------------------------- | ----------------------------------------------------- | ------------------------------------------------------ |
| mtime of `--liveness-file` | within your configured freshness threshold            | older → relay stalled or dead → [Relay hanging](#relay-hanging) |

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

## Incident playbooks

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
