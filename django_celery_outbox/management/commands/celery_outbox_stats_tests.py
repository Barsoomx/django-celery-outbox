import json
from io import StringIO

import pytest
from django.core.management import call_command

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
