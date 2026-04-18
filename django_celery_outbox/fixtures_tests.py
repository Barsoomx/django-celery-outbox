from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import structlog.contextvars

from django_celery_outbox import fixtures as fixtures_module


@dataclass(slots=True)
class FakeQueuedMessage:
    id: int
    task_name: str
    task_id: str
    args: list[Any]
    kwargs: dict[str, Any]


class FakeDeleteQuerySet:
    def __init__(self, manager: FakeManager) -> None:
        self._manager = manager

    def delete(self) -> tuple[int, dict[str, int]]:
        deleted_count = len(self._manager.rows)
        self._manager.rows.clear()
        self._manager.delete_calls += 1
        return deleted_count, {}


class FakeQuerySet:
    def __init__(self, rows: list[FakeQueuedMessage]) -> None:
        self._rows = rows

    def filter(self, **filters: object) -> FakeQuerySet:
        filtered_rows = [
            row for row in self._rows if all(getattr(row, field_name) == expected_value for field_name, expected_value in filters.items())
        ]
        return FakeQuerySet(filtered_rows)

    def order_by(self, field_name: str) -> list[FakeQueuedMessage]:
        return sorted(self._rows, key=lambda row: getattr(row, field_name))


class FakeManager:
    def __init__(self, rows: list[FakeQueuedMessage] | None = None) -> None:
        self.rows = list(rows or [])
        self.delete_calls = 0

    def all(self) -> FakeDeleteQuerySet:
        return FakeDeleteQuerySet(self)

    def filter(self, **filters: object) -> FakeQuerySet:
        return FakeQuerySet(self.rows).filter(**filters)

    def order_by(self, field_name: str) -> list[FakeQueuedMessage]:
        return FakeQuerySet(self.rows).order_by(field_name)


class CacheClearTracker:
    def __init__(self) -> None:
        self.clear_calls = 0

    def cache_clear(self) -> None:
        self.clear_calls += 1


class ContextVarsTracker:
    def __init__(self) -> None:
        self.clear_calls = 0

    def __call__(self) -> None:
        self.clear_calls += 1


class FakeModelBase:
    objects: FakeManager


def _build_fake_model(rows: list[FakeQueuedMessage]) -> type[FakeModelBase]:
    class FakeModel(FakeModelBase):
        objects = FakeManager(rows)

    return FakeModel


def _build_assert_task_sent(
    rows: list[FakeQueuedMessage],
) -> tuple[fixtures_module.AssertTaskSent, type[FakeModelBase]]:
    outbox_model = _build_fake_model(rows)
    assert_task_sent = fixtures_module.assert_task_sent_fixture.__wrapped__(outbox=outbox_model)
    return assert_task_sent, outbox_model


def test_outbox_fixture_cleans_models_redactor_cache_and_contextvars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import django_celery_outbox.app as app_module
    import django_celery_outbox.models as models_module

    outbox_model = _build_fake_model(
        [
            FakeQueuedMessage(
                id=1,
                task_name='queued.task',
                task_id='queued-1',
                args=[],
                kwargs={},
            ),
        ],
    )
    dead_letter_model = _build_fake_model(
        [
            FakeQueuedMessage(
                id=2,
                task_name='dead.task',
                task_id='dead-1',
                args=[],
                kwargs={},
            ),
        ],
    )
    redactor_tracker = CacheClearTracker()
    contextvars_tracker = ContextVarsTracker()

    monkeypatch.setattr(app_module, '_get_redactor', redactor_tracker)
    monkeypatch.setattr(structlog.contextvars, 'clear_contextvars', contextvars_tracker)
    monkeypatch.setattr(models_module, 'CeleryOutbox', outbox_model)
    monkeypatch.setattr(models_module, 'CeleryOutboxDeadLetter', dead_letter_model)

    generator = fixtures_module.outbox.__wrapped__(transactional_db=object())
    yielded_model = next(generator)

    assert yielded_model is outbox_model
    assert outbox_model.objects.rows == []
    assert dead_letter_model.objects.rows == []
    assert outbox_model.objects.delete_calls == 1
    assert dead_letter_model.objects.delete_calls == 1
    assert redactor_tracker.clear_calls == 1
    assert contextvars_tracker.clear_calls == 1

    outbox_model.objects.rows.append(
        FakeQueuedMessage(
            id=3,
            task_name='later.task',
            task_id='later-1',
            args=[],
            kwargs={},
        ),
    )
    dead_letter_model.objects.rows.append(
        FakeQueuedMessage(
            id=4,
            task_name='later.dead',
            task_id='dead-2',
            args=[],
            kwargs={},
        ),
    )

    with pytest.raises(StopIteration):
        next(generator)

    assert outbox_model.objects.rows == []
    assert dead_letter_model.objects.rows == []
    assert outbox_model.objects.delete_calls == 2
    assert dead_letter_model.objects.delete_calls == 2
    assert redactor_tracker.clear_calls == 2
    assert contextvars_tracker.clear_calls == 2


def test_assert_task_sent_matches_name_args_and_kwargs() -> None:
    first_message = FakeQueuedMessage(
        id=1,
        task_name='demo.task',
        task_id='fixture-task-1',
        args=[1, 2],
        kwargs={'flag': True},
    )
    assert_task_sent, _ = _build_assert_task_sent(
        [
            first_message,
            FakeQueuedMessage(
                id=2,
                task_name='demo.task',
                task_id='fixture-task-2',
                args=[9],
                kwargs={'flag': False},
            ),
        ],
    )

    matched = assert_task_sent(
        'demo.task',
        args=(1, 2),
        kwargs={'flag': True},
    )

    assert matched is first_message


def test_assert_task_sent_treats_ellipsis_as_no_filter() -> None:
    first_message = FakeQueuedMessage(
        id=1,
        task_name='demo.task',
        task_id='fixture-task-1',
        args=[1, 2],
        kwargs={'flag': True},
    )
    second_message = FakeQueuedMessage(
        id=2,
        task_name='demo.task',
        task_id='fixture-task-2',
        args=[9],
        kwargs={'flag': False},
    )
    assert_task_sent, _ = _build_assert_task_sent([first_message, second_message])

    assert assert_task_sent('demo.task', args=..., kwargs={'flag': False}) is second_message
    assert assert_task_sent('demo.task', args=(1, 2), kwargs=...) is first_message


def test_assert_task_sent_reports_missing_task_with_queued_summary() -> None:
    assert_task_sent, _ = _build_assert_task_sent(
        [
            FakeQueuedMessage(
                id=1,
                task_name='queued.task',
                task_id='queued-1',
                args=[1],
                kwargs={'flag': True},
            ),
        ],
    )

    with pytest.raises(AssertionError) as exc_info:
        assert_task_sent('missing.task')

    message = str(exc_info.value)
    assert "Expected queued task 'missing.task', found none." in message
    assert "queued.task(task_id=queued-1, args=[1], kwargs={'flag': True})" in message


def test_assert_task_sent_reports_ambiguous_matches_with_queued_summary() -> None:
    assert_task_sent, _ = _build_assert_task_sent(
        [
            FakeQueuedMessage(
                id=1,
                task_name='duplicate.task',
                task_id='dup-1',
                args=[],
                kwargs={},
            ),
            FakeQueuedMessage(
                id=2,
                task_name='duplicate.task',
                task_id='dup-2',
                args=[],
                kwargs={},
            ),
        ],
    )

    with pytest.raises(AssertionError) as exc_info:
        assert_task_sent('duplicate.task')

    message = str(exc_info.value)
    assert 'multiple queued tasks' in message
    assert 'dup-1' in message
    assert 'dup-2' in message
