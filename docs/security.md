# Security

## PII in Task Arguments

Task arguments are stored in the database. If they contain PII:

1. **Minimize data**: Pass IDs, not full objects
2. **Use PII redactor**: Configure `CELERY_OUTBOX_PII_REDACTOR`
3. **Encrypt sensitive fields**: Before passing to tasks

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

## structlog Context

Filter sensitive keys from propagated context:

```python
CELERY_OUTBOX_STRUCTLOG_FILTER_KEYS = {
    'password',
    'api_key',
    'access_token',
    'credit_card',
}
```

## Exception Tracebacks

By default, full tracebacks are logged. Disable for production:

```python
CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK = False
```

## Dead Letter Retention

Dead letters may contain sensitive data. Purge regularly:

```bash
python manage.py celery_outbox_dead_letter_purge --older-than 30
```

## Database Access

- Grant minimal permissions to application user
- Use separate credentials for relay if possible
- Enable TLS for database connections
