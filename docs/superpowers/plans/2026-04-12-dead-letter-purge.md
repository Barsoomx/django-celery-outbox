# Dead Letter Purge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add management command and Celery task to purge old dead letter records with configurable retention policy.

**Architecture:** Core purge logic in `purge.py` with `parse_duration()` and `purge_dead_letter()`. Management command and Celery task are thin wrappers that call the core logic. Settings precedence: CLI flags > `CELERY_OUTBOX_DLQ_RETENTION` > error.

**Tech Stack:** Django management commands, Celery shared_task, fnmatch for glob patterns, dataclasses for results.

**Spec:** `docs/superpowers/specs/2026-04-12-dead-letter-purge-design.md`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `django_celery_outbox/purge.py` | `parse_duration()`, `PurgeResult`, `purge_dead_letter()` |
| `django_celery_outbox/purge_tests.py` | Tests for purge.py |
| `django_celery_outbox/tasks.py` | Celery task `purge_dead_letter` |
| `django_celery_outbox/tasks_tests.py` | Tests for tasks.py |
| `django_celery_outbox/management/commands/celery_outbox_purge_dead_letter.py` | Management command |
| `django_celery_outbox/management/commands/celery_outbox_purge_dead_letter_tests.py` | Command tests |
| `README.md` | Documentation updates |

---

### Task 1: parse_duration() function

**Files:**
- Create: `django_celery_outbox/purge.py`
- Create: `django_celery_outbox/purge_tests.py`

- [ ] **Step 1: Write failing tests for parse_duration**

Create `django_celery_outbox/purge_tests.py`:

```python
from datetime import timedelta

import pytest

from django_celery_outbox.purge import parse_duration


class TestParseDuration:
    def test_parses_seconds(self) -> None:
        result = parse_duration('90s')

        assert result == timedelta(seconds=90)

    def test_parses_minutes(self) -> None:
        result = parse_duration('30m')

        assert result == timedelta(minutes=30)

    def test_parses_hours(self) -> None:
        result = parse_duration('6h')

        assert result == timedelta(hours=6)

    def test_parses_days(self) -> None:
        result = parse_duration('30d')

        assert result == timedelta(days=30)

    def test_parses_weeks(self) -> None:
        result = parse_duration('2w')

        assert result == timedelta(weeks=2)

    def test_raises_on_invalid_unit(self) -> None:
        with pytest.raises(ValueError, match='Invalid duration format'):
            parse_duration('30x')

    def test_raises_on_empty_string(self) -> None:
        with pytest.raises(ValueError, match='Invalid duration format'):
            parse_duration('')

    def test_raises_on_missing_number(self) -> None:
        with pytest.raises(ValueError, match='Invalid duration format'):
            parse_duration('d')

    def test_raises_on_missing_unit(self) -> None:
        with pytest.raises(ValueError, match='Invalid duration format'):
            parse_duration('30')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/purge_tests.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'django_celery_outbox.purge'"

- [ ] **Step 3: Implement parse_duration**

Create `django_celery_outbox/purge.py`:

```python
import re
from datetime import timedelta

_DURATION_PATTERN = re.compile(r'^(\d+)([smhdw])$')
_UNIT_MULTIPLIERS = {
    's': 1,
    'm': 60,
    'h': 3600,
    'd': 86400,
    'w': 604800,
}


def parse_duration(value: str) -> timedelta:
    match = _DURATION_PATTERN.match(value)
    if not match:
        raise ValueError(
            f"Invalid duration format: '{value}'. Use <number><unit> where unit is s/m/h/d/w"
        )

    amount = int(match.group(1))
    unit = match.group(2)
    seconds = amount * _UNIT_MULTIPLIERS[unit]

    return timedelta(seconds=seconds)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/purge_tests.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/purge.py django_celery_outbox/purge_tests.py
git commit -m "feat(purge): add parse_duration function for duration strings"
```

---

### Task 2: PurgeResult dataclass

**Files:**
- Modify: `django_celery_outbox/purge.py`
- Modify: `django_celery_outbox/purge_tests.py`

- [ ] **Step 1: Write test for PurgeResult**

Add to `django_celery_outbox/purge_tests.py`:

```python
from django_celery_outbox.purge import PurgeResult


