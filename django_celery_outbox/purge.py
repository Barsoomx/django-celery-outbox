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


def _execute_purge(queryset: QuerySet, dry_run: bool) -> PurgeResult:
    task_names = dict(Counter(queryset.values_list('task_name', flat=True)))
    deleted_count = sum(task_names.values())

    if not dry_run and deleted_count > 0:
        queryset.delete()

    return PurgeResult(deleted_count=deleted_count, task_names=task_names)


def parse_duration(value: str) -> timedelta:
    match = _DURATION_PATTERN.match(value)
    if not match:
        raise ValueError(
            f'Invalid duration format: \'{value}\'. Use <number><unit> where unit is s/m/h/d/w'
        )

    amount = int(match.group(1))
    unit = match.group(2)
    seconds = amount * _UNIT_MULTIPLIERS[unit]

    return timedelta(seconds=seconds)
