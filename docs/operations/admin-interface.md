# Admin Interface

django-celery-outbox includes read-only object views in Django Admin plus a small set of operator bulk actions.

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
| Schema Version | Payload schema version |
| Created At | When queued |
| Updated At | Last retry/update timestamp |

Available filters: `task_name`, `retries`, `schema_version`

Search fields: `task_id`, `task_name`

The changelist also shows an outbox summary panel with:

- total outbox rows
- pending rows (`updated_at IS NULL`)
- failed rows (`retries > 0`)
- age of the oldest pending row

Bulk action:

- `reset_retries` resets `retries`, `retry_after`, and `updated_at` for the selected rows.

### Dead Letter Queue

Lists failed messages:

| Column | Description |
|--------|-------------|
| ID | Database primary key |
| Task Name | Celery task name |
| Task ID | Celery task UUID |
| Retries | Final retry count |
| Schema Version | Payload schema version |
| Created At | When originally queued |
| Dead At | When moved to dead letter |

Available filters: `task_name`, `failure_reason`, `dead_at`, `schema_version`

Search fields: `task_id`, `task_name`, `failure_reason`

Bulk action:

- `retry_selected` copies the selected dead-letter rows back into `celery_outbox` for another send attempt, preserves stored payload/schema/context fields, and removes them from the dead-letter table.

## Read-Only Record Views

The admin does not allow add/change/delete from object detail pages. That is deliberate: direct editing of outbox rows could cause:

- Duplicate task execution
- Lost tasks
- Inconsistent state

Detail pages still expose inspection payloads through the read-only `args` / `kwargs` views, which prefer redacted inspection copies when available.

Operational changes are exposed only through the dedicated bulk actions above.