class TestPurgeResult:
    def test_stores_deleted_count_and_task_names(self) -> None:
        result = PurgeResult(
            deleted_count=10,
            task_names={'myapp.task1': 5, 'myapp.task2': 5},
        )

        assert result.deleted_count == 10
        assert result.task_names == {'myapp.task1': 5, 'myapp.task2': 5}

    def test_empty_result(self) -> None:
        result = PurgeResult(deleted_count=0, task_names={})

        assert result.deleted_count == 0
        assert result.task_names == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/purge_tests.py::TestPurgeResult -v`
Expected: FAIL with "ImportError: cannot import name 'PurgeResult'"

- [ ] **Step 3: Implement PurgeResult**

Add to `django_celery_outbox/purge.py` after imports:

```python
from dataclasses import dataclass


@dataclass
class PurgeResult:
    deleted_count: int
    task_names: dict[str, int]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/purge_tests.py::TestPurgeResult -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/purge.py django_celery_outbox/purge_tests.py
git commit -m "feat(purge): add PurgeResult dataclass"
```

---

### Task 3: purge_dead_letter with older_than_dead filter

**Files:**
- Modify: `django_celery_outbox/purge.py`
- Modify: `django_celery_outbox/purge_tests.py`

- [ ] **Step 1: Write tests for older_than_dead filter**

Add to `django_celery_outbox/purge_tests.py`:

```python
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from django_celery_outbox.factories import CeleryOutboxDeadLetterFactory
from django_celery_outbox.models import CeleryOutboxDeadLetter
from django_celery_outbox.purge import purge_dead_letter


