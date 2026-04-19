from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

    from django_celery_outbox.models import CeleryOutbox


_UNSET = object()
_SEND_TASK_POSITIONAL_PARAMETER_NAMES = (
    'name',
    'args',
    'kwargs',
    'countdown',
    'eta',
    'task_id',
    'producer',
    'connection',
    'router',
    'result_cls',
    'expires',
    'publisher',
    'link',
    'link_error',
    'add_to_parent',
    'group_id',
    'group_index',
    'retries',
    'chord',
    'reply_to',
    'time_limit',
    'soft_time_limit',
    'root_id',
    'parent_id',
    'route_name',
    'shadow',
    'chain',
    'task_type',
    'replaced_task_nesting',
)


def _is_omitted(value: object) -> bool:
    return value is _UNSET or value is Ellipsis


@dataclass(slots=True)
class RecordedRelayCall:
    name: str
    args: list[Any]
    kwargs: dict[str, Any]
    task_id: str
    headers: dict[str, Any]
    options: dict[str, Any]


@dataclass(slots=True)
class FakeRelayRecorder:
    calls: list[RecordedRelayCall] = field(default_factory=list)


class AssertTaskSent(Protocol):
    def __call__(
        self,
        name: str,
        *,
        args: object = ...,
        kwargs: object = ...,
    ) -> CeleryOutbox: ...


class DrainOutbox(Protocol):
    def __call__(self) -> None: ...


__all__ = [
    'AssertTaskSent',
    'DrainOutbox',
    'FakeRelayRecorder',
    'RecordedRelayCall',
]


def _normalize_expected_args(args: object) -> object:
    if _is_omitted(args):
        return _UNSET

    if isinstance(args, tuple):
        return list(args)

    return args


def _summarize_queued_messages(outbox_model: type[CeleryOutbox]) -> str:
    queued_messages = [
        (f'{msg.task_name}(task_id={msg.task_id}, args={msg.inspection_args}, kwargs={msg.inspection_kwargs})')
        for msg in outbox_model.objects.order_by('id')
    ]

    return '; '.join(queued_messages) if queued_messages else 'none'


def _normalize_send_task_call(
    call_args: tuple[Any, ...],
    call_kwargs: dict[str, Any],
) -> dict[str, Any]:
    max_positional_arguments = len(_SEND_TASK_POSITIONAL_PARAMETER_NAMES)
    if len(call_args) > max_positional_arguments:
        raise TypeError(
            f'send_task() takes at most {max_positional_arguments} positional arguments after app, but {len(call_args)} were given',
        )

    normalized = dict(call_kwargs)
    for parameter_name, value in zip(_SEND_TASK_POSITIONAL_PARAMETER_NAMES, call_args, strict=False):
        if parameter_name in normalized:
            raise TypeError(f"send_task() got multiple values for argument '{parameter_name}'")
        normalized[parameter_name] = value

    if 'name' not in normalized:
        raise TypeError("send_task() missing required argument: 'name'")

    return normalized


def _format_remaining_rows(outbox_model: type[CeleryOutbox]) -> list[str]:
    return [
        (
            f'id={msg.id} task_name={msg.task_name} task_id={msg.task_id} '
            f'retries={msg.retries} retry_after={msg.retry_after} '
            f'updated_at={msg.updated_at} schema_version={msg.schema_version}'
        )
        for msg in outbox_model.objects.order_by('id')[:10]
    ]


@pytest.fixture()
def outbox(
    transactional_db: object,
    django_db_blocker: Any,
) -> Generator[type[CeleryOutbox], None, None]:
    del transactional_db

    import structlog.contextvars

    from django_celery_outbox.app import _get_redactor
    from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter

    def _reset_state() -> None:
        _get_redactor.cache_clear()
        structlog.contextvars.clear_contextvars()
        CeleryOutboxDeadLetter.objects.all().delete()
        CeleryOutbox.objects.all().delete()

    with django_db_blocker.unblock():
        _reset_state()

        try:
            yield CeleryOutbox
        finally:
            _reset_state()


@pytest.fixture(name='assert_task_sent')
def assert_task_sent_fixture(outbox: type[CeleryOutbox]) -> AssertTaskSent:
    def _assert_task_sent(
        name: str,
        *,
        args: object = _UNSET,
        kwargs: object = _UNSET,
    ) -> CeleryOutbox:
        queryset = outbox.objects.filter(task_name=name)

        normalized_args = _normalize_expected_args(args)
        if normalized_args is not _UNSET:
            queryset = queryset.filter(args=normalized_args)

        if not _is_omitted(kwargs):
            queryset = queryset.filter(kwargs=kwargs)

        matches = list(queryset.order_by('id'))
        queued_messages = _summarize_queued_messages(outbox)

        if not matches:
            raise AssertionError(
                f'Expected queued task {name!r}, found none. Queued messages: {queued_messages}',
            )

        if len(matches) > 1:
            raise AssertionError(
                f'Expected a single queued task {name!r}, found multiple queued tasks. Queued messages: {queued_messages}',
            )

        return matches[0]

    return _assert_task_sent


@pytest.fixture()
def fake_relay() -> Generator[FakeRelayRecorder, None, None]:
    from django_celery_outbox._settings import load_celery_app_setting
    from django_celery_outbox.relay._publisher import Celery

    recorder = FakeRelayRecorder()
    relay_app = load_celery_app_setting()
    original_send_task = Celery.send_task

    def _record(
        _app: Celery,
        *call_args: Any,
        **call_kwargs: Any,
    ) -> object:
        normalized_call = _normalize_send_task_call(call_args, call_kwargs)
        name = normalized_call.pop('name')
        args = normalized_call.pop('args', None)
        kwargs = normalized_call.pop('kwargs', None)
        task_id = normalized_call.pop('task_id', None)
        headers = normalized_call.pop('headers', None)

        if _app is not relay_app:
            delegated_options = dict(normalized_call)
            if headers is not None:
                delegated_options['headers'] = headers

            return original_send_task(
                _app,
                name=name,
                args=args,
                kwargs=kwargs,
                task_id=task_id,
                **delegated_options,
            )

        recorder.calls.append(
            RecordedRelayCall(
                name=name,
                args=list(args or []),
                kwargs=dict(kwargs or {}),
                task_id=task_id or '',
                headers=dict(headers or {}),
                options=dict(normalized_call),
            )
        )
        return None

    with patch(
        'django_celery_outbox.relay._publisher.Celery.send_task',
        side_effect=_record,
    ):
        yield recorder


@pytest.fixture(name='drain_outbox')
def drain_outbox_fixture(outbox: type[CeleryOutbox]) -> DrainOutbox:
    def _drain_outbox() -> None:
        from django_celery_outbox._settings import load_celery_app_setting
        from django_celery_outbox.relay import Relay, RelayConfig

        app = load_celery_app_setting()

        while True:
            before_count = outbox.objects.count()
            if before_count == 0:
                return

            relay = Relay(
                app=app,
                config=RelayConfig.init(idle_time=0),
            )

            with patch('django_celery_outbox.relay._relay.close_old_connections'):
                with patch('django_celery_outbox.relay._relay.time.sleep'):
                    relay._processing()

            after_count = outbox.objects.count()
            if after_count == 0:
                return

            if after_count < before_count:
                continue

            remaining_rows = _format_remaining_rows(outbox)
            raise AssertionError(
                'drain_outbox() could not fully drain the queue. '
                f'Rows before={before_count}, after={after_count}. '
                'Likely causes: future retry_after, in-flight rows, '
                'unsupported schema version, or broker send failures. '
                f'Remaining rows: {remaining_rows}'
            )

    return _drain_outbox
