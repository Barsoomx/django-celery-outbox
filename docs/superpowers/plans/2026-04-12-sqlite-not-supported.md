# SQLite Not Supported — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent relay from running on SQLite with clear error messages and migrate all tests to PostgreSQL/MySQL.

**Architecture:** Django system check + Relay.__init__ validation using `connection.features.has_select_for_update_skip_locked`. CI runs tests against PostgreSQL and MySQL matrix.

**Tech Stack:** Django system checks, PostgreSQL 15, MySQL 8.0, psycopg[binary], mysqlclient, GitHub Actions services

**Spec:** `docs/superpowers/specs/2026-04-12-sqlite-not-supported-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `django_celery_outbox/checks.py` | Create | Django system check for SKIP LOCKED support |
| `django_celery_outbox/checks_tests.py` | Create | Tests for system check |
| `django_celery_outbox/apps.py` | Modify | Register checks in ready() |
| `django_celery_outbox/relay.py` | Modify | Add database validation in __init__ |
| `django_celery_outbox/relay_tests.py` | Modify | Add tests for database validation |
| `tests/settings.py` | Modify | Switch database by DB_ENGINE env var |
| `pyproject.toml` | Modify | Add psycopg[binary] and mysqlclient |
| `docker-compose.yml` | Modify | Add postgres and mysql services |
| `.github/workflows/tests.yml` | Modify | Add database matrix |
| `README.md` | Modify | Add Database Requirements section |

---

### Task 1: Django System Check — Tests

**Files:**
- Create: `django_celery_outbox/checks.py`
- Create: `django_celery_outbox/checks_tests.py`

- [ ] **Step 1.1: Create empty checks.py**

```python
# django_celery_outbox/checks.py
```

- [ ] **Step 1.2: Write failing test — error when skip_locked not supported**

```python
# django_celery_outbox/checks_tests.py
from unittest.mock import MagicMock, patch

import pytest

from django_celery_outbox.checks import check_database_supports_skip_locked


def test_check_returns_error_when_skip_locked_not_supported() -> None:
    m_connection = MagicMock()
    m_connection.features.has_select_for_update_skip_locked = False
    m_connection.vendor = 'sqlite'

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.CeleryOutbox') as m_model:
            m_model.objects.db = 'default'
            errors = check_database_supports_skip_locked(None)

    assert len(errors) == 1
    assert errors[0].id == 'celery_outbox.E001'
    assert 'SELECT FOR UPDATE SKIP LOCKED' in errors[0].msg
```

- [ ] **Step 1.3: Run test to verify it fails**

Run: `docker compose run --rm app pytest django_celery_outbox/checks_tests.py -v`
Expected: FAIL — ImportError or function not found

- [ ] **Step 1.4: Implement check function**

```python
# django_celery_outbox/checks.py
from django.core.checks import Error, Tags, register
from django.db import connections

from django_celery_outbox.models import CeleryOutbox


@register(Tags.database)
def check_database_supports_skip_locked(
    app_configs: object,
    **kwargs: object,
) -> list[Error]:
    errors: list[Error] = []
    db_alias = CeleryOutbox.objects.db
    connection = connections[db_alias]

    if not connection.features.has_select_for_update_skip_locked:
        errors.append(
            Error(
                'Database does not support SELECT FOR UPDATE SKIP LOCKED.',
                hint='Use PostgreSQL >= 9.5 or MySQL >= 8.0.1 for django-celery-outbox.',
                id='celery_outbox.E001',
            )
        )

    return errors
```

- [ ] **Step 1.5: Run test to verify it passes**

Run: `docker compose run --rm app pytest django_celery_outbox/checks_tests.py::test_check_returns_error_when_skip_locked_not_supported -v`
Expected: PASS

- [ ] **Step 1.6: Write test — passes when skip_locked supported**

Add to `django_celery_outbox/checks_tests.py`:

```python
def test_check_passes_when_skip_locked_supported() -> None:
    m_connection = MagicMock()
    m_connection.features.has_select_for_update_skip_locked = True

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.CeleryOutbox') as m_model:
            m_model.objects.db = 'default'
            errors = check_database_supports_skip_locked(None)

    assert errors == []