@pytest.mark.django_db
class TestPurgeDeadLetterOlderThanDead:
    def test_deletes_records_older_than_specified_dead_at(self) -> None:
        now = timezone.now()
        with patch('django.utils.timezone.now', return_value=now):
            old_record = CeleryOutboxDeadLetterFactory(task_name='myapp.old_task')
        CeleryOutboxDeadLetter.objects.filter(pk=old_record.pk).update(
            dead_at=now - timedelta(days=31)
        )
        with patch('django.utils.timezone.now', return_value=now):
            new_record = CeleryOutboxDeadLetterFactory(task_name='myapp.new_task')

        result = purge_dead_letter(older_than_dead=timedelta(days=30))

        assert result.deleted_count == 1
        assert result.task_names == {'myapp.old_task': 1}
        assert not CeleryOutboxDeadLetter.objects.filter(pk=old_record.pk).exists()
        assert CeleryOutboxDeadLetter.objects.filter(pk=new_record.pk).exists()

    def test_returns_empty_result_when_no_matches(self) -> None:
        now = timezone.now()
        with patch('django.utils.timezone.now', return_value=now):
            CeleryOutboxDeadLetterFactory()

        result = purge_dead_letter(older_than_dead=timedelta(days=30))

        assert result.deleted_count == 0
        assert result.task_names == {}

    def test_aggregates_counts_by_task_name(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            r1 = CeleryOutboxDeadLetterFactory(task_name='myapp.task_a')
            r2 = CeleryOutboxDeadLetterFactory(task_name='myapp.task_a')
            r3 = CeleryOutboxDeadLetterFactory(task_name='myapp.task_b')
        CeleryOutboxDeadLetter.objects.filter(pk__in=[r1.pk, r2.pk, r3.pk]).update(
            dead_at=old_time
        )

        result = purge_dead_letter(older_than_dead=timedelta(days=30))

        assert result.deleted_count == 3
        assert result.task_names == {'myapp.task_a': 2, 'myapp.task_b': 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/purge_tests.py::TestPurgeDeadLetterOlderThanDead -v`
Expected: FAIL with "ImportError: cannot import name 'purge_dead_letter'"

- [ ] **Step 3: Implement purge_dead_letter with older_than_dead**

Add to `django_celery_outbox/purge.py`:

```python
from collections import Counter

from django.db.models import QuerySet
from django.utils import timezone

from django_celery_outbox.models import CeleryOutboxDeadLetter


def purge_dead_letter(
    older_than_dead: timedelta | None = None,
    older_than_created: timedelta | None = None,
    task_name_pattern: str | None = None,
    dry_run: bool = False,
) -> PurgeResult:
    queryset = CeleryOutboxDeadLetter.objects.all()
    now = timezone.now()

    if older_than_dead is not None:
        cutoff = now - older_than_dead
        queryset = queryset.filter(dead_at__lt=cutoff)

    return _execute_purge(queryset, dry_run)


def _execute_purge(queryset: QuerySet, dry_run: bool) -> PurgeResult:
    task_names = dict(Counter(queryset.values_list('task_name', flat=True)))
    deleted_count = sum(task_names.values())

    if not dry_run and deleted_count > 0:
        queryset.delete()

    return PurgeResult(deleted_count=deleted_count, task_names=task_names)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/purge_tests.py::TestPurgeDeadLetterOlderThanDead -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/purge.py django_celery_outbox/purge_tests.py
git commit -m "feat(purge): add purge_dead_letter with older_than_dead filter"
```

---

### Task 4: purge_dead_letter with older_than_created filter

**Files:**
- Modify: `django_celery_outbox/purge.py`
- Modify: `django_celery_outbox/purge_tests.py`

- [ ] **Step 1: Write tests for older_than_created filter**

Add to `django_celery_outbox/purge_tests.py`:

```python
@pytest.mark.django_db
class TestPurgeDeadLetterOlderThanCreated:
    def test_deletes_records_older_than_specified_created_at(self) -> None:
        now = timezone.now()
        old_record = CeleryOutboxDeadLetterFactory(
            task_name='myapp.old_task',
            created_at=now - timedelta(days=91),
        )
        new_record = CeleryOutboxDeadLetterFactory(
            task_name='myapp.new_task',
            created_at=now - timedelta(days=10),
        )

        result = purge_dead_letter(older_than_created=timedelta(days=90))

        assert result.deleted_count == 1
        assert result.task_names == {'myapp.old_task': 1}
        assert not CeleryOutboxDeadLetter.objects.filter(pk=old_record.pk).exists()
        assert CeleryOutboxDeadLetter.objects.filter(pk=new_record.pk).exists()

    def test_combines_with_older_than_dead_using_and_logic(self) -> None:
        now = timezone.now()
        old_dead = now - timedelta(days=31)
        old_created = now - timedelta(days=91)
        new_created = now - timedelta(days=10)

        with patch('django.utils.timezone.now', return_value=now):
            both_old = CeleryOutboxDeadLetterFactory(
                task_name='myapp.both_old',
                created_at=old_created,
            )
            only_dead_old = CeleryOutboxDeadLetterFactory(
                task_name='myapp.only_dead_old',
                created_at=new_created,
            )
            only_created_old = CeleryOutboxDeadLetterFactory(
                task_name='myapp.only_created_old',
                created_at=old_created,
            )
        CeleryOutboxDeadLetter.objects.filter(pk=both_old.pk).update(dead_at=old_dead)
        CeleryOutboxDeadLetter.objects.filter(pk=only_dead_old.pk).update(dead_at=old_dead)

        result = purge_dead_letter(
            older_than_dead=timedelta(days=30),
            older_than_created=timedelta(days=90),
        )

        assert result.deleted_count == 1
        assert result.task_names == {'myapp.both_old': 1}
        assert not CeleryOutboxDeadLetter.objects.filter(pk=both_old.pk).exists()
        assert CeleryOutboxDeadLetter.objects.filter(pk=only_dead_old.pk).exists()
        assert CeleryOutboxDeadLetter.objects.filter(pk=only_created_old.pk).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/purge_tests.py::TestPurgeDeadLetterOlderThanCreated -v`
Expected: FAIL (first test fails because older_than_created not implemented)

- [ ] **Step 3: Add older_than_created filter to purge_dead_letter**

Update `purge_dead_letter` in `django_celery_outbox/purge.py`:

```python
def purge_dead_letter(
    older_than_dead: timedelta | None = None,
    older_than_created: timedelta | None = None,
    task_name_pattern: str | None = None,
    dry_run: bool = False,
) -> PurgeResult:
    queryset = CeleryOutboxDeadLetter.objects.all()
    now = timezone.now()

    if older_than_dead is not None:
        cutoff = now - older_than_dead
        queryset = queryset.filter(dead_at__lt=cutoff)

    if older_than_created is not None:
        cutoff = now - older_than_created
        queryset = queryset.filter(created_at__lt=cutoff)

    return _execute_purge(queryset, dry_run)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/purge_tests.py::TestPurgeDeadLetterOlderThanCreated -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/purge.py django_celery_outbox/purge_tests.py
git commit -m "feat(purge): add older_than_created filter with AND logic"
```

---

### Task 5: purge_dead_letter with task_name_pattern filter

**Files:**
- Modify: `django_celery_outbox/purge.py`
- Modify: `django_celery_outbox/purge_tests.py`

- [ ] **Step 1: Write tests for task_name_pattern filter**

Add to `django_celery_outbox/purge_tests.py`:

```python
@pytest.mark.django_db
class TestPurgeDeadLetterTaskNamePattern:
    def test_filters_by_exact_task_name(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            match = CeleryOutboxDeadLetterFactory(task_name='myapp.tasks.send_email')
            no_match = CeleryOutboxDeadLetterFactory(task_name='myapp.tasks.process_payment')
        CeleryOutboxDeadLetter.objects.filter(pk__in=[match.pk, no_match.pk]).update(
            dead_at=old_time
        )

        result = purge_dead_letter(
            older_than_dead=timedelta(days=30),
            task_name_pattern='myapp.tasks.send_email',
        )

        assert result.deleted_count == 1
        assert result.task_names == {'myapp.tasks.send_email': 1}
        assert not CeleryOutboxDeadLetter.objects.filter(pk=match.pk).exists()
        assert CeleryOutboxDeadLetter.objects.filter(pk=no_match.pk).exists()

    def test_filters_by_wildcard_pattern(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            match1 = CeleryOutboxDeadLetterFactory(task_name='myapp.tasks.send_email')
            match2 = CeleryOutboxDeadLetterFactory(task_name='myapp.tasks.send_sms')
            no_match = CeleryOutboxDeadLetterFactory(task_name='other.tasks.process')
        CeleryOutboxDeadLetter.objects.filter(
            pk__in=[match1.pk, match2.pk, no_match.pk]
        ).update(dead_at=old_time)

        result = purge_dead_letter(
            older_than_dead=timedelta(days=30),
            task_name_pattern='myapp.tasks.send_*',
        )

        assert result.deleted_count == 2
        assert result.task_names == {'myapp.tasks.send_email': 1, 'myapp.tasks.send_sms': 1}
        assert CeleryOutboxDeadLetter.objects.filter(pk=no_match.pk).exists()

    def test_filters_by_prefix_pattern(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            match1 = CeleryOutboxDeadLetterFactory(task_name='myapp.tasks.a')
            match2 = CeleryOutboxDeadLetterFactory(task_name='myapp.other.b')
            no_match = CeleryOutboxDeadLetterFactory(task_name='other.tasks.c')
        CeleryOutboxDeadLetter.objects.filter(
            pk__in=[match1.pk, match2.pk, no_match.pk]
        ).update(dead_at=old_time)

        result = purge_dead_letter(
            older_than_dead=timedelta(days=30),
            task_name_pattern='myapp.*',
        )

        assert result.deleted_count == 2
        assert CeleryOutboxDeadLetter.objects.filter(pk=no_match.pk).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/purge_tests.py::TestPurgeDeadLetterTaskNamePattern -v`
Expected: FAIL (pattern not applied)

- [ ] **Step 3: Add task_name_pattern filter to purge_dead_letter**

Update `django_celery_outbox/purge.py`:

```python
import fnmatch
import re
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import QuerySet
from django.utils import timezone

from django_celery_outbox.models import CeleryOutboxDeadLetter

_DURATION_PATTERN = re.compile(r'^(\d+)([smhdw])$')
_UNIT_MULTIPLIERS = {
    's': 1,
    'm': 60,
    'h': 3600,
    'd': 86400,
    'w': 604800,
}


@dataclass
class PurgeResult:
    deleted_count: int
    task_names: dict[str, int]


def parse_duration(value: str) -> timedelta:
    match = _DURATION_PATTERN.match(value)
    if not match:
        raise ValueError(
            f"Invalid duration format: '{value}'. Use <number><unit> where unit is s/m/h/d/w"
        )

    amount = int(match.group(1))
    unit = match.group(2)
    seconds = amount * _UNIT_MULTIPLIERS[unit]

    return timedelta(seconds=seconds)


def purge_dead_letter(
    older_than_dead: timedelta | None = None,
    older_than_created: timedelta | None = None,
    task_name_pattern: str | None = None,
    dry_run: bool = False,
) -> PurgeResult:
    queryset = CeleryOutboxDeadLetter.objects.all()
    now = timezone.now()

    if older_than_dead is not None:
        cutoff = now - older_than_dead
        queryset = queryset.filter(dead_at__lt=cutoff)

    if older_than_created is not None:
        cutoff = now - older_than_created
        queryset = queryset.filter(created_at__lt=cutoff)

    if task_name_pattern is not None:
        regex = fnmatch.translate(task_name_pattern)
        queryset = queryset.filter(task_name__regex=regex)

    return _execute_purge(queryset, dry_run)


def _execute_purge(queryset: QuerySet, dry_run: bool) -> PurgeResult:
    task_names = dict(Counter(queryset.values_list('task_name', flat=True)))
    deleted_count = sum(task_names.values())

    if not dry_run and deleted_count > 0:
        queryset.delete()

    return PurgeResult(deleted_count=deleted_count, task_names=task_names)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/purge_tests.py::TestPurgeDeadLetterTaskNamePattern -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/purge.py django_celery_outbox/purge_tests.py
git commit -m "feat(purge): add task_name_pattern filter with glob support"
```

---

### Task 6: purge_dead_letter dry_run mode

**Files:**
- Modify: `django_celery_outbox/purge_tests.py`

- [ ] **Step 1: Write tests for dry_run mode**

Add to `django_celery_outbox/purge_tests.py`:

```python
@pytest.mark.django_db
class TestPurgeDeadLetterDryRun:
    def test_dry_run_returns_count_without_deleting(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            record = CeleryOutboxDeadLetterFactory(task_name='myapp.task')
        CeleryOutboxDeadLetter.objects.filter(pk=record.pk).update(dead_at=old_time)

        result = purge_dead_letter(older_than_dead=timedelta(days=30), dry_run=True)

        assert result.deleted_count == 1
        assert result.task_names == {'myapp.task': 1}
        assert CeleryOutboxDeadLetter.objects.filter(pk=record.pk).exists()

    def test_dry_run_false_deletes_records(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            record = CeleryOutboxDeadLetterFactory(task_name='myapp.task')
        CeleryOutboxDeadLetter.objects.filter(pk=record.pk).update(dead_at=old_time)

        result = purge_dead_letter(older_than_dead=timedelta(days=30), dry_run=False)

        assert result.deleted_count == 1
        assert not CeleryOutboxDeadLetter.objects.filter(pk=record.pk).exists()
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/purge_tests.py::TestPurgeDeadLetterDryRun -v`
Expected: 2 passed (dry_run already implemented in Task 3)

- [ ] **Step 3: Commit**

```bash
git add django_celery_outbox/purge_tests.py
git commit -m "test(purge): add explicit tests for dry_run mode"
```

---

### Task 7: Management command

**Files:**
- Create: `django_celery_outbox/management/commands/celery_outbox_purge_dead_letter.py`
- Create: `django_celery_outbox/management/commands/celery_outbox_purge_dead_letter_tests.py`

- [ ] **Step 1: Write tests for management command**

Create `django_celery_outbox/management/commands/celery_outbox_purge_dead_letter_tests.py`:

```python
from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from django_celery_outbox.purge import PurgeResult


class TestPurgeDeadLetterCommand:
    def test_requires_at_least_one_older_than_flag(self) -> None:
        with pytest.raises(CommandError, match='No retention policy specified'):
            call_command('celery_outbox_purge_dead_letter')

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_passes_older_than_dead_to_purge(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})

        call_command('celery_outbox_purge_dead_letter', older_than_dead='30d')

        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=30),
            older_than_created=None,
            task_name_pattern=None,
            dry_run=False,
        )

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_passes_older_than_created_to_purge(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})

        call_command('celery_outbox_purge_dead_letter', older_than_created='90d')

        m_purge.assert_called_once_with(
            older_than_dead=None,
            older_than_created=timedelta(days=90),
            task_name_pattern=None,
            dry_run=False,
        )

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_passes_both_filters_to_purge(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})

        call_command(
            'celery_outbox_purge_dead_letter',
            older_than_dead='7d',
            older_than_created='30d',
        )

        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=7),
            older_than_created=timedelta(days=30),
            task_name_pattern=None,
            dry_run=False,
        )

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_passes_task_name_pattern_to_purge(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})

        call_command(
            'celery_outbox_purge_dead_letter',
            older_than_dead='30d',
            task_name='myapp.tasks.*',
        )

        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=30),
            older_than_created=None,
            task_name_pattern='myapp.tasks.*',
            dry_run=False,
        )

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_passes_dry_run_flag(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})

        call_command('celery_outbox_purge_dead_letter', older_than_dead='30d', dry_run=True)

        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=30),
            older_than_created=None,
            task_name_pattern=None,
            dry_run=True,
        )

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_outputs_deleted_count(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(
            deleted_count=142,
            task_names={'myapp.task1': 100, 'myapp.task2': 42},
        )
        out = StringIO()

        call_command('celery_outbox_purge_dead_letter', older_than_dead='30d', stdout=out)

        output = out.getvalue()
        assert 'Deleted 142 dead letter records' in output
        assert 'myapp.task1: 100' in output
        assert 'myapp.task2: 42' in output

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_outputs_dry_run_message(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(
            deleted_count=10,
            task_names={'myapp.task': 10},
        )
        out = StringIO()

        call_command(
            'celery_outbox_purge_dead_letter',
            older_than_dead='30d',
            dry_run=True,
            stdout=out,
        )

        output = out.getvalue()
        assert 'Would delete 10 dead letter records' in output

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_outputs_no_matches_message(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})
        out = StringIO()

        call_command('celery_outbox_purge_dead_letter', older_than_dead='30d', stdout=out)

        output = out.getvalue()
        assert 'No dead letter records match the specified criteria' in output


class TestPurgeDeadLetterCommandSettings:
    @override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '30d'})
    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_uses_settings_when_no_flags(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})

        call_command('celery_outbox_purge_dead_letter')

        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=30),
            older_than_created=None,
            task_name_pattern=None,
            dry_run=False,
        )

    @override_settings(CELERY_OUTBOX_DLQ_RETENTION={
        'older_than_dead': '7d',
        'older_than_created': '90d',
        'task_name': 'myapp.*',
    })
    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_uses_all_settings_fields(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})

        call_command('celery_outbox_purge_dead_letter')

        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=7),
            older_than_created=timedelta(days=90),
            task_name_pattern='myapp.*',
            dry_run=False,
        )

    @override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '7d'})
    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_cli_flags_override_settings(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})

        call_command('celery_outbox_purge_dead_letter', older_than_dead='30d')

        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=30),
            older_than_created=None,
            task_name_pattern=None,
            dry_run=False,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/management/commands/celery_outbox_purge_dead_letter_tests.py -v`
Expected: FAIL with "Unknown command: 'celery_outbox_purge_dead_letter'"

- [ ] **Step 3: Implement management command**

Create `django_celery_outbox/management/commands/celery_outbox_purge_dead_letter.py`:

```python
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_celery_outbox.purge import PurgeResult, parse_duration, purge_dead_letter


