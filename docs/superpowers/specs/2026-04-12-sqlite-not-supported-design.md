# SQLite Not Supported — Design Spec

**Issue:** [#17](https://github.com/Barsoomx/django-celery-outbox/issues/17)  
**Date:** 2026-04-12  
**Status:** Approved

## Problem

`relay.py:136-147` uses `CeleryOutbox.objects.select_for_update(skip_locked=True)`. Django raises `NotSupportedError` on SQLite because SQLite does not support `SKIP LOCKED`.

Current tests run on SQLite (`tests/settings.py`), so the relay code path is either not exercised or silently bypasses the `select_for_update`. Any user pointing django-celery-outbox at SQLite will crash on the first batch.

## Decision

**Hard abort** — SQLite is not supported. Relay refuses to start on SQLite with a clear error message.

## Supported Databases

- PostgreSQL >= 9.5
- MySQL >= 8.0.1

## Solution

### 1. Django System Check

**File:** `django_celery_outbox/checks.py`

```python
from django.core.checks import Error, register, Tags
from django.db import connection

@register(Tags.database)
def check_database_supports_skip_locked(app_configs, **kwargs):
    errors = []
    vendor = connection.vendor
    
    if vendor == 'sqlite':
        errors.append(Error(
            'SQLite does not support SELECT FOR UPDATE SKIP LOCKED.',
            hint='Use PostgreSQL >= 9.5 or MySQL >= 8.0.1 for django-celery-outbox.',
            id='celery_outbox.E001',
        ))
    
    return errors
```

**Registration in `apps.py`:**

```python
class DjangoCeleryOutboxConfig(AppConfig):
    name = 'django_celery_outbox'
    default_auto_field = 'django.db.models.BigAutoField'
    
    def ready(self):
        from django_celery_outbox import checks  # noqa: F401
```

### 2. Relay Startup Validation

**File:** `django_celery_outbox/relay.py`

Add validation in `Relay.__init__`:

```python
from django.db import connection

class Relay:
    _SUPPORTED_VENDORS = frozenset({'postgresql', 'mysql'})
    
    def __init__(self, app: Celery, ...):
        # existing validations...
        
        vendor = connection.vendor
        if vendor not in self._SUPPORTED_VENDORS:
            raise RuntimeError(
                f'Database backend "{vendor}" is not supported. '
                f'django-celery-outbox requires PostgreSQL >= 9.5 or MySQL >= 8.0.1 '
                f'for SELECT FOR UPDATE SKIP LOCKED.'
            )
        
        # rest of __init__...
```

### 3. CI Configuration

**docker-compose.yml** — add database services:

```yaml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: test_db
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_DATABASE: test_db
      MYSQL_USER: test
      MYSQL_PASSWORD: test
      MYSQL_ROOT_PASSWORD: root
```

**tests/settings.py** — switch by environment variable:

```python
import os

DB_ENGINE = os.environ.get('DB_ENGINE', 'postgresql')

if DB_ENGINE == 'postgresql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'test_db',
            'USER': 'test',
            'PASSWORD': 'test',
            'HOST': os.environ.get('DB_HOST', 'postgres'),
        }
    }
elif DB_ENGINE == 'mysql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': 'test_db',
            'USER': 'test', 
            'PASSWORD': 'test',
            'HOST': os.environ.get('DB_HOST', 'mysql'),
        }
    }
```

**pyproject.toml** — add database drivers:

```toml
test = [
  "pytest>=7.0",
  "pytest-django>=4.5",
  "factory-boy>=3.3",
  "psycopg[binary]>=3.1",
  "mysqlclient>=2.2",
]
```

**GitHub Actions** — matrix with both databases:

```yaml
jobs:
  test:
    strategy:
      matrix:
        db: [postgresql, mysql]
        python: ["3.10", "3.11", "3.12"]
    
    services:
      postgres:
        image: postgres:15
        # conditionally enabled
      mysql:
        image: mysql:8.0
        # conditionally enabled
    
    steps:
      - run: pytest -v
        env:
          DB_ENGINE: ${{ matrix.db }}
```

### 4. Documentation

**README.md** — add Database Requirements section:

```markdown
## Database Requirements

django-celery-outbox uses `SELECT FOR UPDATE SKIP LOCKED` for safe concurrent 
relay instances. This requires:

- **PostgreSQL >= 9.5**
- **MySQL >= 8.0.1**

SQLite is **not supported** and will raise an error at startup.
```

### 5. Tests

**File:** `django_celery_outbox/checks_tests.py`

- `test_check_returns_error_for_sqlite`
- `test_check_passes_for_postgresql`
- `test_check_passes_for_mysql`

**File:** `django_celery_outbox/relay_tests.py` — add:

- `test_relay_init_raises_for_unsupported_db`
- `test_relay_init_accepts_postgresql`
- `test_relay_init_accepts_mysql`

## Acceptance Criteria

- [x] Django system check errors when configured against SQLite
- [x] Docs explicitly list supported DBs (PG >= 9.5, MySQL >= 8.0.1)
- [x] Hard abort with actionable error message
- [x] Relay tests exercise `select_for_update(skip_locked=True)` against PG/MySQL in CI
