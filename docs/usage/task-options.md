# Task Options

## Supported Options

All standard Celery task options work through the outbox:

| Option | Description |
|--------|-------------|
| `countdown` | Delay execution by N seconds |
| `eta` | Execute at specific datetime |
| `expires` | Discard if not executed by this time |
| `link` | Callback task on success |
| `link_error` | Callback task on failure |
| `time_limit` | Hard time limit |
| `soft_time_limit` | Soft time limit (raises `SoftTimeLimitExceeded`) |

## Examples

### Countdown

```python
# Execute 60 seconds from now
send_email.apply_async(args=[user.id], countdown=60)
```

!!! note "Countdown vs ETA"
    `countdown` is converted to absolute `eta` at intercept time. This ensures the task runs at the correct time regardless of relay delay.

### ETA

```python
from datetime import datetime, timedelta

# Execute at specific time
send_email.apply_async(
    args=[user.id],
    eta=datetime.now() + timedelta(hours=1)
)
```

### Callbacks

```python
# Execute step2 after step1 completes
step1.apply_async(args=[data], link=step2.s())

# Execute error_handler if step1 fails
step1.apply_async(args=[data], link_error=error_handler.s())
```

### Time Limits

```python
# Kill task after 30 seconds
long_task.apply_async(args=[data], time_limit=30)

# Raise SoftTimeLimitExceeded after 25 seconds
long_task.apply_async(args=[data], soft_time_limit=25)
```
