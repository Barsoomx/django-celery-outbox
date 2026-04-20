from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from django_celery_outbox.factories import CeleryOutboxDeadLetterFactory
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter


@pytest.mark.django_db
def test_replay_command_replays_selected_ids_only() -> None:
    dead1 = CeleryOutboxDeadLetterFactory.create(task_id='cmd-replay-1')
    dead2 = CeleryOutboxDeadLetterFactory.create(task_id='cmd-replay-2')

    out = StringIO()
    call_command('celery_outbox_replay_dead_letter', str(dead1.pk), stdout=out)

    assert CeleryOutbox.objects.filter(task_id='cmd-replay-1').exists()
    assert not CeleryOutbox.objects.filter(task_id='cmd-replay-2').exists()
    assert CeleryOutboxDeadLetter.objects.filter(pk=dead2.pk).exists()
    assert 'Replayed 1 dead letter record(s).' in out.getvalue()


@pytest.mark.django_db
def test_replay_command_limit_caps_replayed_rows() -> None:
    dead1 = CeleryOutboxDeadLetterFactory.create(task_id='cmd-limit-1')
    dead2 = CeleryOutboxDeadLetterFactory.create(task_id='cmd-limit-2')

    out = StringIO()
    call_command(
        'celery_outbox_replay_dead_letter',
        str(dead1.pk),
        str(dead2.pk),
        limit=1,
        stdout=out,
    )

    assert CeleryOutbox.objects.filter(task_id='cmd-limit-1').exists()
    assert not CeleryOutbox.objects.filter(task_id='cmd-limit-2').exists()
    assert CeleryOutboxDeadLetter.objects.filter(pk=dead2.pk).exists()
    assert 'Replayed 1 dead letter record(s).' in out.getvalue()


def test_replay_command_rejects_zero_limit() -> None:
    with pytest.raises(CommandError, match='--limit must be greater than 0'):
        call_command('celery_outbox_replay_dead_letter', '1', limit=0)


def test_replay_command_rejects_negative_limit() -> None:
    with pytest.raises(CommandError, match='--limit must be greater than 0'):
        call_command('celery_outbox_replay_dead_letter', '1', limit=-1)
