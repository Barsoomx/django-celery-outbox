# Security

## PII in Task Arguments

Task arguments are stored in the database. If they contain PII:

1. **Minimize data**: Pass IDs, not full objects
2. **Use PII redactor**: Configure `CELERY_OUTBOX_PII_REDACTOR`
3. **Encrypt sensitive fields**: Before passing to tasks
4. **Exclude tasks entirely**: Use `CELERY_OUTBOX_EXCLUDE_TASKS` when a payload must never be persisted in the outbox database

### PII Redactor

```python
# settings.py
CELERY_OUTBOX_PII_REDACTOR = 'myapp.utils.redact_pii'
```

```python
# myapp/utils.py
def redact_pii(task_name: str, args: list, kwargs: dict) -> tuple[list, dict]:
    redacted_kwargs = kwargs.copy()
    if 'email' in redacted_kwargs:
        redacted_kwargs['email'] = '***@***.***'
    return args, redacted_kwargs
```

The redactor creates sanitized inspection copies (`redacted_args`, `redacted_kwargs`) for admin and dead-letter review. The original task payload remains in the database and is used by the relay for actual task dispatch. If you need to prevent PII from being stored at all, use `CELERY_OUTBOX_EXCLUDE_TASKS` to bypass the outbox or encrypt sensitive fields at the application level before passing them as task arguments.

See [Configuration](configuration.md) for redaction settings and [Dead Letter Queue](operations/dead-letter.md) for the operator surfaces that can display stored payloads.

## structlog Context

Allowlist safe keys from propagated context:

```python
CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS = [
    'request_id',
    'trace_id',
    'user_id',
]
```

## Exception Tracebacks

By default, full tracebacks are logged. Disable for production:

```python
CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK = False
```

## Dead Letter Retention

Dead letters may contain sensitive data. Purge regularly:

```python
# settings.py
CELERY_OUTBOX_DLQ_RETENTION = {
    'older_than_dead': '30d',
}

# celery.py
from celery.schedules import crontab

app.conf.beat_schedule = {
    'purge-dead-letters': {
        'task': 'django_celery_outbox.tasks.purge_dead_letter',
        'schedule': crontab(hour=3, minute=0),
    },
}
```

Or via management command:

```bash
python manage.py celery_outbox_purge_dead_letter --older-than-dead 30d
```

Dead-letter replay and purge are operator actions. Restrict them to trusted staff, log who performed them, and audit them the same way you would other recovery operations against durable message state.

## Database Access

- Use separate deploy and runtime credentials; runtime app and relay processes should run with least-privilege DML access only
- Do not let production runtime credentials own the schema or grant rights onward
- Use separate credentials for relay if possible
- Enable TLS for database connections
