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

```bash
python manage.py celery_outbox_purge_dead_letter --older-than-dead 30d
```

## Database Access

- Grant minimal permissions to application user
- Use separate credentials for relay if possible
- Enable TLS for database connections
