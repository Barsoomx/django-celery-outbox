# celery_outbox_stats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `celery_outbox_stats` management command to inspect outbox queue without Django admin.

**Architecture:** Dataclass `QueueStats` encapsulates stats with formatting methods. Function `get_queue_stats()` queries DB and returns dataclass. Management command delegates to function and outputs based on format flag.

**Tech Stack:** Django management commands, Django ORM (Sum aggregate), dataclasses, pytest

**Spec:** `docs/superpowers/specs/2026-04-12-operator-cli-stats-design.md`

---

## File Structure

```
django_celery_outbox/
├── stats.py                              # QueueStats dataclass + get_queue_stats()
├── stats_tests.py                        # Tests for stats module
├── management/commands/
│   ├── celery_outbox_stats.py            # Management command
│   └── celery_outbox_stats_tests.py      # Tests for command
```

---

### Task 1: QueueStats dataclass with formatting methods

**Files:**
- Create: `django_celery_outbox/stats.py`
- Create: `django_celery_outbox/stats_tests.py`

- [ ] **Step 1: Write failing tests for QueueStats**

Create `django_celery_outbox/stats_tests.py`:

```python
import json

import pytest


def test_queue_stats_to_dict() -> None:
    from django_celery_outbox.stats import QueueStats

    stats = QueueStats(
        queue_depth=125,
        dlq_count=3,
        oldest_pending_seconds=8130.5,
        top_failing=[
            {'task_name': 'app.tasks.send_email', 'total_retries': 42},
            {'task_name': 'app.tasks.sync_data', 'total_retries': 15},
        ],
    )

    result = stats.to_dict()

    assert result == {
        'queue_depth': 125,
        'dlq_count': 3,
        'oldest_pending_seconds': 8130.5,
        'top_failing': [
            {'task_name': 'app.tasks.send_email', 'total_retries': 42},
            {'task_name': 'app.tasks.sync_data', 'total_retries': 15},
        ],
    }


def test_queue_stats_to_json() -> None:
    from django_celery_outbox.stats import QueueStats

    stats = QueueStats(
        queue_depth=125,
        dlq_count=3,
        oldest_pending_seconds=8130.5,
        top_failing=[{'task_name': 'app.tasks.send_email', 'total_retries': 42}],
    )

    result = stats.to_json()
    parsed = json.loads(result)

    assert parsed['queue_depth'] == 125
    assert parsed['dlq_count'] == 3
    assert parsed['oldest_pending_seconds'] == 8130.5
    assert parsed['top_failing'] == [{'task_name': 'app.tasks.send_email', 'total_retries': 42}]


def test_queue_stats_to_text_with_all_data() -> None:
    from django_celery_outbox.stats import QueueStats

    stats = QueueStats(
        queue_depth=125,
        dlq_count=3,
        oldest_pending_seconds=8130.0,
        top_failing=[
            {'task_name': 'app.tasks.send_email', 'total_retries': 42},
            {'task_name': 'app.tasks.sync_data', 'total_retries': 15},
        ],
    )

    result = stats.to_text()

    assert 'Queue depth:     125' in result
    assert 'DLQ count:       3' in result
    assert 'Oldest pending:  2h 15m 30s' in result
    assert 'Top failing tasks:' in result
    assert '1. app.tasks.send_email (42 retries)' in result
    assert '2. app.tasks.sync_data (15 retries)' in result


def test_queue_stats_to_text_with_no_oldest_pending() -> None:
    from django_celery_outbox.stats import QueueStats

    stats = QueueStats(
        queue_depth=0,
        dlq_count=0,
        oldest_pending_seconds=None,
        top_failing=[],
    )

    result = stats.to_text()

    assert 'Oldest pending:  -' in result
    assert 'Top failing tasks:' not in result


def test_queue_stats_format_duration_hours() -> None:
    from django_celery_outbox.stats import QueueStats

    result = QueueStats._format_duration(3661.0)

    assert result == '1h 1m 1s'


def test_queue_stats_format_duration_minutes() -> None:
    from django_celery_outbox.stats import QueueStats

    result = QueueStats._format_duration(125.0)

    assert result == '2m 5s'


def test_queue_stats_format_duration_seconds_only() -> None:
    from django_celery_outbox.stats import QueueStats

    result = QueueStats._format_duration(45.0)

    assert result == '45s'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/stats_tests.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'django_celery_outbox.stats'`

- [ ] **Step 3: Implement QueueStats dataclass**

Create `django_celery_outbox/stats.py`:

