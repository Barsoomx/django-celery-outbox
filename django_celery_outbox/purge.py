import re
from dataclasses import dataclass
from datetime import timedelta

import structlog
from django.db.models import Count, QuerySet
from django.utils import timezone

from django_celery_outbox.models import CeleryOutboxDeadLetter

_logger = structlog.getLogger(__name__)

_DURATION_PATTERN = re.compile(r'^(\d+)([smhdw])$')
_UNIT_MULTIPLIERS = {
    's': 1,
    'm': 60,
    'h': 3600,
    'd': 86400,
    'w': 604800,
}
_DELETE_CHUNK_SIZE = 1000


@dataclass
class PurgeResult:
    deleted_count: int
    task_names: dict[str, int]


def _glob_to_regex(pattern: str) -> str:
    regex = re.escape(pattern)
    regex = regex.replace(r'\*', '.*')
    regex = regex.replace(r'\?', '.')

    return f'^{regex}$'


def purge_dead_letter(
    older_than_dead: timedelta | None = None,
    older_than_created: timedelta | None = None,
    task_name_pattern: str | None = None,
    dry_run: bool = False,
) -> PurgeResult:
    if older_than_dead is None and older_than_created is None:
        raise ValueError('At least one of older_than_dead or older_than_created must be provided')

    queryset = CeleryOutboxDeadLetter.objects.all()
    now = timezone.now()

    if older_than_dead is not None:
        cutoff = now - older_than_dead
        queryset = queryset.filter(dead_at__lt=cutoff)

    if older_than_created is not None:
        cutoff = now - older_than_created
        queryset = queryset.filter(created_at__lt=cutoff)

    if task_name_pattern is not None:
        regex = _glob_to_regex(task_name_pattern)
        queryset = queryset.filter(task_name__regex=regex)

    result = _execute_purge(
        queryset,
        dry_run,
        chunk_ordering=_chunk_ordering(
            older_than_dead=older_than_dead,
            older_than_created=older_than_created,
        ),
    )

    _logger.info(
        'celery_outbox_dead_letter_purged',
        deleted_count=result.deleted_count,
        dry_run=dry_run,
        older_than_dead=str(older_than_dead) if older_than_dead else None,
        older_than_created=str(older_than_created) if older_than_created else None,
        task_name_pattern=task_name_pattern,
    )

    return result


def _chunk_ordering(
    *,
    older_than_dead: timedelta | None,
    older_than_created: timedelta | None,
) -> tuple[str, ...]:
    if older_than_dead is not None:
        return ('dead_at', 'pk')

    if older_than_created is not None:
        return ('created_at', 'pk')

    return ('pk',)


def _execute_purge(
    queryset: QuerySet,
    dry_run: bool,
    *,
    chunk_ordering: tuple[str, ...],
) -> PurgeResult:
    if dry_run:
        aggregated = queryset.values('task_name').annotate(count=Count('id'))
        task_names = {row['task_name']: row['count'] for row in aggregated}
        return PurgeResult(deleted_count=sum(task_names.values()), task_names=task_names)

    return _delete_in_chunks(queryset, chunk_ordering=chunk_ordering)


def _delete_in_chunks(
    queryset: QuerySet[CeleryOutboxDeadLetter],
    *,
    chunk_ordering: tuple[str, ...],
) -> PurgeResult:
    deleted_count = 0
    task_names: dict[str, int] = {}

    while rows := list(queryset.order_by(*chunk_ordering).values_list('pk', 'task_name')[:_DELETE_CHUNK_SIZE]):
        ids = [pk for pk, _task_name in rows]
        deleted_count += len(rows)
        for _pk, task_name in rows:
            task_names[task_name] = task_names.get(task_name, 0) + 1
        CeleryOutboxDeadLetter.objects.filter(pk__in=ids).delete()

    return PurgeResult(deleted_count=deleted_count, task_names=task_names)


def parse_duration(value: str) -> timedelta:
    match = _DURATION_PATTERN.match(value)
    if not match:
        raise ValueError(f"Invalid duration format: '{value}'. Use <number><unit> where unit is s/m/h/d/w")

    amount = int(match.group(1))
    unit = match.group(2)
    seconds = amount * _UNIT_MULTIPLIERS[unit]

    return timedelta(seconds=seconds)
