from unittest.mock import MagicMock, patch

import pytest

from django_celery_outbox.factories import CeleryOutboxDeadLetterFactory
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter
from django_celery_outbox.replay import replay_dead_letters


@pytest.mark.django_db
def test_replay_dead_letters_preserves_payload_and_schema_version() -> None:
    dead = CeleryOutboxDeadLetterFactory.create(
        task_id='replay-1',
        task_name='app.tasks.replay',
        args=[1, 2],
        kwargs={'key': 'value'},
        redacted_args=['[REDACTED]', 2],
        redacted_kwargs={'key': '[REDACTED]'},
        options={'queue': 'critical'},
        schema_version=2,
        sentry_trace_id='trace-1',
        sentry_baggage='baggage-1',
        structlog_context='{"request_id": "req-1"}',
    )

    count = replay_dead_letters([dead.pk])

    assert count == 1
    outbox = CeleryOutbox.objects.get(task_id='replay-1')
    assert outbox.args == [1, 2]
    assert outbox.kwargs == {'key': 'value'}
    assert outbox.redacted_args == ['[REDACTED]', 2]
    assert outbox.redacted_kwargs == {'key': '[REDACTED]'}
    assert outbox.options == {'queue': 'critical'}
    assert outbox.schema_version == 2
    assert outbox.sentry_trace_id == 'trace-1'
    assert outbox.sentry_baggage == 'baggage-1'
    assert outbox.structlog_context == '{"request_id": "req-1"}'
    assert not CeleryOutboxDeadLetter.objects.filter(pk=dead.pk).exists()


@pytest.mark.django_db
def test_replay_dead_letters_limit_replays_only_requested_slice() -> None:
    dead1 = CeleryOutboxDeadLetterFactory.create(task_id='replay-limit-1')
    dead2 = CeleryOutboxDeadLetterFactory.create(task_id='replay-limit-2')
    dead3 = CeleryOutboxDeadLetterFactory.create(task_id='replay-limit-3')

    count = replay_dead_letters([dead1.pk, dead2.pk, dead3.pk], limit=2)

    assert count == 2
    assert CeleryOutbox.objects.filter(task_id='replay-limit-1').exists()
    assert CeleryOutbox.objects.filter(task_id='replay-limit-2').exists()
    assert not CeleryOutbox.objects.filter(task_id='replay-limit-3').exists()
    assert not CeleryOutboxDeadLetter.objects.filter(pk=dead1.pk).exists()
    assert not CeleryOutboxDeadLetter.objects.filter(pk=dead2.pk).exists()
    assert CeleryOutboxDeadLetter.objects.filter(pk=dead3.pk).exists()


def test_replay_dead_letters_uses_outbox_alias_for_read_write_and_delete() -> None:
    row = MagicMock(
        pk=11,
        task_id='replay-alias-1',
        task_name='app.tasks.replay_alias',
        args=[1],
        kwargs={'k': 'v'},
        redacted_args=None,
        redacted_kwargs=None,
        options={'queue': 'critical'},
        schema_version=2,
        sentry_trace_id='trace-1',
        sentry_baggage='baggage-1',
        structlog_context='{"request_id": "req-1"}',
    )
    read_queryset = MagicMock()
    read_queryset.order_by.return_value = read_queryset
    read_queryset.__iter__.return_value = iter([row])
    delete_queryset = MagicMock()
    read_locking_manager = MagicMock()
    read_locking_manager.filter.return_value = read_queryset
    read_using_manager = MagicMock()
    read_using_manager.select_for_update.return_value = read_locking_manager
    delete_using_manager = MagicMock()
    delete_using_manager.filter.return_value = delete_queryset

    with (
        patch('django_celery_outbox.replay.get_outbox_db_alias', return_value='outbox') as m_alias,
        patch(
            'django_celery_outbox.replay.CeleryOutboxDeadLetter.objects.using',
            side_effect=[read_using_manager, delete_using_manager],
        ) as m_dead_using,
        patch('django_celery_outbox.replay.CeleryOutbox.objects.using') as m_outbox_using,
        patch('django_celery_outbox.replay.transaction.atomic') as m_atomic,
    ):
        replayed = replay_dead_letters([row.pk])

    assert replayed == 1
    m_alias.assert_called_once_with()
    assert m_dead_using.call_count == 2
    read_using_manager.select_for_update.assert_called_once_with()
    read_locking_manager.filter.assert_called_once_with(pk__in=[row.pk])
    delete_using_manager.filter.assert_called_once_with(pk__in=[row.pk])
    m_atomic.assert_called_once_with(using='outbox')
    m_outbox_using.assert_called_once_with('outbox')
    m_outbox_using.return_value.bulk_create.assert_called_once()
    delete_queryset.delete.assert_called_once_with()