```python
import json
from dataclasses import dataclass


@dataclass
class QueueStats:
    queue_depth: int
    dlq_count: int
    oldest_pending_seconds: float | None
    top_failing: list[dict]

    def to_dict(self) -> dict:
        return {
            'queue_depth': self.queue_depth,
            'dlq_count': self.dlq_count,
            'oldest_pending_seconds': self.oldest_pending_seconds,
            'top_failing': self.top_failing,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_text(self) -> str:
        lines = [
            f'Queue depth:     {self.queue_depth}',
            f'DLQ count:       {self.dlq_count}',
        ]
        if self.oldest_pending_seconds is not None:
            lines.append(f'Oldest pending:  {self._format_duration(self.oldest_pending_seconds)}')
        else:
            lines.append('Oldest pending:  -')

        if self.top_failing:
            lines.append('')
            lines.append('Top failing tasks:')
            for i, item in enumerate(self.top_failing, 1):
                lines.append(f"  {i}. {item['task_name']} ({item['total_retries']} retries)")

        return '\n'.join(lines)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        hours, remainder = divmod(int(seconds), 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f'{hours}h {minutes}m {secs}s'

        if minutes:
            return f'{minutes}m {secs}s'

        return f'{secs}s'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/stats_tests.py -v`

Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/stats.py django_celery_outbox/stats_tests.py
git commit -m "feat: add QueueStats dataclass with formatting methods"
```

---

### Task 2: get_queue_stats() function

**Files:**
- Modify: `django_celery_outbox/stats.py`
- Modify: `django_celery_outbox/stats_tests.py`

- [ ] **Step 1: Write failing tests for get_queue_stats**

Append to `django_celery_outbox/stats_tests.py`:

```python
from django.utils import timezone

from django_celery_outbox.factories import CeleryOutboxFactory, CeleryOutboxDeadLetterFactory


@pytest.mark.django_db
def test_get_queue_stats_empty_queue() -> None:
    from django_celery_outbox.stats import get_queue_stats

    result = get_queue_stats()

    assert result.queue_depth == 0
    assert result.dlq_count == 0
    assert result.oldest_pending_seconds is None
    assert result.top_failing == []


@pytest.mark.django_db
def test_get_queue_stats_with_pending_messages() -> None:
    from django_celery_outbox.stats import get_queue_stats

    CeleryOutboxFactory.create_batch(5)

    result = get_queue_stats()

    assert result.queue_depth == 5


@pytest.mark.django_db
def test_get_queue_stats_with_dlq() -> None:
    from django_celery_outbox.stats import get_queue_stats

    CeleryOutboxDeadLetterFactory.create_batch(3)

    result = get_queue_stats()

    assert result.dlq_count == 3


@pytest.mark.django_db
def test_get_queue_stats_oldest_pending() -> None:
    from django_celery_outbox.stats import get_queue_stats
    from datetime import timedelta

    old_time = timezone.now() - timedelta(hours=2)
    CeleryOutboxFactory.create(created_at=old_time)
    CeleryOutboxFactory.create()

    result = get_queue_stats()

    assert result.oldest_pending_seconds is not None
    assert result.oldest_pending_seconds >= 7200


@pytest.mark.django_db
def test_get_queue_stats_top_failing() -> None:
    from django_celery_outbox.stats import get_queue_stats

    CeleryOutboxFactory.create(task_name='app.tasks.high_fail', retries=10)
    CeleryOutboxFactory.create(task_name='app.tasks.high_fail', retries=5)
    CeleryOutboxFactory.create(task_name='app.tasks.low_fail', retries=2)
    CeleryOutboxFactory.create(task_name='app.tasks.no_fail', retries=0)

    result = get_queue_stats(top_n=10)

    assert len(result.top_failing) == 2
    assert result.top_failing[0]['task_name'] == 'app.tasks.high_fail'
    assert result.top_failing[0]['total_retries'] == 15
    assert result.top_failing[1]['task_name'] == 'app.tasks.low_fail'
    assert result.top_failing[1]['total_retries'] == 2


@pytest.mark.django_db
def test_get_queue_stats_top_n_limits_results() -> None:
    from django_celery_outbox.stats import get_queue_stats

    CeleryOutboxFactory.create(task_name='app.tasks.task_a', retries=10)
    CeleryOutboxFactory.create(task_name='app.tasks.task_b', retries=5)
    CeleryOutboxFactory.create(task_name='app.tasks.task_c', retries=2)

    result = get_queue_stats(top_n=2)

    assert len(result.top_failing) == 2


