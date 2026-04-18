from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

    from django_celery_outbox.models import CeleryOutbox


_UNSET = object()


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
    if args is _UNSET:
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

        if kwargs is not _UNSET:
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
def fake_relay() -> FakeRelayRecorder:
    raise NotImplementedError('fake_relay fixture is not implemented yet')


@pytest.fixture(name='drain_outbox')
def drain_outbox_fixture() -> DrainOutbox:
    raise NotImplementedError('drain_outbox fixture is not implemented yet')
