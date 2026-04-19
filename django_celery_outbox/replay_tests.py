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
