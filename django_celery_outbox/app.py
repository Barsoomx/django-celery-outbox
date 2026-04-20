from collections.abc import Callable, Hashable
from copy import deepcopy
from functools import lru_cache
from typing import Any, cast

import sentry_sdk
import structlog
from celery import Celery
from celery.result import AsyncResult
from celery.utils import uuid
from django.conf import settings
from django.db import connections, transaction
from django.dispatch import Signal

from django_celery_outbox import metrics
from django_celery_outbox._settings import get_exclude_tasks_setting, load_pii_redactor_setting
from django_celery_outbox.metrics import get_task_tag
from django_celery_outbox.serialization import CURRENT_SCHEMA_VERSION, serialize_options
from django_celery_outbox.signals import outbox_message_created
from django_celery_outbox.structlog_utils import get_structlog_context_json

_logger = structlog.getLogger(__name__)


def _get_redactor_cache_key(setting_value: object) -> tuple[str, object]:
    if isinstance(setting_value, Hashable):
        return ('value', setting_value)
    return ('id', id(setting_value))


@lru_cache(maxsize=8)
def _get_redactor(cache_key: tuple[str, object]) -> Callable[[str, list, dict], tuple[list, dict]] | None:
    del cache_key
    return load_pii_redactor_setting()


def clear_redactor_cache() -> None:
    _get_redactor.cache_clear()


def _build_redacted_payloads(
    task_name: str,
    args_list: list[Any],
    kwargs_dict: dict[str, Any],
) -> tuple[list[Any] | None, dict[str, Any] | None]:
    redactor = _get_redactor(_get_redactor_cache_key(getattr(settings, 'CELERY_OUTBOX_PII_REDACTOR', None)))
    if redactor is None:
        return None, None

    payload = cast(
        dict[str, Any],
        deepcopy(
            {
                'args': args_list,
                'kwargs': kwargs_dict,
            }
        ),
    )
    redacted_args, redacted_kwargs = redactor(
        task_name,
        cast(list[Any], payload['args']),
        cast(dict[str, Any], payload['kwargs']),
    )
    return (
        redacted_args if redacted_args != args_list else None,
        redacted_kwargs if redacted_kwargs != kwargs_dict else None,
    )


def _redact_serialized_signature(
    task_name: str,
    signature: dict[str, Any],
    redactor: Callable[[str, list, dict], tuple[list, dict]],
) -> dict[str, Any]:
    signature_task_name = cast(str, signature.get('task', task_name))
    redacted_args, redacted_kwargs = redactor(
        signature_task_name,
        deepcopy(list(signature.get('args', []))),
        deepcopy(dict(signature.get('kwargs', {}))),
    )
    updated = dict(signature)
    updated['args'] = redacted_args
    updated['kwargs'] = redacted_kwargs
    nested_options = updated.get('options')
    if isinstance(nested_options, dict):
        updated['options'] = _redact_signature_options(signature_task_name, nested_options, redactor)
    return updated


def _redact_signature_options(
    task_name: str,
    options: dict[str, Any],
    redactor: Callable[[str, list, dict], tuple[list, dict]],
) -> dict[str, Any]:
    for key in ('link', 'link_error', 'chain'):
        if key in options and isinstance(options[key], list):
            options[key] = [_redact_serialized_signature(task_name, item, redactor) if isinstance(item, dict) else item for item in options[key]]
    if 'chord' in options and isinstance(options['chord'], dict):
        options['chord'] = _redact_serialized_signature(task_name, options['chord'], redactor)
    return options


def _redact_options_for_inspection(task_name: str, options: dict[str, Any]) -> dict[str, Any]:
    redactor = _get_redactor(_get_redactor_cache_key(getattr(settings, 'CELERY_OUTBOX_PII_REDACTOR', None)))
    if redactor is None:
        return options

    try:
        cloned = cast(dict[str, Any], deepcopy(options))
        return _redact_signature_options(task_name, cloned, redactor)
    except Exception:
        # Admin/debug inspection should keep working even if user redaction code misbehaves.
        _logger.warning(
            'celery_outbox_inspection_redaction_failed',
            task_name=task_name,
            exc_info=True,
        )
        return options


def _send_signal_safe(
    *,
    signal: Signal,
    signal_name: str,
    task_id: str,
    task_name: str,
) -> None:
    for receiver, response in signal.send_robust(
        sender=OutboxCelery,
        task_id=task_id,
        task_name=task_name,
    ):
        if isinstance(response, Exception):
            exc_info = (type(response), response, response.__traceback__)
            _logger.error(
                'celery_outbox_signal_error',
                signal=signal_name,
                task_id=task_id,
                task_name=task_name,
                receiver=getattr(receiver, '__qualname__', repr(receiver)),
                exception_type=type(response).__name__,
                exception_message=str(response),
                exc_info=exc_info,
            )


def _emit_enqueued_metric_safe(task_name: str) -> None:
    try:
        metrics.increment('messages.enqueued', tags=get_task_tag(task_name))
    except Exception:
        _logger.warning(
            'celery_outbox_metric_error',
            metric='messages.enqueued',
            task_name=task_name,
            exc_info=True,
        )


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
        exclude_tasks = get_exclude_tasks_setting()
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

        args_list = list(args) if args else []
        kwargs_dict = dict(kwargs) if kwargs else {}

        stored_redacted_args, stored_redacted_kwargs = _build_redacted_payloads(
            name,
            args_list,
            kwargs_dict,
        )
        from django_celery_outbox.models import CeleryOutbox

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
                args=args_list,
                kwargs=kwargs_dict,
                redacted_args=stored_redacted_args,
                redacted_kwargs=stored_redacted_kwargs,
                options=serialized_options,
                schema_version=CURRENT_SCHEMA_VERSION,
                sentry_trace_id=sentry_sdk.get_traceparent(),
                sentry_baggage=sentry_sdk.get_baggage(),
                structlog_context=get_structlog_context_json(),
            )

            _send_signal_safe(
                signal=outbox_message_created,
                signal_name='outbox_message_created',
                task_id=task_id,
                task_name=name,
            )
            transaction.on_commit(
                lambda: _emit_enqueued_metric_safe(name),
                using=CeleryOutbox.objects.db,
            )

            span.set_status('ok')

        actual_result_cls: type[AsyncResult] = result_cls or self.AsyncResult  # type: ignore[assignment]
        return actual_result_cls(task_id)
