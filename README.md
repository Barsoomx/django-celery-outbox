# django-celery-outbox

[![Tests](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/tests.yml/badge.svg)](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/tests.yml)
[![CodeQL](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/codeql.yml/badge.svg)](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/codeql.yml)
[![codecov](https://codecov.io/github/Barsoomx/django-celery-outbox/graph/badge.svg?token=PKOXQWYZVD)](https://codecov.io/github/Barsoomx/django-celery-outbox)
[![PyPI version](https://img.shields.io/pypi/v/django-celery-outbox.svg)](https://pypi.org/project/django-celery-outbox/)
[![Docs](https://img.shields.io/badge/docs-latest-blue.svg)](https://barsoomx.github.io/django-celery-outbox/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Transactional Outbox pattern for Celery tasks in Django.

## Features

- Durable persistence for committed task intents
- Duplicate-tolerant relay recovery
- Automatic retry with capped exponential backoff
- Dead letter queue for exhausted retries
- Structlog & Sentry trace propagation
- StatsD metrics
- Django admin integration

## Compatibility

CI exercises Django 4.2 and 5.2 in the general matrix, plus dedicated live-broker smoke coverage for Django 5.0 and 5.1. The support claims in this repository stay aligned with those explicit lanes.

## Coverage

Canonical coverage is published from the Py3.12 / Django 5.2 / Celery 5.6 / PostgreSQL lane in GitHub Actions.

[![Codecov Tree Graph](https://codecov.io/github/Barsoomx/django-celery-outbox/graphs/tree.svg?token=PKOXQWYZVD)](https://codecov.io/github/Barsoomx/django-celery-outbox)

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

Committed rows stay in the outbox until the relay publishes them or dead-letters them, but
consumers still need to be idempotent. If the relay crashes after a broker publish and before
cleanup, stale-timeout recovery can reclaim and resend the row. Stronger end-to-end guarantees
still depend on broker confirms; without publisher confirms, the broker can fail ambiguously
after `Celery.send_task()` returns.

**[Full Documentation →](https://barsoomx.github.io/django-celery-outbox/)**

## Security

See [Security Guide](https://barsoomx.github.io/django-celery-outbox/security/) for PII handling, traceback logging, and DLQ retention.

## License

MIT