```

- [ ] **Step 1.7: Run all checks tests**

Run: `docker compose run --rm app pytest django_celery_outbox/checks_tests.py -v`
Expected: 2 tests PASS

- [ ] **Step 1.8: Commit**

```bash
git add django_celery_outbox/checks.py django_celery_outbox/checks_tests.py
git commit -m "feat: add Django system check for SKIP LOCKED support

Adds celery_outbox.E001 error when database does not support
SELECT FOR UPDATE SKIP LOCKED (e.g., SQLite)."
```

---

### Task 2: Register Check in apps.py

**Files:**
- Modify: `django_celery_outbox/apps.py`

- [ ] **Step 2.1: Update apps.py to register checks**

```python
# django_celery_outbox/apps.py
from django.apps import AppConfig


class DjangoCeleryOutboxConfig(AppConfig):
    name = 'django_celery_outbox'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self) -> None:
        from django_celery_outbox import checks  # noqa: F401
```

- [ ] **Step 2.2: Run linter**

Run: `docker compose run --rm app ruff check django_celery_outbox/apps.py`
Expected: No errors

- [ ] **Step 2.3: Commit**

```bash
git add django_celery_outbox/apps.py
git commit -m "feat: register database check in AppConfig.ready()"
```

---

### Task 3: Relay Startup Validation — Tests

**Files:**
- Modify: `django_celery_outbox/relay.py`
- Modify: `django_celery_outbox/relay_tests.py`

- [ ] **Step 3.1: Write failing test — raises when skip_locked not supported**

Add to `django_celery_outbox/relay_tests.py`:

```python
def test_relay_init_raises_when_skip_locked_not_supported(m_celery_app: MagicMock) -> None:
    m_connection = MagicMock()
    m_connection.features.has_select_for_update_skip_locked = False
    m_connection.vendor = 'sqlite'

    with patch('django_celery_outbox.relay.connections', {'default': m_connection}):
        with patch('django_celery_outbox.relay.CeleryOutbox') as m_model:
            m_model.objects.db = 'default'

            with pytest.raises(RuntimeError, match='does not support SELECT FOR UPDATE SKIP LOCKED'):
                Relay(app=m_celery_app)
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `docker compose run --rm app pytest django_celery_outbox/relay_tests.py::test_relay_init_raises_when_skip_locked_not_supported -v`
Expected: FAIL — RuntimeError not raised

- [ ] **Step 3.3: Implement validation in Relay.__init__**

Update `django_celery_outbox/relay.py`:

Add import at top:
```python
from django.db import close_old_connections, connections, transaction
```

Add validation after existing validations in `__init__` (after line 50, before `self._app = app`):

```python
        db_alias = CeleryOutbox.objects.db
        db_connection = connections[db_alias]
        if not db_connection.features.has_select_for_update_skip_locked:
            raise RuntimeError(
                f'Database backend "{db_connection.vendor}" does not support '
                f'SELECT FOR UPDATE SKIP LOCKED. '
                f'django-celery-outbox requires PostgreSQL >= 9.5 or MySQL >= 8.0.1.'
            )
```

- [ ] **Step 3.4: Run test to verify it passes**

Run: `docker compose run --rm app pytest django_celery_outbox/relay_tests.py::test_relay_init_raises_when_skip_locked_not_supported -v`
Expected: PASS

- [ ] **Step 3.5: Write test — accepts when skip_locked supported**

Add to `django_celery_outbox/relay_tests.py`:

```python
def test_relay_init_accepts_when_skip_locked_supported(m_celery_app: MagicMock) -> None:
    m_connection = MagicMock()
    m_connection.features.has_select_for_update_skip_locked = True

    with patch('django_celery_outbox.relay.connections', {'default': m_connection}):
        with patch('django_celery_outbox.relay.CeleryOutbox') as m_model:
            m_model.objects.db = 'default'
            relay = Relay(app=m_celery_app)

    assert relay is not None
```

- [ ] **Step 3.6: Run all new relay tests**

Run: `docker compose run --rm app pytest django_celery_outbox/relay_tests.py::test_relay_init_raises_when_skip_locked_not_supported django_celery_outbox/relay_tests.py::test_relay_init_accepts_when_skip_locked_supported -v`
Expected: 2 tests PASS

- [ ] **Step 3.7: Commit**

```bash
git add django_celery_outbox/relay.py django_celery_outbox/relay_tests.py
git commit -m "feat: add database validation in Relay.__init__

Raises RuntimeError if database does not support SELECT FOR UPDATE
SKIP LOCKED. Provides clear error message with supported databases."
```

