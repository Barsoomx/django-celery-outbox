# Dead Letter Purge Command

**Issue:** https://github.com/Barsoomx/django-celery-outbox/issues/18
**Date:** 2026-04-12

## Problem

`celery_outbox_dead_letter` grows forever. No cleanup command, no retention setting, no admin action for bulk purge. Operators must write their own SQL/scripts. This creates:
- Unbounded table growth on production
- GDPR/compliance risk: PII in task args retained indefinitely
- Storage cost and query degradation over time

## Solution

Management command + Celery task for purging old dead letter records with configurable retention policy.

## CLI Interface

```bash
python manage.py celery_outbox_purge_dead_letter \
    --older-than-dead=30d \
    --older-than-created=90d \
    --task-name="myapp.tasks.*" \
    --dry-run
```

### Flags

| Flag | Required | Description |
|------|----------|-------------|
| `--older-than-dead` | no | Delete records where `dead_at` is older than specified period |
| `--older-than-created` | no | Delete records where `created_at` is older than specified period |
| `--task-name` | no | Glob pattern for filtering by task name (fnmatch) |
| `--dry-run` | no | Show what would be deleted without deleting |

### Logic

- At least one of `--older-than-*` flags required (otherwise error)
- If both specified — AND logic (both conditions must match)
- `--task-name` supports wildcards: `myapp.*`, `*.cleanup`, `myapp.tasks.send_*`

### Duration Format

`<number><unit>` where unit = `s|m|h|d|w` (seconds, minutes, hours, days, weeks)

Examples: `30d`, `2w`, `6h`, `90s`

## Django Setting

```python
CELERY_OUTBOX_DLQ_RETENTION = {
    'older_than_dead': '30d',      # optional
    'older_than_created': '90d',   # optional
    'task_name': 'myapp.tasks.*',  # optional
}
```

### Precedence

1. CLI flags have priority over setting
2. If no flags — use `CELERY_OUTBOX_DLQ_RETENTION`
3. If no flags and no setting — error "No retention policy specified"

## Celery Task

```python
# django_celery_outbox/tasks.py
@shared_task(name='celery_outbox.purge_dead_letter')
def purge_dead_letter():
    """Purge dead letter records based on CELERY_OUTBOX_DLQ_RETENTION setting."""
```

### Usage with Celery Beat

```python
CELERY_BEAT_SCHEDULE = {
    'purge-dead-letter-nightly': {
        'task': 'celery_outbox.purge_dead_letter',
        'schedule': crontab(hour=3, minute=0),
    },
}
```

Task uses only `CELERY_OUTBOX_DLQ_RETENTION` setting (no parameters). For custom parameters use management command.

## Code Structure

### New Files

```
django_celery_outbox/
├── purge.py                    # Purge logic (PurgeResult, purge_dead_letter())
├── purge_tests.py              # Tests for purge.py
├── tasks.py                    # Celery task purge_dead_letter
├── tasks_tests.py              # Tests for tasks.py
├── management/
│   └── commands/
│       ├── celery_outbox_purge_dead_letter.py       # Management command
│       └── celery_outbox_purge_dead_letter_tests.py # Command tests
```

### Module `purge.py`

```python
@dataclass
class PurgeResult:
    deleted_count: int
    task_names: dict[str, int]  # {'myapp.task1': 5, 'myapp.task2': 3}

def parse_duration(value: str) -> timedelta:
    """Parse '30d', '2w', '6h' into timedelta."""

def purge_dead_letter(
    older_than_dead: timedelta | None = None,
    older_than_created: timedelta | None = None,
    task_name_pattern: str | None = None,
    dry_run: bool = False,
) -> PurgeResult:
    """Delete dead letter records matching criteria."""
```

### Dependencies

- `purge.py` — pure logic, depends only on models
- `tasks.py` — depends on `purge.py` + Django settings
- Management command — depends on `purge.py`

## Output

### Dry-run

```
Would delete 142 dead letter records:
  myapp.tasks.send_email: 89
  myapp.tasks.process_payment: 45
  myapp.tasks.sync_inventory: 8
```

### Actual Purge

```
Deleted 142 dead letter records:
  myapp.tasks.send_email: 89
  myapp.tasks.process_payment: 45
  myapp.tasks.sync_inventory: 8
```

### No Matches

```
No dead letter records match the specified criteria.
```

### Structlog Events

```python
logger.info(
    'celery_outbox_dead_letter_purged',
    deleted_count=142,
    dry_run=False,
    older_than_dead='30d',
    older_than_created='90d',
    task_name_pattern='myapp.*',
)
```

### Errors

- Invalid duration: `Invalid duration format: '30x'. Use <number><unit> where unit is s/m/h/d/w`
- No criteria: `No retention policy specified. Use --older-than-dead or --older-than-created, or set CELERY_OUTBOX_DLQ_RETENTION`

## README Documentation

Add to "Dead Letter Table" section:

### Purging Old Records

```bash
# Delete records dead for more than 30 days
python manage.py celery_outbox_purge_dead_letter --older-than-dead=30d

# Delete records created more than 90 days ago (GDPR compliance)
python manage.py celery_outbox_purge_dead_letter --older-than-created=90d

# Combine criteria (AND logic)
python manage.py celery_outbox_purge_dead_letter --older-than-dead=7d --older-than-created=30d

# Filter by task name pattern
python manage.py celery_outbox_purge_dead_letter --older-than-dead=30d --task-name="myapp.tasks.*"

# Dry run
python manage.py celery_outbox_purge_dead_letter --older-than-dead=30d --dry-run
```

### Automated Cleanup

```python
CELERY_OUTBOX_DLQ_RETENTION = {
    'older_than_dead': '30d',
    'older_than_created': '90d',
}

CELERY_BEAT_SCHEDULE = {
    'purge-dead-letter-nightly': {
        'task': 'celery_outbox.purge_dead_letter',
        'schedule': crontab(hour=3, minute=0),
    },
}
```

Add to Settings table:

| Setting | Default | Description |
|---------|---------|-------------|
| `CELERY_OUTBOX_DLQ_RETENTION` | `None` | Dict with retention policy for dead letter purge |

## Acceptance Criteria

- [x] New management command `celery_outbox_purge_dead_letter`
- [x] Dual filter: `--older-than-dead` and `--older-than-created`
- [x] Task name pattern filter
- [x] Dry-run mode
- [x] `CELERY_OUTBOX_DLQ_RETENTION` setting
- [x] Celery task for beat integration
- [x] Documented in README
- [ ] Tests
