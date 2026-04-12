# Admin Interface

django-celery-outbox includes read-only Django Admin views.

## Setup

Add to your `INSTALLED_APPS` (already done if following Quick Start):

```python
INSTALLED_APPS = [
    # ...
    'django_celery_outbox',
]
```

## Available Views

### Celery Outbox

Lists pending messages:

| Column | Description |
|--------|-------------|
| ID | Database primary key |
| Task Name | Celery task name |
| Task ID | Celery task UUID |
| Retries | Current retry count |
| Created At | When queued |
| Retry After | Next retry time (if failed) |

### Dead Letter Queue

Lists failed messages:

| Column | Description |
|--------|-------------|
| ID | Database primary key |
| Task Name | Celery task name |
| Task ID | Celery task UUID |
| Retries | Final retry count |
| Failure Reason | Why it failed |
| Created At | When originally queued |

## Read-Only

Admin views are read-only by design. Modifying outbox entries could cause:

- Duplicate task execution
- Lost tasks
- Inconsistent state

Use management commands for operations.