@pytest.mark.django_db
def test_get_queue_stats_top_n_zero_returns_empty_list() -> None:
    from django_celery_outbox.stats import get_queue_stats

    CeleryOutboxFactory.create(task_name='app.tasks.task_a', retries=10)

    result = get_queue_stats(top_n=0)

    assert result.top_failing == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/stats_tests.py::test_get_queue_stats_empty_queue -v`

Expected: FAIL with `ImportError: cannot import name 'get_queue_stats'`

- [ ] **Step 3: Implement get_queue_stats function**

Add to `django_celery_outbox/stats.py` (after QueueStats class):

```python
from django.db.models import Sum
from django.utils import timezone

from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter


def get_queue_stats(top_n: int = 10) -> QueueStats:
    queue_depth = CeleryOutbox.objects.count()
    dlq_count = CeleryOutboxDeadLetter.objects.count()

    oldest = CeleryOutbox.objects.order_by('created_at').values_list('created_at', flat=True).first()
    if oldest:
        oldest_pending_seconds = (timezone.now() - oldest).total_seconds()
    else:
        oldest_pending_seconds = None

    top_failing: list[dict] = []
    if top_n > 0:
        top_failing = list(
            CeleryOutbox.objects
            .values('task_name')
            .annotate(total_retries=Sum('retries'))
            .filter(total_retries__gt=0)
            .order_by('-total_retries')[:top_n]
        )

    return QueueStats(
        queue_depth=queue_depth,
        dlq_count=dlq_count,
        oldest_pending_seconds=oldest_pending_seconds,
        top_failing=top_failing,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/stats_tests.py -v`

Expected: All 15 tests PASS

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/stats.py django_celery_outbox/stats_tests.py
git commit -m "feat: add get_queue_stats function"
```

---

### Task 3: celery_outbox_stats management command

**Files:**
- Create: `django_celery_outbox/management/commands/celery_outbox_stats.py`
- Create: `django_celery_outbox/management/commands/celery_outbox_stats_tests.py`

- [ ] **Step 1: Write failing tests for management command**

Create `django_celery_outbox/management/commands/celery_outbox_stats_tests.py`:

```python
import json
from io import StringIO

import pytest
from django.core.management import call_command

from django_celery_outbox.factories import CeleryOutboxFactory


@pytest.mark.django_db
def test_command_outputs_text_by_default() -> None:
    CeleryOutboxFactory.create_batch(5)

    out = StringIO()
    call_command('celery_outbox_stats', stdout=out)

    output = out.getvalue()
    assert 'Queue depth:     5' in output
    assert 'DLQ count:' in output


@pytest.mark.django_db
def test_command_outputs_json_when_format_json() -> None:
    CeleryOutboxFactory.create_batch(3)

    out = StringIO()
    call_command('celery_outbox_stats', format='json', stdout=out)

    output = out.getvalue()
    data = json.loads(output)
    assert data['queue_depth'] == 3


@pytest.mark.django_db
def test_command_respects_top_argument() -> None:
    CeleryOutboxFactory.create(task_name='app.tasks.task_a', retries=10)
    CeleryOutboxFactory.create(task_name='app.tasks.task_b', retries=5)
    CeleryOutboxFactory.create(task_name='app.tasks.task_c', retries=2)

    out = StringIO()
    call_command('celery_outbox_stats', format='json', top=2, stdout=out)

    output = out.getvalue()
    data = json.loads(output)
    assert len(data['top_failing']) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest django_celery_outbox/management/commands/celery_outbox_stats_tests.py -v`

Expected: FAIL with `Unknown command: 'celery_outbox_stats'`

- [ ] **Step 3: Implement management command**

Create `django_celery_outbox/management/commands/celery_outbox_stats.py`:

```python
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from django_celery_outbox.stats import get_queue_stats


class Command(BaseCommand):
    help = 'Display celery outbox queue statistics'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            '--format',
            choices=['text', 'json'],
            default='text',
        )
        parser.add_argument(
            '--top',
            type=int,
            default=10,
        )

    def handle(self, *args: Any, **options: Any) -> None:
        stats = get_queue_stats(top_n=options['top'])

        if options['format'] == 'json':
            self.stdout.write(stats.to_json())
        else:
            self.stdout.write(stats.to_text())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest django_celery_outbox/management/commands/celery_outbox_stats_tests.py -v`

Expected: All 3 tests PASS

- [ ] **Step 5: Run all tests to ensure no regressions**

Run: `docker compose run --rm app pytest -v`

Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add django_celery_outbox/management/commands/celery_outbox_stats.py django_celery_outbox/management/commands/celery_outbox_stats_tests.py
git commit -m "feat: add celery_outbox_stats management command

Closes #27"
```

---

## Acceptance Criteria Checklist

- [ ] `celery_outbox_stats` command outputs queue depth, DLQ count, oldest pending age, top-N failing tasks
- [ ] Supports `--format=json|text`
- [ ] Supports `--top=N`
- [ ] All tests pass
