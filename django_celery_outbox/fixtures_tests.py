from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
import structlog.contextvars
from celery import Celery
from celery.result import AsyncResult
from django.db import connections, transaction

from django_celery_outbox import fixtures as fixtures_module
from django_celery_outbox.app import OutboxCelery
from django_celery_outbox.fixtures import (
    AssertTaskSent,
    DrainOutbox,
    FakeRelayRecorder,
    RecordedRelayCall,
)
from django_celery_outbox.models import CeleryOutbox


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


def _enable_relay_for_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = connections[CeleryOutbox.objects.db]
    monkeypatch.setattr(connection.features, 'has_select_for_update_skip_locked', True, raising=False)


def test_fake_relay_records_publish_and_drain_outbox(
    fake_relay: FakeRelayRecorder,
    assert_task_sent: AssertTaskSent,
    drain_outbox: DrainOutbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)

    app = OutboxCelery('fixture-tests')

    with transaction.atomic():
        app.send_task(
            'relay.task',
            args=(1,),
            kwargs={'flag': True},
            task_id='relay-task-1',
        )

    message = assert_task_sent('relay.task', args=(1,), kwargs={'flag': True})

    drain_outbox()

    assert CeleryOutbox.objects.count() == 0
    assert len(fake_relay.calls) == 1
    assert fake_relay.calls[0].task_id == message.task_id
    assert fake_relay.calls[0].name == 'relay.task'
    assert fake_relay.calls[0].args == [1]
    assert fake_relay.calls[0].kwargs == {'flag': True}


def test_drain_outbox_processes_multiple_batches(
    fake_relay: FakeRelayRecorder,
    drain_outbox: DrainOutbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)

    app = OutboxCelery('fixture-tests')

    with transaction.atomic():
        for i in range(101):
            app.send_task('batch.task', task_id=f'batch-{i}')

    drain_outbox()

    assert CeleryOutbox.objects.count() == 0
    assert len(fake_relay.calls) == 101


def test_drain_outbox_raises_on_broker_failures(
    drain_outbox: DrainOutbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)

    app = OutboxCelery('fixture-tests')

    with transaction.atomic():
        app.send_task('failing.task', task_id='failing-task-1')

    with patch(
        'django_celery_outbox.relay._publisher.Celery.send_task',
        side_effect=RuntimeError('broker down'),
    ):
        with pytest.raises(AssertionError, match='could not fully drain the queue'):
            drain_outbox()

    message = CeleryOutbox.objects.get(task_id='failing-task-1')
    assert message.retries == 1
    assert message.retry_after is not None


def test_drain_outbox_fails_on_timeout_outage_deferral(
    drain_outbox: DrainOutbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)

    app = OutboxCelery('fixture-tests')

    with transaction.atomic():
        app.send_task('timeout.task', task_id='timeout-task-1')

    with patch(
        'django_celery_outbox.relay._publisher.Celery.send_task',
        side_effect=TimeoutError('timed out'),
    ):
        with pytest.raises(AssertionError, match='could not fully drain the queue'):
            drain_outbox()

    message = CeleryOutbox.objects.get(task_id='timeout-task-1')
    assert message.retries == 0
    assert message.retry_after is not None


def test_fixture_types_are_importable() -> None:
    assert AssertTaskSent is not None
    assert DrainOutbox is not None
    assert FakeRelayRecorder is not None
    assert RecordedRelayCall is not None


def test_fixture_support_exports_semver_stable_boundary() -> None:
    import django_celery_outbox._fixture_support as fixture_support_module

    assert fixture_support_module.__all__ == [
        'FakeRelayRecorder',
        'RecordedRelayCall',
        'load_fixture_celery_app',
        'patch_fake_relay_send_task',
        'reset_fixture_state',
        'run_drain_outbox_once',
    ]


