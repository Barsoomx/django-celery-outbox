# Runbook

Open this page when something is wrong. Skim for the symptom that matches what you are seeing (page's [Incident playbooks](#incident-playbooks)), read the relevant playbook top to bottom, and execute. This page is not meant to be read cover-to-cover.

Every playbook below has the same shape: **Detect → Triage → Fix → Verify**. If you cannot find a matching playbook, the closest page for ad-hoc diagnosis is [Troubleshooting](../troubleshooting.md).

## Health signals

Use these tables as a reference while following any playbook.

### Liveness file

| Signal                     | Healthy                              | Stale                                                                                |
| -------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------ |
| mtime of `--liveness-file` | within 2× the relay poll interval    | older → relay stalled or dead → [Relay hanging](#relay-hanging)                      |

See [Health Checks](health-checks.md) for the `--liveness-file` flag details.

### `celery_outbox_stats` snapshot

`python manage.py celery_outbox_stats` prints a point-in-time snapshot. It is not a replacement for metrics over time.

| Field                     | Meaning                                           | Abnormal → playbook                                  |
| ------------------------- | ------------------------------------------------- | ---------------------------------------------------- |
| `queue_depth`             | rows in `celery_outbox` awaiting send             | trending up → [Queue growing](#queue-growing)        |
| `oldest_pending_seconds`  | age of the oldest pending row (delivery latency)  | above your SLO → [Queue growing](#queue-growing)     |
| `dlq_count`               | rows in `celery_outbox_dead_letter`               | delta from baseline → [Dead-letter queue growing](#dead-letter-queue-growing) |

### Metrics for graphing and alerting

StatsD names are shown with the default `MONITORING_STATSD_PREFIX = 'celery_outbox'`. Prometheus-exported names (via statsd-exporter) replace dots with underscores.

| StatsD metric                               | Prometheus                                   | Type   | Use                                                                                           |
| ------------------------------------------- | -------------------------------------------- | ------ | --------------------------------------------------------------------------------------------- |
| `celery_outbox.queue.depth`                 | `celery_outbox_queue_depth`                  | gauge  | Chart as a time series. Sawtooth is healthy; monotonic rise means the queue is growing.       |
| `celery_outbox.oldest_pending_age_seconds`  | `celery_outbox_oldest_pending_age_seconds`   | gauge  | Alert on crossing your SLO. Suggested starting threshold: 60s. Tune to your application.      |
| `celery_outbox.dead_letter.count`           | `celery_outbox_dead_letter_count`            | gauge  | Alert on delta after the baseline stabilizes.                                                 |
| `celery_outbox.batch.duration_ms`           | `celery_outbox_batch_duration_ms`            | timing | Chart per-batch processing time. Absence of new samples means the relay has stalled.          |

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
