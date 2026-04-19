# django-celery-outbox

[![PyPI](https://img.shields.io/pypi/v/django-celery-outbox.svg)](https://pypi.org/project/django-celery-outbox/)
[![Tests](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/tests.yml/badge.svg)](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Transactional Outbox pattern for Celery tasks in Django.

## Why Use This?

When you call `task.delay()` inside a database transaction, two things can go wrong:

1. **Message lost**: The task is sent to the broker, but the transaction rolls back. The task runs with data that doesn't exist.
2. **Message never sent**: The transaction commits, but the broker connection fails. The task is never executed.

django-celery-outbox solves both problems by storing tasks in a database table within the same transaction as your business data. A separate relay process reads the table and sends tasks to the broker asynchronously with **durable recovery for committed rows** and duplicate-tolerant relay semantics. Stronger end-to-end guarantees still depend on broker confirms.

## Features

- Drop-in replacement for `celery.Celery`
- Duplicate-tolerant relay recovery
- Automatic retry with exponential backoff
- Dead letter queue for failed messages
- Sentry trace propagation
- structlog context propagation
- StatsD metrics
- Django admin integration
- Packaged pytest fixtures
- File-based relay liveness guidance

## Quick Links

- [Getting Started](getting-started.md) — Install and configure in 5 minutes
- [Concepts](concepts.md) — How the outbox pattern works
- [Configuration](configuration.md) — All settings reference
- [Testing with pytest](usage/testing-with-pytest.md) — Built-in fixtures for outbox and relay tests
- [Example Project](https://github.com/Barsoomx/django-celery-outbox/tree/master/examples/minimal_django) — Working Docker Compose setup
