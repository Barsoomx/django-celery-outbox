# Celery Version Matrix CI Design

**Issue:** [#28](https://github.com/Barsoomx/django-celery-outbox/issues/28)  
**Date:** 2026-04-12  
**Status:** Approved (updated after CI PostgreSQL/MySQL integration)

## Problem

CI тестирует только одну версию Celery (из pip resolve), при этом `pyproject.toml` декларирует `celery>=5.3` без верхней границы. Когда Celery выпускает breaking changes между минорными версиями (например, изменение сигнатуры `send_task()`), библиотека может молча сломаться для пользователей.

## Current State

После параллельной работы CI уже имеет:
- Matrix: Python 3.10/3.11/3.12 × Django 4.2/5.0/5.1/5.2 × DB postgresql/mysql
- Services для PostgreSQL 15 и MySQL 8.0
- 24 jobs (3×4×2)

## Solution

### 1. Комбинированный matrix подход

**PostgreSQL** — полный Celery matrix (основная БД для SKIP LOCKED):
```yaml
matrix:
  python-version: ["3.10", "3.11", "3.12"]
  django: ["4.2", "5.2"]  # LTS + latest
  celery: ["5.3", "5.4", "5.5", "5.6"]
  db: ["postgresql"]
```
**24 jobs** (3×2×4×1)

**MySQL** — только latest Celery (проверка DB-совместимости):
```yaml
include:
  - python-version: "3.10"
    django: "4.2"
    celery: "5.6"
    db: "mysql"
  - python-version: "3.11"
    django: "4.2"
    celery: "5.6"
    db: "mysql"
  - python-version: "3.12"
    django: "4.2"
    celery: "5.6"
    db: "mysql"
  - python-version: "3.10"
    django: "5.2"
    celery: "5.6"
    db: "mysql"
  - python-version: "3.11"
    django: "5.2"
    celery: "5.6"
    db: "mysql"
  - python-version: "3.12"
    django: "5.2"
    celery: "5.6"
    db: "mysql"
```
**6 jobs** (3×2×1×1)

### 2. Обновлённый tests.yml

```yaml
test:
  name: Py${{ matrix.python-version }} Django${{ matrix.django }} Celery${{ matrix.celery }} ${{ matrix.db }}
  runs-on: ubuntu-latest
  strategy:
    fail-fast: false
    matrix:
      python-version: ["3.10", "3.11", "3.12"]
      django: ["4.2", "5.2"]
      celery: ["5.3", "5.4", "5.5", "5.6"]
      db: ["postgresql"]
      include:
        # MySQL with latest Celery only
        - python-version: "3.10"
          django: "4.2"
          celery: "5.6"
          db: "mysql"
        - python-version: "3.11"
          django: "4.2"
          celery: "5.6"
          db: "mysql"
        - python-version: "3.12"
          django: "4.2"
          celery: "5.6"
          db: "mysql"
        - python-version: "3.10"
          django: "5.2"
          celery: "5.6"
          db: "mysql"
        - python-version: "3.11"
          django: "5.2"
          celery: "5.6"
          db: "mysql"
        - python-version: "3.12"
          django: "5.2"
          celery: "5.6"
          db: "mysql"

  services:
    postgres:
      image: postgres:15
      # ... existing config
    mysql:
      image: mysql:8.0
      # ... existing config

  steps:
    # ... existing steps ...
    - name: Install Django version
      run: pip install "Django~=${{ matrix.django }}"
    - name: Install Celery version
      run: pip install "celery~=${{ matrix.celery }}"
    - name: Run tests
      # ... existing env vars ...
```

### 3. Bleeding-edge job

```yaml
bleeding-edge:
  name: Bleeding Edge (latest Django + Celery)
  runs-on: ubuntu-latest
  continue-on-error: true
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
  steps:
    - uses: actions/checkout@v4
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: "3.12"
        cache: pip
    - name: Upgrade pip
      run: python -m pip install --upgrade pip
    - name: Install package with test dependencies
      run: pip install -e '.[test]'
    - name: Install latest Django and Celery
      run: pip install --upgrade Django celery
    - name: Run tests
      env:
        DB_ENGINE: postgresql
        DB_HOST: 127.0.0.1
        DB_NAME: test_db
        DB_USER: test
        DB_PASSWORD: test
        DB_PORT: 5432
      run: pytest -v
```

### 4. README таблица совместимости

Обновить секцию в README.md:

```markdown
## Compatibility

| Dependency | Versions |
|------------|----------|
| Python     | 3.10, 3.11, 3.12 |
| Django     | 4.2 LTS, 5.0, 5.1, 5.2 * |
| Celery     | 5.3, 5.4, 5.5, 5.6 |
| Database   | PostgreSQL 15+, MySQL 8.0+ |

\* CI tests LTS (4.2) and latest (5.2); intermediate versions supported but not tested in every combination.
```

## Job Summary

| Job Type | Count | Coverage |
|----------|-------|----------|
| PostgreSQL + Celery matrix | 24 | 3 Py × 2 Dj × 4 Cel |
| MySQL + latest Celery | 6 | 3 Py × 2 Dj × 1 Cel |
| Bleeding-edge | 1 | Py3.12 + latest all |
| **Total** | **31** | |

## Decisions

### Без upper bounds в pyproject.toml

Оставляем `Django>=4.2` и `celery>=5.3` без верхних границ. CI bleeding-edge job даёт early warning о проблемах.

### Django 5.0/5.1 убраны из CI matrix

CI тестирует LTS (4.2) + latest (5.2). Промежуточные версии остаются в classifiers — библиотека их поддерживает, но не тестирует в каждой комбинации. Это решение принято для контроля размера matrix (issue #28 scope extension).

### PostgreSQL — основная БД для полного Celery matrix

Обе БД (PostgreSQL и MySQL 8.0+) поддерживают SKIP LOCKED. PostgreSQL выбрана для полного Celery matrix как primary production database. MySQL coverage сокращена для избежания избыточных комбинаций (не для технических ограничений).

### Job count trade-off

Текущий CI: 24 jobs (3 Py × 4 Dj × 2 DB). После изменений: 31 job (+29%). Trade-off: больше jobs, но 4× Celery coverage вместо 1×.

### Dependabot без изменений

Текущая конфигурация достаточна.

## Files Changed

1. `.github/workflows/tests.yml` — обновление matrix, добавление Celery axis, bleeding-edge job
2. `README.md` — таблица совместимости
