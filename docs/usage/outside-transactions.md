# Outside Transactions

## Warning

Using the outbox outside a transaction defeats its purpose:

```python
# BAD: Not in a transaction
order = Order.objects.create(...)
send_email.delay(order.id)  # Written to outbox, but not atomic with Order
```

The relay logs a warning when this happens:

```
celery_outbox_not_in_transaction task_name=myapp.tasks.send_email
```

## When It's Acceptable

Outside transactions may be acceptable for:

- Background jobs that don't need atomicity
- Tasks triggered by management commands
- Testing and development

## Recommendations

1. **Use transactions**: Wrap related operations in `transaction.atomic()`
2. **Enable warnings**: Check logs for `celery_outbox_not_in_transaction`
3. **Consider excluded tasks**: If a task doesn't need transactional guarantees, add it to `CELERY_OUTBOX_EXCLUDE_TASKS`
