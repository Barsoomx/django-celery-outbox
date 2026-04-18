from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter
from django_celery_outbox.relay._mutations import RelayMutations


@pytest.mark.django_db
def test_update_failed_increments_retries_and_sets_retry_after() -> None:
    mutations = RelayMutations(backoff_time=120)
    before = timezone.now()
    msg = CeleryOutbox.objects.create(
        task_id='task-1',
        task_name='some.task',
        retries=1,
        updated_at=None,
    )

    with patch('django_celery_outbox.relay._mutations.random.uniform', return_value=0):
        mutations.update_failed([(msg.id, 1)])

    msg.refresh_from_db()
    assert msg.retries == 2
    assert msg.updated_at is not None
    assert msg.retry_after is not None
    assert msg.retry_after >= before + timedelta(seconds=239)


def test_update_failed_groups_ids_by_retry_count() -> None:
    mutations = RelayMutations(backoff_time=120)

    with patch('django_celery_outbox.relay._mutations.CeleryOutbox.objects.filter') as m_filter:
        m_queryset = MagicMock()
        m_filter.return_value = m_queryset

        with patch('django_celery_outbox.relay._mutations.random.uniform', return_value=0):
            mutations.update_failed([(1, 0), (2, 0), (3, 2)])

    assert m_filter.call_count == 2
    m_filter.assert_any_call(pk__in=[1, 2])
    m_filter.assert_any_call(pk__in=[3])
    assert m_queryset.update.call_count == 2


@pytest.mark.django_db
def test_delete_published_removes_only_requested_rows() -> None:
    mutations = RelayMutations(backoff_time=120)
    msg1 = CeleryOutbox.objects.create(task_id='task-1', task_name='some.task')
    msg2 = CeleryOutbox.objects.create(task_id='task-2', task_name='some.task')

    mutations.delete_published([msg1.id])

    assert not CeleryOutbox.objects.filter(pk=msg1.id).exists()
    assert CeleryOutbox.objects.filter(pk=msg2.id).exists()


@pytest.mark.django_db
def test_delete_published_noops_for_empty_list() -> None:
    mutations = RelayMutations(backoff_time=120)
    msg = CeleryOutbox.objects.create(task_id='task-1', task_name='some.task')

    mutations.delete_published([])

    assert CeleryOutbox.objects.filter(pk=msg.id).exists()


@pytest.mark.django_db
def test_move_exceeded_to_dead_letter_preserves_message_fields() -> None:
    mutations = RelayMutations(backoff_time=120)
    msg = CeleryOutbox.objects.create(
        task_id='task-dead',
        task_name='some.task',
        args=[1],
        kwargs={'a': 1},
        redacted_args=['x'],
        redacted_kwargs={'a': 'x'},
        options={'priority': 9},
        retries=5,
        schema_version=2,
        sentry_trace_id='trace',
        sentry_baggage='baggage',
        structlog_context='{"request_id": "req-1"}',
    )

    mutations.move_exceeded_to_dead_letter([msg])

    dead = CeleryOutboxDeadLetter.objects.get(task_id='task-dead')
    assert dead.task_name == 'some.task'
    assert dead.args == [1]
    assert dead.kwargs == {'a': 1}
    assert dead.redacted_args == ['x']
    assert dead.redacted_kwargs == {'a': 'x'}
    assert dead.options == {'priority': 9}
    assert dead.schema_version == 2
    assert dead.failure_reason == 'max retries exceeded'
    assert not CeleryOutbox.objects.filter(pk=msg.id).exists()


@pytest.mark.django_db
def test_move_exceeded_to_dead_letter_noops_for_empty_list() -> None:
    mutations = RelayMutations(backoff_time=120)

    mutations.move_exceeded_to_dead_letter([])

    assert CeleryOutboxDeadLetter.objects.count() == 0
