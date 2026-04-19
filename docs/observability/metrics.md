# Metrics

The relay emits StatsD metrics for monitoring.

## Configuration

```python
# settings.py
MONITORING_METRICS_ENABLED = True
MONITORING_STATSD_HOST = 'localhost'
MONITORING_STATSD_PORT = 9125
MONITORING_STATSD_PREFIX = 'celery_outbox'
MONITORING_STATSD_TAGS = {
    'env': 'production',
    'service': 'myapp',
}
```

Set `MONITORING_METRICS_ENABLED = False` to disable all emission without removing the integration code.

## Metric Reference

| Metric | Type | Tags | Description |
|--------|------|------|-------------|
| `queue.depth` | gauge | - | Live backlog: rows currently eligible for relay send or recovery (`updated_at IS NULL`, retryable by `retry_after`, or stale in-flight rows) |
| `dead_letter.count` | gauge | - | Dead letter entries |
| `oldest_pending_age_seconds` | gauge | - | Age of oldest pending message in seconds |
| `batch.duration_ms` | timing | - | Processing time |
| `send_latency_ms` | timing | `task_name` | Time from enqueue to publish (outbox queue latency) |
| `messages.enqueued` | counter | `task_name` | Committed outbox rows only; rollback and excluded-task bypass do not emit it |
| `messages.published` | counter | `task_name` | Successfully sent |
| `messages.failed` | counter | `task_name`, `exception_type` | Failed (will retry) |
| `messages.exceeded` | counter | `task_name`, `exception_type` | Dead-lettered |

## Cardinality Control

High-cardinality `task_name` tags can overwhelm metrics backends. Control this with:

```python
# Option 1: Disable task_name tags entirely
CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS = True

# Option 2: Allowlist specific tasks (others become "other")
CELERY_OUTBOX_MONITORED_TASKS = {'orders.tasks.process_payment', 'orders.tasks.send_email'}
```

When `CELERY_OUTBOX_MONITORED_TASKS` is set, only listed tasks get their actual name in tags. All other tasks are tagged as `other` to limit cardinality.

## Grafana Dashboard

Example PromQL queries (via StatsD exporter):

```promql
# Queue depth
celery_outbox_queue_depth

# Throughput (messages/sec)
rate(celery_outbox_messages_published_total[5m])

# Error rate
rate(celery_outbox_messages_failed_total[5m]) /
rate(celery_outbox_messages_published_total[5m])

# P95 batch duration
histogram_quantile(0.95, celery_outbox_batch_duration_ms_bucket)
```

!!! note "StatsD Backend Compatibility"
    The histogram queries (e.g., `histogram_quantile`) require a StatsD backend that converts timing metrics to Prometheus histograms.
    Datadog StatsD exporter and statsd-exporter with histogram mapping support this.
    For other backends, use `avg()` or raw timing values instead.

## Alerting

Recommended alerts:

| Condition | Severity | Action |
|-----------|----------|--------|
| `queue.depth > 1000` for 5m | Warning | Check whether the live backlog is draining |
| `celery_outbox_oldest_pending_age_seconds > 60` for 10m | Critical | Queue latency is above SLO; inspect relay throughput and broker health |
| `increase(celery_outbox_messages_exceeded_total[10m]) > 0` | Critical | New dead letters were created; triage failures before replaying or purging |
| `rate(celery_outbox_messages_failed_total[5m]) > 0` for 10m | Warning | Check broker connectivity or task-specific send failures |

Do not treat `queue.depth` as a count of only `updated_at IS NULL` rows. It is the same live-backlog summary used by the relay selector and the `celery_outbox_stats` command.

`celery_outbox_relay_breaker_open` is a broker-unavailable condition, not proof that the relay process is dead. Page process-down incidents from your platform health checks or liveness file monitoring instead of from the bundled metric examples.
