# Health Checks

## Relay Liveness Probe

The relay supports file-based liveness probes for Kubernetes:

```bash
python manage.py celery_outbox_relay --liveness-file /tmp/relay-alive
```

After each batch, the relay touches this file. Your probe should check both:

- the file exists
- its mtime is still fresh

A plain `test -f` only proves the relay started once; it does not detect a stalled relay. A portable probe is to have Kubernetes run a short Python check in the same container:

```yaml
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

Choose `max_age_seconds` to exceed your normal healthy gap between touches. A good starting point is the larger of:

- roughly 2x `--idle-time`
- your worst-case healthy batch duration

With the example above, Kubernetes restarts the pod if the file is missing or has been stale for at least 90 seconds.

## Queue Depth Check

Monitor queue depth via stats command:

```bash
python manage.py celery_outbox_stats
```

Or via StatsD metric:

```promql
celery_outbox_queue_depth > 1000
```

## Health Endpoint

The package does not ship an HTTP health endpoint. If your platform requires one for load balancers, add your own view:

```python
from django.http import JsonResponse
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter

def health(request):
    return JsonResponse({
        'status': 'ok',
        'queue_depth': CeleryOutbox.objects.count(),
        'dead_letter_count': CeleryOutboxDeadLetter.objects.count(),
    })
```

```python
# urls.py
path('health/', health),
```
