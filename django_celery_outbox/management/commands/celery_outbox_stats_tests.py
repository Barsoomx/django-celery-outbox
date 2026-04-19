import json
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from django_celery_outbox.factories import CeleryOutboxFactory


@pytest.mark.django_db
def test_command_outputs_text_by_default() -> None:
    CeleryOutboxFactory.create_batch(5)

    out = StringIO()
    call_command('celery_outbox_stats', stdout=out)

    output = out.getvalue()
    assert 'Queue depth:     5' in output
    assert 'DLQ count:' in output


@pytest.mark.django_db
def test_command_outputs_json_when_format_json() -> None:
    CeleryOutboxFactory.create_batch(3)

    out = StringIO()
    call_command('celery_outbox_stats', format='json', stdout=out)

    output = out.getvalue()
    data = json.loads(output)
    assert data['queue_depth'] == 3


@pytest.mark.django_db
def test_command_respects_top_argument() -> None:
    CeleryOutboxFactory.create(task_name='app.tasks.task_a', retries=10)
    CeleryOutboxFactory.create(task_name='app.tasks.task_b', retries=5)
    CeleryOutboxFactory.create(task_name='app.tasks.task_c', retries=2)

    out = StringIO()
    call_command('celery_outbox_stats', format='json', top=2, stdout=out)

    output = out.getvalue()
    data = json.loads(output)
    assert len(data['top_failing']) == 2


@pytest.mark.django_db
def test_stats_command_defaults_top_to_zero() -> None:
    CeleryOutboxFactory.create(task_name='app.tasks.task_a', retries=10)

    out = StringIO()
    call_command('celery_outbox_stats', format='json', stdout=out)

    parsed = json.loads(out.getvalue())
    assert parsed['top_failing'] == []


@pytest.mark.django_db
@override_settings(CELERY_OUTBOX_STALE_TIMEOUT_SECONDS=900)
def test_command_uses_configured_stale_timeout_by_default() -> None:
    CeleryOutboxFactory.create(
        task_name='app.tasks.inflight',
        updated_at=timezone.now() - timedelta(minutes=10),
        retry_after=None,
    )

    out = StringIO()
    call_command('celery_outbox_stats', format='json', stdout=out)

    parsed = json.loads(out.getvalue())
    assert parsed['queue_depth'] == 0


def test_command_rejects_non_positive_stale_timeout() -> None:
    out = StringIO()

    with pytest.raises(CommandError, match='stale-timeout-seconds must be > 0'):
        call_command('celery_outbox_stats', stale_timeout_seconds=0, stdout=out)