---

### Task 4: Update pyproject.toml — Database Drivers

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 4.1: Add database drivers to test dependencies**

Update `[project.optional-dependencies]` section in `pyproject.toml`:

```toml
test = [
  "pytest>=7.0",
  "pytest-django>=4.5",
  "factory-boy>=3.3",
  "psycopg[binary]>=3.1",
  "mysqlclient>=2.2",
]
```

- [ ] **Step 4.2: Commit**

```bash
git add pyproject.toml
git commit -m "build: add psycopg and mysqlclient to test dependencies"
```

---

### Task 5: Update docker-compose.yml — Database Services

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 5.1: Add postgres and mysql services**

Replace entire `docker-compose.yml`:

```yaml
services:
  app:
    build: .
    volumes:
      - .:/app
    working_dir: /app
    depends_on:
      - postgres
      - mysql
    environment:
      - DB_ENGINE=postgresql
      - DB_HOST=postgres
      - DB_NAME=test_db
      - DB_USER=test
      - DB_PASSWORD=test

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: test_db
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U test -d test_db']
      interval: 5s
      timeout: 5s
      retries: 5

  mysql:
    image: mysql:8.0
    environment:
      MYSQL_DATABASE: test_db
      MYSQL_USER: test
      MYSQL_PASSWORD: test
      MYSQL_ROOT_PASSWORD: root
    healthcheck:
      test: ['CMD', 'mysqladmin', 'ping', '-h', 'localhost']
      interval: 5s
      timeout: 5s
      retries: 5
```

- [ ] **Step 5.2: Validate YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"`
Expected: No output (success)

- [ ] **Step 5.3: Commit**

```bash
git add docker-compose.yml
git commit -m "build: add postgres and mysql services to docker-compose"
```

---

### Task 6: Update tests/settings.py — Database Switching

**Files:**
- Modify: `tests/settings.py`

- [ ] **Step 6.1: Replace settings.py with env-based config**

Replace entire `tests/settings.py`:

```python
import os

SECRET_KEY = 'test-secret-key'

DB_ENGINE = os.environ.get('DB_ENGINE', 'postgresql')

if DB_ENGINE == 'postgresql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'test_db'),
            'USER': os.environ.get('DB_USER', 'test'),
            'PASSWORD': os.environ.get('DB_PASSWORD', 'test'),
            'HOST': os.environ.get('DB_HOST', 'postgres'),
            'PORT': os.environ.get('DB_PORT', '5432'),
        }
    }
elif DB_ENGINE == 'mysql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('DB_NAME', 'test_db'),
            'USER': os.environ.get('DB_USER', 'test'),
            'PASSWORD': os.environ.get('DB_PASSWORD', 'test'),
            'HOST': os.environ.get('DB_HOST', 'mysql'),
            'PORT': os.environ.get('DB_PORT', '3306'),
        }
    }
else:
    raise ValueError(f'Unsupported DB_ENGINE: {DB_ENGINE}')

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.admin',
    'django_celery_outbox',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

USE_TZ = True
```

- [ ] **Step 6.2: Commit**

```bash
git add tests/settings.py
git commit -m "build: switch test database by DB_ENGINE env var

Supports postgresql and mysql. Removes SQLite support."
```

---

### Task 7: Update Dockerfile — Install System Dependencies

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 7.1: Update Dockerfile with system dependencies**

mysqlclient requires system packages. Replace entire `Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y \
    pkg-config \
    default-libmysqlclient-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install -e '.[dev,test]'
```

- [ ] **Step 7.2: Verify build**

Run: `docker compose build`
Expected: Build succeeds

- [ ] **Step 7.3: Commit**

```bash
git add Dockerfile
git commit -m "build: add system dependencies for mysqlclient"
```

---

### Task 8: Run Tests on PostgreSQL

**Files:** None (verification only)

- [ ] **Step 8.1: Start services**

Run: `docker compose up -d postgres`
Expected: postgres container starts

- [ ] **Step 8.2: Wait for postgres to be healthy**

Run: `docker compose exec postgres pg_isready -U test -d test_db`
Expected: `accepting connections`

- [ ] **Step 8.3: Run tests on PostgreSQL**

Run: `docker compose run --rm -e DB_ENGINE=postgresql app pytest -v`
Expected: All tests PASS

- [ ] **Step 8.4: Run tests on MySQL**

