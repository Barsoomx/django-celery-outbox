# Health Checks

## Relay Liveness Probe

The relay supports file-based liveness probes for Kubernetes:

```bash
python manage.py celery_outbox_relay --liveness-file /tmp/relay-alive
```

After each batch, the relay touches this file. Configure your probe:

```yaml
livenessProbe:
  exec:
    command:
      - test
      - -f
      - /tmp/relay-alive
  initialDelaySeconds: 10
  periodSeconds: 30
  failureThreshold: 3
```

If the file isn't touched for 90 seconds (30s * 3), Kubernetes restarts the pod.

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

For load balancer health checks, add a view:

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