def test_reset_fixture_state_clears_models_redactor_cache_and_contextvars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import django_celery_outbox._fixture_support as fixture_support_module
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

    fixture_support_module.reset_fixture_state()

    assert outbox_model.objects.rows == []
    assert dead_letter_model.objects.rows == []
    assert outbox_model.objects.delete_calls == 1
    assert dead_letter_model.objects.delete_calls == 1
    assert redactor_tracker.clear_calls == 1
    assert contextvars_tracker.clear_calls == 1


def test_fake_relay_uses_fixture_support_patch_target(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[FakeRelayRecorder] = []

    class _PatchContext:
        def __enter__(self) -> None:
            return None

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            del exc_type, exc, tb

    def fake_patch_fake_relay_send_task(recorder: FakeRelayRecorder) -> _PatchContext:
        called.append(recorder)
        return _PatchContext()

    monkeypatch.setattr(
        fixtures_module,
        'patch_fake_relay_send_task',
        fake_patch_fake_relay_send_task,
        raising=False,
    )

    generator = cast(Any, fixtures_module.fake_relay).__wrapped__()
    recorder = next(generator)

    assert called == [recorder]

    with pytest.raises(StopIteration):
        next(generator)


@pytest.mark.django_db
def test_drain_outbox_uses_fixture_support_run_once(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[tuple[object, float]] = []

    def fake_run_drain_outbox_once(app: object, *, idle_time: float = 0.0) -> None:
        called.append((app, idle_time))

    monkeypatch.setattr(
        fixtures_module,
        'run_drain_outbox_once',
        fake_run_drain_outbox_once,
        raising=False,
    )

    drain_outbox = cast(Any, fixtures_module.drain_outbox_fixture).__wrapped__(outbox=CeleryOutbox)

    with patch.object(CeleryOutbox.objects, 'count', side_effect=[1, 0]):
        drain_outbox()

    assert len(called) == 1


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


def test_outbox_fixture_uses_fixture_support_reset_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import django_celery_outbox.models as models_module

    outbox_model = _build_fake_model([])
    dead_letter_model = _build_fake_model([])
    blocker_tracker = DjangoDbBlockerTracker()
    reset_calls: list[None] = []

    def fake_reset_fixture_state() -> None:
        reset_calls.append(None)

    monkeypatch.setattr(models_module, 'CeleryOutbox', outbox_model)
    monkeypatch.setattr(models_module, 'CeleryOutboxDeadLetter', dead_letter_model)
    monkeypatch.setattr(fixtures_module, 'reset_fixture_state', fake_reset_fixture_state, raising=False)

    outbox_fixture = cast(Any, fixtures_module.outbox)
    generator = outbox_fixture.__wrapped__(
        transactional_db=object(),
        django_db_blocker=blocker_tracker,
    )
    yielded_model = next(generator)

    assert yielded_model is outbox_model
    assert reset_calls == [None]
    assert blocker_tracker.enter_calls == 1
    assert blocker_tracker.exit_calls == 0

    with pytest.raises(StopIteration):
        next(generator)

    assert reset_calls == [None, None]
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


def test_assert_task_sent_treats_ellipsis_as_omitted_with_fake_model() -> None:
    message = FakeQueuedMessage(
        id=1,
        task_name='ellipsis.task',
        task_id='ellipsis-1',
        args=[1],
        kwargs={'flag': True},
    )
    assert_task_sent, _ = _build_assert_task_sent([message])

    matched = assert_task_sent(
        'ellipsis.task',
        args=...,
        kwargs=...,
    )

    assert matched is message


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


def test_fake_relay_delegates_non_relay_celery_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import django_celery_outbox._settings as settings_module
    import django_celery_outbox.relay._publisher as publisher_module

    relay_app = Celery('relay-app')
    other_app = Celery('other-app')
    delegated_result = MagicMock(spec=AsyncResult)
    delegated_calls: list[tuple[Celery, dict[str, Any]]] = []

    def fake_original_send_task(app: Celery, **kwargs: Any) -> AsyncResult:
        delegated_calls.append((app, kwargs))
        return delegated_result

    monkeypatch.setattr(settings_module, 'load_celery_app_setting', lambda: relay_app)
    monkeypatch.setattr(publisher_module.Celery, 'send_task', fake_original_send_task)

    fake_relay_fixture = cast(Any, fixtures_module.fake_relay)
    generator = fake_relay_fixture.__wrapped__()
    recorder = next(generator)

    relay_result = publisher_module.Celery.send_task(
        relay_app,
        name='relay.task',
        args=[1],
        kwargs={'flag': True},
        task_id='relay-1',
    )
    direct_result = publisher_module.Celery.send_task(
        other_app,
        name='direct.task',
        task_id='direct-1',
    )

    with pytest.raises(StopIteration):
        next(generator)

    assert relay_result is None
    assert len(recorder.calls) == 1
    assert recorder.calls[0].name == 'relay.task'
    assert recorder.calls[0].task_id == 'relay-1'

    assert direct_result is delegated_result
    assert delegated_calls == [
        (
            other_app,
            {
                'name': 'direct.task',
                'args': None,
                'kwargs': None,
                'task_id': 'direct-1',
            },
        )
    ]


def test_fake_relay_records_relay_celery_sends_with_positional_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import django_celery_outbox._settings as settings_module
    import django_celery_outbox.relay._publisher as publisher_module

    relay_app = Celery('relay-app')
    delegated_calls: list[tuple[Celery, dict[str, Any]]] = []

    def fake_original_send_task(app: Celery, **kwargs: Any) -> AsyncResult:
        delegated_calls.append((app, kwargs))
        return MagicMock(spec=AsyncResult)

    monkeypatch.setattr(settings_module, 'load_celery_app_setting', lambda: relay_app)
    monkeypatch.setattr(publisher_module.Celery, 'send_task', fake_original_send_task)

    fake_relay_fixture = cast(Any, fixtures_module.fake_relay)
    generator = fake_relay_fixture.__wrapped__()
    recorder = next(generator)

    result = publisher_module.Celery.send_task(
        relay_app,
        'relay.task',
        [1],
        {'flag': True},
        task_id='relay-1',
        headers={'trace': 'abc'},
        countdown=5,
    )

    with pytest.raises(StopIteration):
        next(generator)

    assert result is None
    assert delegated_calls == []
    assert recorder.calls == [
        RecordedRelayCall(
            name='relay.task',
            args=[1],
            kwargs={'flag': True},
            task_id='relay-1',
            headers={'trace': 'abc'},
            options={'countdown': 5},
        )
    ]


def test_fake_relay_delegates_non_relay_celery_sends_with_positional_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import django_celery_outbox._settings as settings_module
    import django_celery_outbox.relay._publisher as publisher_module

    relay_app = Celery('relay-app')
    other_app = Celery('other-app')
    delegated_result = MagicMock(spec=AsyncResult)
    delegated_calls: list[tuple[Celery, dict[str, Any]]] = []

    def fake_original_send_task(app: Celery, **kwargs: Any) -> AsyncResult:
        delegated_calls.append((app, kwargs))
        return delegated_result

    monkeypatch.setattr(settings_module, 'load_celery_app_setting', lambda: relay_app)
    monkeypatch.setattr(publisher_module.Celery, 'send_task', fake_original_send_task)

    fake_relay_fixture = cast(Any, fixtures_module.fake_relay)
    generator = fake_relay_fixture.__wrapped__()
    recorder = next(generator)

    direct_result = publisher_module.Celery.send_task(
        other_app,
        'direct.task',
        [1],
        {'flag': True},
        task_id='direct-1',
        headers={'trace': 'abc'},
        countdown=7,
    )

    with pytest.raises(StopIteration):
        next(generator)

    assert direct_result is delegated_result
    assert recorder.calls == []
    assert delegated_calls == [
        (
            other_app,
            {
                'name': 'direct.task',
                'args': [1],
                'kwargs': {'flag': True},
                'task_id': 'direct-1',
                'headers': {'trace': 'abc'},
                'countdown': 7,
            },
        )
    ]
