# Kubernetes Deployment

## Deployment Manifest

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: celery-outbox-relay
spec:
  replicas: 2
  selector:
    matchLabels:
      app: celery-outbox-relay
  template:
    metadata:
      labels:
        app: celery-outbox-relay
    spec:
      containers:
        - name: relay
          image: myapp:latest
          command:
            - python
            - manage.py
            - celery_outbox_relay
            - --batch-size=100
            - --idle-time=1.0
            - --liveness-file=/tmp/alive
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: myapp-secrets
                  key: database-url
            - name: CELERY_BROKER_URL
              valueFrom:
                secretKeyRef:
                  name: myapp-secrets
                  key: broker-url
          livenessProbe:
            exec:
              command:
                - python
                - -c
                - |
                  import os
                  import sys
                  import time

                  path = "/tmp/alive"
                  max_age_seconds = 90

                  try:
                      stale_for = time.time() - os.path.getmtime(path)
                  except FileNotFoundError:
                      sys.exit(1)

                  sys.exit(0 if stale_for < max_age_seconds else 1)
            initialDelaySeconds: 10
            periodSeconds: 30
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "256Mi"
              cpu: "500m"
```

## Scaling

The relay scales horizontally. Each instance locks different rows via `SELECT FOR UPDATE SKIP LOCKED`.

Recommended: 2-3 replicas for high availability.

## Graceful Shutdown

The relay handles SIGTERM gracefully. Kubernetes sends SIGTERM during pod termination.

Set `terminationGracePeriodSeconds` to allow batch completion:

```yaml
spec:
  terminationGracePeriodSeconds: 120  # >= shutdown_timeout + send_timeout + margin
```

Size the grace period to cover your configured `--shutdown-timeout`, `--send-timeout`, and some scheduling margin. A shorter window can force SIGKILL before the relay finishes draining.

## Resource Requirements

| Workload | Memory | CPU |
|----------|--------|-----|
| Low volume | 128Mi | 100m |
| Medium volume | 256Mi | 250m |
| High volume | 512Mi | 500m |

Relay is I/O bound (database + broker), not CPU bound.
