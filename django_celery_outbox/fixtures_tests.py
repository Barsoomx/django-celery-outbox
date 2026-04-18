from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest
import structlog.contextvars
from django.db import transaction

from django_celery_outbox import fixtures as fixtures_module
from django_celery_outbox.app import OutboxCelery


def test_outbox_fixture_starts_empty(outbox: Any) -> None:
    assert outbox.objects.count() == 0


def test_assert_task_sent_matches_name_args_and_kwargs(
    assert_task_sent: fixtures_module.AssertTaskSent,
) -> None:
    app = OutboxCelery('fixture-tests')

    with transaction.atomic():
        app.send_task(
            'demo.task',
            args=(1, 2),
            kwargs={'flag': True},
            task_id='fixture-task-1',
        )

    message = assert_task_sent(
        'demo.task',
        args=(1, 2),
        kwargs={'flag': True},
    )

    assert message.task_id == 'fixture-task-1'


def test_assert_task_sent_reports_missing_task(
    assert_task_sent: fixtures_module.AssertTaskSent,
) -> None:
    with pytest.raises(AssertionError, match="Expected queued task 'missing.task'"):
        assert_task_sent('missing.task')


def test_assert_task_sent_reports_ambiguous_matches(
    assert_task_sent: fixtures_module.AssertTaskSent,
) -> None:
    app = OutboxCelery('fixture-tests')

    with transaction.atomic():
        app.send_task('duplicate.task', task_id='dup-1')
        app.send_task('duplicate.task', task_id='dup-2')

    with pytest.raises(AssertionError, match='multiple queued tasks'):
        assert_task_sent('duplicate.task')


@dataclass(slots=True)
class FakeQueuedMessage:
    id: int
    task_name: str
    task_id: str
    args: list[Any]
    kwargs: dict[str, Any]
    redacted_args: list[Any] | None = None
    redacted_kwargs: dict[str, Any] | None = None

    @property
    def inspection_args(self) -> list[Any]:
        return self.redacted_args if self.redacted_args is not None else self.args

    @property
    def inspection_kwargs(self) -> dict[str, Any]:
        return self.redacted_kwargs if self.redacted_kwargs is not None else self.kwargs


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


class BlockerContextTracker:
    def __init__(self, blocker: DjangoDbBlockerTracker) -> None:
        self._blocker = blocker

    def __enter__(self) -> None:
        self._blocker.enter_calls += 1

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb
        self._blocker.exit_calls += 1


class DjangoDbBlockerTracker:
    def __init__(self) -> None:
        self.enter_calls = 0
        self.exit_calls = 0

    def unblock(self) -> BlockerContextTracker:
        return BlockerContextTracker(self)


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
    assert_task_sent_fixture = cast(Any, fixtures_module.assert_task_sent_fixture)
    assert_task_sent = assert_task_sent_fixture.__wrapped__(outbox=outbox_model)
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
    blocker_tracker = DjangoDbBlockerTracker()

    monkeypatch.setattr(app_module, '_get_redactor', redactor_tracker)
    monkeypatch.setattr(structlog.contextvars, 'clear_contextvars', contextvars_tracker)
    monkeypatch.setattr(models_module, 'CeleryOutbox', outbox_model)
    monkeypatch.setattr(models_module, 'CeleryOutboxDeadLetter', dead_letter_model)

    outbox_fixture = cast(Any, fixtures_module.outbox)
    generator = outbox_fixture.__wrapped__(
        transactional_db=object(),
        django_db_blocker=blocker_tracker,
    )
    yielded_model = next(generator)

    assert yielded_model is outbox_model
    assert outbox_model.objects.rows == []
    assert dead_letter_model.objects.rows == []
    assert outbox_model.objects.delete_calls == 1
    assert dead_letter_model.objects.delete_calls == 1
    assert redactor_tracker.clear_calls == 1
    assert contextvars_tracker.clear_calls == 1
    assert blocker_tracker.enter_calls == 1
    assert blocker_tracker.exit_calls == 0

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
    assert blocker_tracker.enter_calls == 1
    assert blocker_tracker.exit_calls == 1


def test_assert_task_sent_matches_name_args_and_kwargs_with_fake_model() -> None:
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


def test_assert_task_sent_reports_missing_task_with_queued_summary_with_fake_model() -> None:
    assert_task_sent, _ = _build_assert_task_sent(
        [
            FakeQueuedMessage(
                id=1,
                task_name='queued.task',
                task_id='queued-1',
                args=[1],
                kwargs={'email': 'user@example.com'},
                redacted_args=['<redacted>'],
                redacted_kwargs={'email': '<redacted>'},
            ),
        ],
    )

    with pytest.raises(AssertionError) as exc_info:
        assert_task_sent('missing.task')

    message = str(exc_info.value)
    assert "Expected queued task 'missing.task', found none." in message
    assert "queued.task(task_id=queued-1, args=['<redacted>'], kwargs={'email': '<redacted>'})" in message
    assert 'user@example.com' not in message


def test_assert_task_sent_reports_ambiguous_matches_with_queued_summary_with_fake_model() -> None:
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
