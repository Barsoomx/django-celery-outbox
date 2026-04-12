# Log Sampling for High-Throughput Deployments

At >1000 messages/second, logging can become a bottleneck. This guide covers optimization strategies.

## Log Volume Analysis

| Event | Frequency | Typical Volume | Recommendation |
|-------|-----------|----------------|----------------|
| `celery_outbox_batch_processed` | Per cycle | ~1-2/sec | Log all |
| `celery_outbox_relay_idle` | When idle | ~1-10/sec | Set DEBUG level |
| `celery_outbox_relay_busy` | When busy | ~1-10/sec | Set DEBUG level |
| `celery_outbox_send_failed` | Per failure | Variable | Log all (important) |
| `celery_outbox_max_retries_exceeded` | Rare | ~0.001/sec | Log all (critical) |

## Recommendations

### 1. Filter DEBUG Events

Configure structlog to filter DEBUG level in production:

```python
LOGGING = {
    'loggers': {
        'django_celery_outbox.relay': {
            'level': 'INFO',  # Skip DEBUG events
        },
    },
}
```

### 2. Disable Task Name Tags

For high cardinality scenarios (>100 unique task names):

```python
CELERY_OUTBOX_DISABLE_TASK_NAME_TAGS = True
```

Or use an allowlist:

```python
CELERY_OUTBOX_MONITORED_TASKS = {'critical.task1', 'critical.task2'}
```

### 3. Use Async Log Handlers

Configure structlog with async handlers to prevent blocking:

```python
import structlog
from structlog.stdlib import AsyncBoundLogger

structlog.configure(
    wrapper_class=AsyncBoundLogger,
    # ...
)
```

### 4. Sample Non-Critical Logs

For very high volume, consider sampling in your log processor:

```python
import random

def sample_processor(logger, method_name, event_dict):
    if event_dict.get('event') in ('celery_outbox_relay_idle', 'celery_outbox_relay_busy'):
        if random.random() > 0.1:  # 10% sample rate
            raise structlog.DropEvent
    return event_dict
```

## Monitoring Log Volume

Track log volume with StatsD:

```python
# In structlog processor
def count_logs(logger, method_name, event_dict):
    from django_celery_outbox import metrics
    metrics.increment('log.events', tags={'event': event_dict.get('event', 'unknown')})
    return event_dict
```