class Command(BaseCommand):
    help = 'Purge old dead letter records from celery_outbox_dead_letter table'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            '--older-than-dead',
            type=str,
            default=None,
            help='Delete records where dead_at is older than specified period (e.g., 30d, 2w)',
        )
        parser.add_argument(
            '--older-than-created',
            type=str,
            default=None,
            help='Delete records where created_at is older than specified period (e.g., 90d)',
        )
        parser.add_argument(
            '--task-name',
            type=str,
            default=None,
            help='Glob pattern for filtering by task name (e.g., myapp.tasks.*)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )

    def handle(self, *args: Any, **options: Any) -> None:
        older_than_dead = self._get_duration('older_than_dead', options)
        older_than_created = self._get_duration('older_than_created', options)
        task_name_pattern = self._get_task_name_pattern(options)
        dry_run = options['dry_run']

        if older_than_dead is None and older_than_created is None:
            raise CommandError(
                'No retention policy specified. Use --older-than-dead or --older-than-created, '
                'or set CELERY_OUTBOX_DLQ_RETENTION'
            )

        result = purge_dead_letter(
            older_than_dead=older_than_dead,
            older_than_created=older_than_created,
            task_name_pattern=task_name_pattern,
            dry_run=dry_run,
        )

        self._output_result(result, dry_run)

    def _get_duration(self, key: str, options: dict[str, Any]) -> timedelta | None:
        cli_key = key.replace('_', '-')
        cli_value = options.get(key.replace('-', '_'))
        if cli_value:
            return parse_duration(cli_value)

        retention = getattr(settings, 'CELERY_OUTBOX_DLQ_RETENTION', None) or {}
        settings_value = retention.get(key)
        if settings_value:
            return parse_duration(settings_value)

        return None

    def _get_task_name_pattern(self, options: dict[str, Any]) -> str | None:
        cli_value = options.get('task_name')
        if cli_value:
            return cli_value

        retention = getattr(settings, 'CELERY_OUTBOX_DLQ_RETENTION', None) or {}

        return retention.get('task_name')

    def _output_result(self, result: PurgeResult, dry_run: bool) -> None:
        if result.deleted_count == 0:
            self.stdout.write('No dead letter records match the specified criteria.')

            return

        prefix = 'Would delete' if dry_run else 'Deleted'
        self.stdout.write(f'{prefix} {result.deleted_count} dead letter records:')
        for task_name, count in sorted(result.task_names.items()):
            self.stdout.write(f'  {task_name}: {count}')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/management/commands/celery_outbox_purge_dead_letter_tests.py -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/management/commands/celery_outbox_purge_dead_letter.py django_celery_outbox/management/commands/celery_outbox_purge_dead_letter_tests.py
git commit -m "feat(purge): add celery_outbox_purge_dead_letter management command"
```

---

### Task 8: Celery task

**Files:**
- Create: `django_celery_outbox/tasks.py`
- Create: `django_celery_outbox/tasks_tests.py`

- [ ] **Step 1: Write tests for Celery task**

Create `django_celery_outbox/tasks_tests.py`:

```python
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from django_celery_outbox.purge import PurgeResult


class TestPurgeDeadLetterTask:
    @override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '30d'})
    @patch('django_celery_outbox.tasks.purge_dead_letter')
    def test_calls_purge_with_settings(self, m_purge: MagicMock) -> None:
        from django_celery_outbox.tasks import purge_dead_letter_task

        m_purge.return_value = PurgeResult(deleted_count=5, task_names={'app.task': 5})

        result = purge_dead_letter_task()

        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=30),
            older_than_created=None,
            task_name_pattern=None,
            dry_run=False,
        )
        assert result == {'deleted_count': 5, 'task_names': {'app.task': 5}}

    @override_settings(CELERY_OUTBOX_DLQ_RETENTION={
        'older_than_dead': '7d',
        'older_than_created': '90d',
        'task_name': 'myapp.*',
    })
    @patch('django_celery_outbox.tasks.purge_dead_letter')
    def test_uses_all_settings_fields(self, m_purge: MagicMock) -> None:
        from django_celery_outbox.tasks import purge_dead_letter_task

        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})

        purge_dead_letter_task()

        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=7),
            older_than_created=timedelta(days=90),
            task_name_pattern='myapp.*',
            dry_run=False,
        )

    def test_raises_when_no_settings(self) -> None:
        from django_celery_outbox.tasks import purge_dead_letter_task

        with pytest.raises(ValueError, match='CELERY_OUTBOX_DLQ_RETENTION setting is required'):
            purge_dead_letter_task()

    @override_settings(CELERY_OUTBOX_DLQ_RETENTION={})
    def test_raises_when_settings_empty(self) -> None:
        from django_celery_outbox.tasks import purge_dead_letter_task

        with pytest.raises(ValueError, match='CELERY_OUTBOX_DLQ_RETENTION must specify'):
            purge_dead_letter_task()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/tasks_tests.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'django_celery_outbox.tasks'"

