# django-celery-outbox

[![Tests](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/tests.yml/badge.svg)](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/tests.yml)
[![CodeQL](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/codeql.yml/badge.svg)](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/codeql.yml)
[![PyPI version](https://img.shields.io/pypi/v/django-celery-outbox.svg)](https://pypi.org/project/django-celery-outbox/)
[![Docs](https://img.shields.io/badge/docs-latest-blue.svg)](https://barsoomx.github.io/django-celery-outbox/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Transactional Outbox pattern for Celery tasks in Django.

## Features

- At-least-once delivery guarantee
- Automatic retry with exponential backoff
- Dead letter queue for failed messages
- Structlog & Sentry trace propagation
- StatsD metrics
- Django admin integration

## Quick Start

```bash
pip install django-celery-outbox
```

```python
# settings.py
INSTALLED_APPS = [..., 'django_celery_outbox']
CELERY_OUTBOX_APP = 'myproject.celery.app'

# celery.py
from django_celery_outbox import OutboxCelery

app = OutboxCelery('myproject')
```

```bash
python manage.py migrate
python manage.py check
python manage.py celery_outbox_relay
```

**[Full Documentation →](https://barsoomx.github.io/django-celery-outbox/)**

## Testing with pytest

Install pytest support alongside the library:

```bash
pip install django-celery-outbox pytest pytest-django
```

Configure Django settings for your test suite, for example:

```ini
[pytest]
DJANGO_SETTINGS_MODULE = myproject.settings
```

`drain_outbox()` uses the real relay path, so it requires the same supported database backends as the relay itself:

- PostgreSQL >= 9.5
- MySQL >= 8.0.1

```python
def test_my_code(fake_relay, assert_task_sent, drain_outbox):
    enqueue_my_task()

    msg = assert_task_sent('my.task')
    drain_outbox()

    assert len(fake_relay.calls) == 1
    assert fake_relay.calls[0].task_id == msg.task_id
```

## Security

See [Security Guide](https://barsoomx.github.io/django-celery-outbox/security/) for PII handling, traceback logging, and DLQ retention.

## License

MIT
