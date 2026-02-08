from typing import Any

import sentry_sdk
import structlog
from celery import Celery
from celery.result import AsyncResult
from celery.utils import uuid
from django.conf import settings
from django.db import connections

from django_celery_outbox.models import CeleryOutbox
from django_celery_outbox.serialization import serialize_options
from django_celery_outbox.signals import outbox_message_created
from django_celery_outbox.structlog_utils import get_structlog_context_json

_logger = structlog.getLogger(__name__)

_OUTBOX_OPTION_KEYS = (
    'expires',
    'link',
    'link_error',
    'chord',
    'chain',
    'group_id',
    'group_index',
    'time_limit',
    'soft_time_limit',
    'root_id',
    'parent_id',
    'route_name',
    'shadow',
)


def _collect_options(local_vars: dict[str, Any], extra_options: dict[str, Any]) -> dict[str, Any]:
    result = dict(extra_options)
    for key in _OUTBOX_OPTION_KEYS:
        val = local_vars.get(key)
        if val is not None:
            result[key] = val

    retries = local_vars.get('retries', 0)
    if retries:
        result['retries'] = retries

    return result


class OutboxCelery(Celery):
    def send_task(  # type: ignore[override]
        self,
        name: str,
        args: tuple | None = None,
        kwargs: dict | None = None,
        countdown: float | None = None,
        eta: Any | None = None,
        task_id: str | None = None,
        producer: Any | None = None,
        connection: Any | None = None,
        result_cls: type | None = None,
        expires: Any | None = None,
        publisher: Any | None = None,
        link: Any | None = None,
        link_error: Any | None = None,
        add_to_parent: bool = True,
        group_id: str | None = None,
        group_index: int | None = None,
        retries: int = 0,
        chord: Any | None = None,
        reply_to: str | None = None,
        time_limit: float | None = None,
        soft_time_limit: float | None = None,
        root_id: str | None = None,
        parent_id: str | None = None,
        route_name: str | None = None,
        shadow: str | None = None,
        chain: Any | None = None,
        task_type: Any | None = None,
        **options: Any,
    ) -> AsyncResult:
        exclude_tasks = set(getattr(settings, 'CELERY_OUTBOX_EXCLUDE_TASKS', ()))
        if name in exclude_tasks:
            return super().send_task(
                name,
                args=args,
                kwargs=kwargs,
                countdown=countdown,
                eta=eta,
                task_id=task_id,
                producer=producer,
                connection=connection,
                result_cls=result_cls,
                expires=expires,
                publisher=publisher,
                link=link,
                link_error=link_error,
                add_to_parent=add_to_parent,
                group_id=group_id,
                group_index=group_index,
                retries=retries,
                chord=chord,
                reply_to=reply_to,
                time_limit=time_limit,
                soft_time_limit=soft_time_limit,
                root_id=root_id,
                parent_id=parent_id,
                route_name=route_name,
                shadow=shadow,
                chain=chain,
                task_type=task_type,
                **options,
            )

        task_id = task_id or uuid()

        all_options = _collect_options(
            {
                'expires': expires,
                'link': link,
                'link_error': link_error,
                'chord': chord,
                'chain': chain,
                'group_id': group_id,
                'group_index': group_index,
                'time_limit': time_limit,
                'soft_time_limit': soft_time_limit,
                'root_id': root_id,
                'parent_id': parent_id,
                'route_name': route_name,
                'shadow': shadow,
                'retries': retries,
            },
            options,
        )

        serialized_options = serialize_options(
            all_options,
            countdown=countdown,
            eta=eta,
        )

        if not connections[CeleryOutbox.objects.db].in_atomic_block:
            _logger.warning(
                'celery_outbox_not_in_transaction',
                task_name=name,
                task_id=task_id,
            )

        with sentry_sdk.start_span(op='celery_outbox.intercept', name=name) as span:
            span.set_data('messaging.message.id', task_id)
            span.set_data('messaging.destination.name', 'celery_outbox')

            CeleryOutbox.objects.create(
                task_id=task_id,
                task_name=name,
                args=list(args) if args else [],
                kwargs=dict(kwargs) if kwargs else {},
                options=serialized_options,
                sentry_trace_id=sentry_sdk.get_traceparent(),
                sentry_baggage=sentry_sdk.get_baggage(),
                structlog_context=get_structlog_context_json(),
            )

            outbox_message_created.send(
                sender=OutboxCelery,
                task_id=task_id,
                task_name=name,
            )

            span.set_status('ok')

        actual_result_cls: type[AsyncResult] = result_cls or self.AsyncResult  # type: ignore[assignment]
        return actual_result_cls(task_id)