- [ ] **Step 3: Implement Celery task**

Create `django_celery_outbox/tasks.py`:

```python
from typing import Any

from celery import shared_task
from django.conf import settings

from django_celery_outbox.purge import parse_duration, purge_dead_letter


@shared_task(name='celery_outbox.purge_dead_letter')
def purge_dead_letter_task() -> dict[str, Any]:
    retention = getattr(settings, 'CELERY_OUTBOX_DLQ_RETENTION', None)
    if retention is None:
        raise ValueError(
            'CELERY_OUTBOX_DLQ_RETENTION setting is required for purge_dead_letter task'
        )

    older_than_dead_str = retention.get('older_than_dead')
    older_than_created_str = retention.get('older_than_created')
    task_name_pattern = retention.get('task_name')

    if not older_than_dead_str and not older_than_created_str:
        raise ValueError(
            'CELERY_OUTBOX_DLQ_RETENTION must specify older_than_dead or older_than_created'
        )

    older_than_dead = parse_duration(older_than_dead_str) if older_than_dead_str else None
    older_than_created = parse_duration(older_than_created_str) if older_than_created_str else None

    result = purge_dead_letter(
        older_than_dead=older_than_dead,
        older_than_created=older_than_created,
        task_name_pattern=task_name_pattern,
        dry_run=False,
    )

    return {
        'deleted_count': result.deleted_count,
        'task_names': result.task_names,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/tasks_tests.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/tasks.py django_celery_outbox/tasks_tests.py
git commit -m "feat(purge): add Celery task for beat integration"
```

