# Celery Version Matrix CI Design

**Issue:** [#28](https://github.com/Barsoomx/django-celery-outbox/issues/28)  
**Date:** 2026-04-12  
**Status:** Approved

## Problem

CI тестирует только одну версию Celery (из pip resolve), при этом `pyproject.toml` декларирует `celery>=5.3` без верхней границы. Когда Celery выпускает breaking changes между минорными версиями (например, изменение сигнатуры `send_task()`), библиотека может молча сломаться для пользователей.

## Solution

### 1. Расширение CI matrix

Добавить ось Celery в matrix job `test`:

```yaml
test:
  name: Py${{ matrix.python-version }} Django${{ matrix.django }} Celery${{ matrix.celery }}
  runs-on: ubuntu-latest
  strategy:
    fail-fast: false
    matrix:
      python-version: ["3.10", "3.11", "3.12"]
      django: ["4.2", "5.2"]  # LTS + latest
      celery: ["5.3", "5.4", "5.5", "5.6"]
  steps:
    - uses: actions/checkout@v4
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}
        cache: pip
    - name: Upgrade pip
      run: python -m pip install --upgrade pip
    - name: Install package with test dependencies
      run: pip install -e '.[test]'
    - name: Install Django version
      run: pip install "Django~=${{ matrix.django }}"
    - name: Install Celery version
      run: pip install "celery~=${{ matrix.celery }}"
    - name: Run tests
      run: pytest -v
```

**Итого:** 3 Python × 2 Django × 4 Celery = 24 jobs

### 2. Bleeding-edge job

Отдельный job для раннего обнаружения проблем с новыми версиями:

```yaml
bleeding-edge:
  name: Bleeding Edge (latest Django + Celery)
  runs-on: ubuntu-latest
  continue-on-error: true
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
      run: pytest -v
```

`continue-on-error: true` — job показывает статус, но не блокирует merge.

### 3. README таблица совместимости

Добавить в README.md:

```markdown
## Compatibility

| Dependency | Versions |
|------------|----------|
| Python     | 3.10, 3.11, 3.12 |
| Django     | 4.2 LTS, 5.0, 5.1, 5.2 |
| Celery     | 5.3, 5.4, 5.5, 5.6 |
```

## Decisions

### Без upper bounds в pyproject.toml

Оставляем `Django>=4.2` и `celery>=5.3` без верхних границ. Причина: пользователи библиотеки сами решают, использовать ли новые major версии. CI bleeding-edge job даёт early warning о проблемах.

### Django 5.0/5.1 убраны из CI matrix

CI тестирует LTS (4.2) + latest (5.2). Промежуточные версии 5.0/5.1 остаются в classifiers — библиотека их поддерживает, но не тестирует в каждой Celery комбинации.

### Dependabot без изменений

Текущая конфигурация (weekly updates, security grouping) достаточна.

## Out of Scope

- Удаление `ci.yml` — отложено (параллельная работа над docker compose + PostgreSQL)
- Изменения в Dependabot
- Upper bounds в pyproject.toml

## Files Changed

1. `.github/workflows/tests.yml` — расширение matrix, добавление bleeding-edge job
2. `README.md` — таблица совместимости
