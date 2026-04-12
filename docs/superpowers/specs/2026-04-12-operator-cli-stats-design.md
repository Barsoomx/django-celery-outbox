# Operator CLI: celery_outbox_stats

**Issue:** https://github.com/Barsoomx/django-celery-outbox/issues/27  
**Date:** 2026-04-12  
**Status:** Approved

## Problem

Operators have no CLI for inspecting the outbox queue without opening Django admin. Common questions during incidents:
- Current queue depth
- DLQ count
- Oldest pending message age
- Which tasks are failing most

## Scope

**In scope:**
- `celery_outbox_stats` management command

**Out of scope:**
- Drain mode (removed from scope per discussion)

## Design

### File Structure

```
django_celery_outbox/
├── stats.py                              # QueueStats dataclass + get_queue_stats()
├── stats_tests.py
├── management/commands/
│   ├── celery_outbox_stats.py
│   └── celery_outbox_stats_tests.py
```

### stats.py

```python
from dataclasses import dataclass
from django.db.models import Sum
from django.utils import timezone

from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter


@dataclass
class QueueStats:
    queue_depth: int
    dlq_count: int
    oldest_pending_seconds: float | None
    top_failing: list[dict]  # [{'task_name': str, 'total_retries': int}, ...]

    def to_dict(self) -> dict:
        return {
            'queue_depth': self.queue_depth,
            'dlq_count': self.dlq_count,
            'oldest_pending_seconds': self.oldest_pending_seconds,
            'top_failing': self.top_failing,
        }

    def to_json(self) -> str:
        import json
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
        elif minutes:
            return f'{minutes}m {secs}s'
        else:
            return f'{secs}s'


def get_queue_stats(top_n: int = 10) -> QueueStats:
    queue_depth = CeleryOutbox.objects.count()
    dlq_count = CeleryOutboxDeadLetter.objects.count()
    
    oldest = CeleryOutbox.objects.order_by('created_at').values_list('created_at', flat=True).first()
    if oldest:
        oldest_pending_seconds = (timezone.now() - oldest).total_seconds()
    else:
        oldest_pending_seconds = None
    
    top_failing = []
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

### Management Command

```python
# celery_outbox_stats.py
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

### Output Examples

**Text format (default):**
```
Queue depth:     125
DLQ count:       3
Oldest pending:  2h 15m 30s

Top failing tasks:
  1. my_app.tasks.send_email (42 retries)
  2. my_app.tasks.sync_data (15 retries)
```

**JSON format:**
```json
{
  "queue_depth": 125,
  "dlq_count": 3,
  "oldest_pending_seconds": 8130.5,
  "top_failing": [
    {"task_name": "my_app.tasks.send_email", "total_retries": 42},
    {"task_name": "my_app.tasks.sync_data", "total_retries": 15}
  ]
}
```

### Tests

**stats_tests.py:**
- `test_get_queue_stats_empty_queue`
- `test_get_queue_stats_with_pending_messages`
- `test_get_queue_stats_with_dlq`
- `test_get_queue_stats_oldest_pending`
- `test_get_queue_stats_top_failing`
- `test_queue_stats_to_json`
- `test_queue_stats_to_text`
- `test_queue_stats_format_duration`

**celery_outbox_stats_tests.py:**
- `test_command_outputs_text_by_default`
- `test_command_outputs_json_when_format_json`
- `test_command_respects_top_argument`

### Non-changes

- `admin.py` remains unchanged (different semantics for pending_count vs queue_depth)

## Acceptance Criteria

- [ ] `celery_outbox_stats` command outputs queue depth, DLQ count, oldest pending age, top-N failing tasks
- [ ] Supports `--format=json|text`
- [ ] Supports `--top=N`
- [ ] Tests pass