---

### Task 9: README documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update Dead Letter Table section**

Find the "Dead Letter Table" section in README.md and add after the existing content:

```markdown
### Purging Old Records

To prevent unbounded table growth, use the purge command:

```bash
# Delete records dead for more than 30 days
python manage.py celery_outbox_purge_dead_letter --older-than-dead=30d

# Delete records created more than 90 days ago (GDPR compliance)
python manage.py celery_outbox_purge_dead_letter --older-than-created=90d

# Combine criteria (AND logic)
python manage.py celery_outbox_purge_dead_letter --older-than-dead=7d --older-than-created=30d

# Filter by task name pattern
python manage.py celery_outbox_purge_dead_letter --older-than-dead=30d --task-name="myapp.tasks.*"

# Dry run - see what would be deleted
python manage.py celery_outbox_purge_dead_letter --older-than-dead=30d --dry-run
```

Duration format: `<number><unit>` where unit is `s` (seconds), `m` (minutes), `h` (hours), `d` (days), or `w` (weeks).

### Automated Cleanup

Configure a retention policy in settings:

```python
CELERY_OUTBOX_DLQ_RETENTION = {
    'older_than_dead': '30d',
    'older_than_created': '90d',
    'task_name': 'myapp.tasks.*',  # optional
}
```

Schedule via Celery Beat:

```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'purge-dead-letter-nightly': {
        'task': 'celery_outbox.purge_dead_letter',
        'schedule': crontab(hour=3, minute=0),
    },
}
```

Or run the management command from cron (uses `CELERY_OUTBOX_DLQ_RETENTION` automatically):

```bash
0 3 * * * cd /app && python manage.py celery_outbox_purge_dead_letter
```
```

