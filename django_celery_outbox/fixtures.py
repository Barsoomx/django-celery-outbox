from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import pytest

if TYPE_CHECKING:
    from django_celery_outbox.models import CeleryOutbox


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


@pytest.fixture()
def outbox() -> type[CeleryOutbox]:
    raise NotImplementedError('outbox fixture is not implemented yet')


@pytest.fixture(name='assert_task_sent')
def assert_task_sent_fixture() -> AssertTaskSent:
    raise NotImplementedError('assert_task_sent fixture is not implemented yet')


@pytest.fixture()
def fake_relay() -> FakeRelayRecorder:
    raise NotImplementedError('fake_relay fixture is not implemented yet')


@pytest.fixture(name='drain_outbox')
def drain_outbox_fixture() -> DrainOutbox:
    raise NotImplementedError('drain_outbox fixture is not implemented yet')
