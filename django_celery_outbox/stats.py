import json
from dataclasses import dataclass
from datetime import timedelta
from typing import TypedDict, cast

from django.db.models import Q, Sum
from django.db.models.functions import Now
from django.utils import timezone

from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter
from django_celery_outbox.serialization import CURRENT_SCHEMA_VERSION, MIN_SUPPORTED_VERSION

_STALE_TIMEOUT = timedelta(minutes=5)


class TopFailingTask(TypedDict):
    task_name: str
    total_retries: int


@dataclass
class QueueStats:
    queue_depth: int
    dlq_count: int
    oldest_pending_seconds: float | None
    top_failing: list[TopFailingTask]

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
                lines.append(f'  {i}. {item["task_name"]} ({item["total_retries"]} retries)')

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


def get_queue_stats(top_n: int = 10) -> QueueStats:
    pending_filter = (
        Q(updated_at__isnull=True) | Q(retry_after__lte=Now()) | Q(updated_at__lte=Now() - _STALE_TIMEOUT, retry_after__isnull=True)
    ) & Q(
        schema_version__gte=MIN_SUPPORTED_VERSION,
        schema_version__lte=CURRENT_SCHEMA_VERSION,
    )
    pending_qs = CeleryOutbox.objects.filter(pending_filter)
    queue_depth = pending_qs.count()
    dlq_count = CeleryOutboxDeadLetter.objects.count()

    oldest = pending_qs.order_by('created_at').values_list('created_at', flat=True).first()
    if oldest:
        oldest_pending_seconds = (timezone.now() - oldest).total_seconds()
    else:
        oldest_pending_seconds = None

    top_failing: list[TopFailingTask] = []
    if top_n > 0:
        top_failing = cast(
            list[TopFailingTask],
            list(
                CeleryOutbox.objects.values('task_name')
                .annotate(total_retries=Sum('retries'))
                .filter(total_retries__gt=0)
                .order_by('-total_retries')[:top_n]
            ),
        )

    return QueueStats(
        queue_depth=queue_depth,
        dlq_count=dlq_count,
        oldest_pending_seconds=oldest_pending_seconds,
        top_failing=top_failing,
    )