- [ ] **Step 2: Add setting to Configuration table**

Find the Configuration table and add a new row:

```markdown
| `CELERY_OUTBOX_DLQ_RETENTION` | `None` | Dict with retention policy for dead letter purge. Keys: `older_than_dead`, `older_than_created`, `task_name` |
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add dead letter purge documentation"
```

---

### Task 10: Run full test suite and verify

**Files:**
- None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `docker compose run --rm app pytest -v`
Expected: All tests pass

- [ ] **Step 2: Run linting**

Run: `docker compose run --rm app ruff check .`
Expected: No errors

- [ ] **Step 3: Run type checking**

Run: `docker compose run --rm app mypy -p django_celery_outbox --config-file=pyproject.toml`
Expected: No errors

- [ ] **Step 4: Final commit if any fixes needed**

If any fixes were made, commit them:
```bash
git add -A
git commit -m "fix: address linting and type issues"
```

---

## Summary

| Task | Description | New Files |
|------|-------------|-----------|
| 1 | parse_duration() function | purge.py, purge_tests.py |
| 2 | PurgeResult dataclass | - |
| 3 | purge_dead_letter with older_than_dead | - |
| 4 | older_than_created filter | - |
| 5 | task_name_pattern filter | - |
| 6 | dry_run mode tests | - |
| 7 | Management command | celery_outbox_purge_dead_letter.py, tests |
| 8 | Celery task | tasks.py, tasks_tests.py |
| 9 | README documentation | - |
| 10 | Verification | - |
