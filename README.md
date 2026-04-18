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

The package ships a `pytest11` plugin with fixtures for outbox assertions and relay verification: `outbox`, `assert_task_sent`, `fake_relay`, and `drain_outbox`.

If you use `fake_relay` or `drain_outbox`, configure `CELERY_OUTBOX_APP` in your test settings so the fixtures can resolve the relay Celery app.

See [Testing with pytest](https://barsoomx.github.io/django-celery-outbox/usage/testing-with-pytest/) for setup and usage examples.

## Security

See [Security Guide](https://barsoomx.github.io/django-celery-outbox/security/) for PII handling, traceback logging, and DLQ retention.

## License

MIT
