# Basic Tasks

## Sending Tasks

With `OutboxCelery`, tasks are sent exactly like regular Celery:

```python
from myproject.celery import app

@app.task
def send_email(user_id: int, template: str):
    ...

# All these work:
send_email.delay(123, 'welcome')
send_email.apply_async(args=[123, 'welcome'])
send_email.apply_async(kwargs={'user_id': 123, 'template': 'welcome'})
```

## Inside Transactions

The outbox pattern only makes sense inside transactions:

```python
from django.db import transaction

with transaction.atomic():
    user = User.objects.create(email='test@example.com')
    send_email.delay(user.id, 'welcome')
# Both committed together
```

If the transaction rolls back, the task is never sent.

## Task Signatures

Celery signatures are fully supported:

```python
from celery import signature, chain, group, chord

# Signature
sig = send_email.s(123, 'welcome')
sig.delay()

# Chain
chain(step1.s(), step2.s(), step3.s()).delay()

# Group (parallel execution)
group(task.s(i) for i in range(10)).delay()

# Chord (group + callback)
chord(group(task.s(i) for i in range(10)), callback.s()).delay()
```
