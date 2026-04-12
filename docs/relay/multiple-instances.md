# Multiple Relay Instances

## Scaling Horizontally

You can run multiple relay instances safely thanks to `SELECT FOR UPDATE SKIP LOCKED`:

```bash
# Instance 1
python manage.py celery_outbox_relay --batch-size 100

# Instance 2
python manage.py celery_outbox_relay --batch-size 100

# Instance 3
python manage.py celery_outbox_relay --batch-size 100
```

Each instance locks different rows, preventing double-processing.

## Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: celery-outbox-relay
spec:
  replicas: 3  # Scale as needed
  selector:
    matchLabels:
      app: celery-outbox-relay
  template:
    spec:
      containers:
        - name: relay
          image: myapp:latest
          command:
            - python
            - manage.py
            - celery_outbox_relay
            - --batch-size=100
            - --liveness-file=/tmp/alive
          livenessProbe:
            exec:
              command:
                - test
                - -f
                - /tmp/alive
            initialDelaySeconds: 10
            periodSeconds: 30
```

## Considerations

1. **Database connections**: Each instance uses one connection
2. **Lock contention**: More instances = more lock attempts
3. **Diminishing returns**: Beyond 3-5 instances, gains are minimal
4. **Monitoring**: Track `messages.published` per instance
