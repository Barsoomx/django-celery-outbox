# Metrics

The relay emits StatsD metrics for monitoring.

## Configuration

```python
# settings.py
CELERY_OUTBOX_STATSD_HOST = 'localhost'
CELERY_OUTBOX_STATSD_PORT = 8125
CELERY_OUTBOX_STATSD_PREFIX = 'celery_outbox'
CELERY_OUTBOX_STATSD_TAGS = {
    'env': 'production',
    'service': 'myapp',
}
```

## Metric Reference

| Metric | Type | Tags | Description |
|--------|------|------|-------------|
| `queue.depth` | gauge | - | Pending messages |
| `dead_letter.count` | gauge | - | Dead letter entries |
| `batch.duration_ms` | timing | - | Processing time |
| `messages.published` | counter | `task_name` | Successfully sent |
| `messages.failed` | counter | `task_name` | Failed (will retry) |
| `messages.exceeded` | counter | `task_name` | Dead-lettered |

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

## Alerting

Recommended alerts:

| Condition | Severity | Action |
|-----------|----------|--------|
| `queue.depth > 1000` for 5m | Warning | Check relay health |
| `dead_letter.count > 10` | Warning | Investigate failures |
| `messages.failed > 0` for 10m | Warning | Check broker connectivity |