Run: `docker compose up -d mysql && sleep 10 && docker compose run --rm -e DB_ENGINE=mysql -e DB_HOST=mysql app pytest -v`
Expected: All tests PASS

---

### Task 9: Update GitHub Actions — Database Matrix

**Files:**
- Modify: `.github/workflows/tests.yml`

- [ ] **Step 9.1: Update test job with database matrix**

Replace the `test` job in `.github/workflows/tests.yml`:

```yaml
  test:
    name: Python ${{ matrix.python-version }} - Django ${{ matrix.django }} - ${{ matrix.db }}
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ['3.10', '3.11', '3.12']
        django: ['4.2', '5.0', '5.1', '5.2']
        db: ['postgresql', 'mysql']

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

      mysql:
        image: mysql:8.0
        env:
          MYSQL_DATABASE: test_db
          MYSQL_USER: test
          MYSQL_PASSWORD: test
          MYSQL_ROOT_PASSWORD: root
        options: >-
          --health-cmd "mysqladmin ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 3306:3306

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip

      - name: Install system dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y pkg-config default-libmysqlclient-dev

      - name: Upgrade pip
        run: python -m pip install --upgrade pip

      - name: Install package with test dependencies
        run: pip install -e '.[test]'

      - name: Install Django version
        run: pip install "Django~=${{ matrix.django }}"

      - name: Run tests
        env:
          DB_ENGINE: ${{ matrix.db }}
          DB_HOST: 127.0.0.1
          DB_NAME: test_db
          DB_USER: test
          DB_PASSWORD: test
          DB_PORT: ${{ matrix.db == 'postgresql' && '5432' || '3306' }}
        run: pytest -v
```

- [ ] **Step 9.2: Validate YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/tests.yml'))"`
Expected: No output (success)

- [ ] **Step 9.3: Commit**

```bash
git add .github/workflows/tests.yml
git commit -m "ci: add PostgreSQL and MySQL matrix to test workflow

Tests now run against both databases for each Python×Django combination."
```

---

### Task 10: Update README.md — Database Requirements

**Files:**
- Modify: `README.md`

- [ ] **Step 10.1: Add Database Requirements section after Features**

Insert after line 26 (after `- Health check endpoint for load balancer / k8s probes`):

```markdown

## Database Requirements

django-celery-outbox uses `SELECT FOR UPDATE SKIP LOCKED` for safe concurrent relay instances. This requires:

- **PostgreSQL >= 9.5**
- **MySQL >= 8.0.1**

SQLite is **not supported** and will raise an error at startup.
```

- [ ] **Step 10.2: Commit**

```bash
git add README.md
git commit -m "docs: add Database Requirements section to README

Documents that SQLite is not supported and lists required
PostgreSQL/MySQL versions."
```

---

### Task 11: Final Verification

**Files:** None (verification only)

- [ ] **Step 11.1: Run full test suite on PostgreSQL**

Run: `docker compose run --rm -e DB_ENGINE=postgresql app pytest -v`
Expected: All tests PASS

- [ ] **Step 11.2: Run full test suite on MySQL**

Run: `docker compose run --rm -e DB_ENGINE=mysql -e DB_HOST=mysql app pytest -v`
Expected: All tests PASS

- [ ] **Step 11.3: Run linter**

Run: `docker compose run --rm app ruff check .`
Expected: No errors

- [ ] **Step 11.4: Run type checker**

Run: `docker compose run --rm app mypy -p django_celery_outbox --config-file=pyproject.toml`
Expected: No errors

- [ ] **Step 11.5: Verify Django system check works**

Run: `docker compose run --rm app python manage.py check`
Expected: No errors (running on PostgreSQL)

---

## Summary

| Task | Description | Commits |
|------|-------------|---------|
| 1 | Django system check + tests | 1 |
| 2 | Register check in apps.py | 1 |
| 3 | Relay startup validation + tests | 1 |
| 4 | Add database drivers to pyproject.toml | 1 |
| 5 | Add postgres/mysql to docker-compose | 1 |
| 6 | Update tests/settings.py | 1 |
| 7 | Update Dockerfile | 1 |
| 8 | Verify tests on PostgreSQL/MySQL | 0 |
| 9 | Update GitHub Actions | 1 |
| 10 | Update README.md | 1 |
| 11 | Final verification | 0 |

**Total commits:** 9
