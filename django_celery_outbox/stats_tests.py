import json

import pytest


def test_queue_stats_to_dict() -> None:
    from django_celery_outbox.stats import QueueStats

    stats = QueueStats(
        queue_depth=125,
        dlq_count=3,
        oldest_pending_seconds=8130.5,
        top_failing=[
            {'task_name': 'app.tasks.send_email', 'total_retries': 42},
            {'task_name': 'app.tasks.sync_data', 'total_retries': 15},
        ],
    )

    result = stats.to_dict()

    assert result == {
        'queue_depth': 125,
        'dlq_count': 3,
        'oldest_pending_seconds': 8130.5,
        'top_failing': [
            {'task_name': 'app.tasks.send_email', 'total_retries': 42},
            {'task_name': 'app.tasks.sync_data', 'total_retries': 15},
        ],
    }


def test_queue_stats_to_json() -> None:
    from django_celery_outbox.stats import QueueStats

    stats = QueueStats(
        queue_depth=125,
        dlq_count=3,
        oldest_pending_seconds=8130.5,
        top_failing=[{'task_name': 'app.tasks.send_email', 'total_retries': 42}],
    )

    result = stats.to_json()
    parsed = json.loads(result)

    assert parsed['queue_depth'] == 125
    assert parsed['dlq_count'] == 3
    assert parsed['oldest_pending_seconds'] == 8130.5
    assert parsed['top_failing'] == [{'task_name': 'app.tasks.send_email', 'total_retries': 42}]


def test_queue_stats_to_text_with_all_data() -> None:
    from django_celery_outbox.stats import QueueStats

    stats = QueueStats(
        queue_depth=125,
        dlq_count=3,
        oldest_pending_seconds=8130.0,
        top_failing=[
            {'task_name': 'app.tasks.send_email', 'total_retries': 42},
            {'task_name': 'app.tasks.sync_data', 'total_retries': 15},
        ],
    )

    result = stats.to_text()

    assert 'Queue depth:     125' in result
    assert 'DLQ count:       3' in result
    assert 'Oldest pending:  2h 15m 30s' in result
    assert 'Top failing tasks:' in result
    assert '1. app.tasks.send_email (42 retries)' in result
    assert '2. app.tasks.sync_data (15 retries)' in result


def test_queue_stats_to_text_with_no_oldest_pending() -> None:
    from django_celery_outbox.stats import QueueStats

    stats = QueueStats(
        queue_depth=0,
        dlq_count=0,
        oldest_pending_seconds=None,
        top_failing=[],
    )

    result = stats.to_text()

    assert 'Oldest pending:  -' in result
    assert 'Top failing tasks:' not in result


def test_queue_stats_format_duration_hours() -> None:
    from django_celery_outbox.stats import QueueStats

    result = QueueStats._format_duration(3661.0)

    assert result == '1h 1m 1s'


def test_queue_stats_format_duration_minutes() -> None:
    from django_celery_outbox.stats import QueueStats

    result = QueueStats._format_duration(125.0)

    assert result == '2m 5s'


def test_queue_stats_format_duration_seconds_only() -> None:
    from django_celery_outbox.stats import QueueStats

    result = QueueStats._format_duration(45.0)

    assert result == '45s'


@pytest.mark.django_db
def test_get_queue_stats_empty_queue() -> None:
    from django_celery_outbox.stats import get_queue_stats

    result = get_queue_stats()

    assert result.queue_depth == 0
    assert result.dlq_count == 0
    assert result.oldest_pending_seconds is None
    assert result.top_failing == []


@pytest.mark.django_db
def test_get_queue_stats_with_pending_messages() -> None:
    from django_celery_outbox.factories import CeleryOutboxFactory
    from django_celery_outbox.stats import get_queue_stats

    CeleryOutboxFactory.create_batch(5)

    result = get_queue_stats()

    assert result.queue_depth == 5


@pytest.mark.django_db
def test_get_queue_stats_with_dlq() -> None:
    from django_celery_outbox.factories import CeleryOutboxDeadLetterFactory
    from django_celery_outbox.stats import get_queue_stats

    CeleryOutboxDeadLetterFactory.create_batch(3)

    result = get_queue_stats()

    assert result.dlq_count == 3


@pytest.mark.django_db
def test_get_queue_stats_oldest_pending() -> None:
    from datetime import timedelta

    from django.utils import timezone

    from django_celery_outbox.factories import CeleryOutboxFactory
    from django_celery_outbox.models import CeleryOutbox
    from django_celery_outbox.stats import get_queue_stats

    old_message = CeleryOutboxFactory.create()
    CeleryOutbox.objects.filter(pk=old_message.pk).update(created_at=timezone.now() - timedelta(hours=2))
    CeleryOutboxFactory.create()

    result = get_queue_stats()

    assert result.oldest_pending_seconds is not None
    assert result.oldest_pending_seconds >= 7200


@pytest.mark.django_db
def test_get_queue_stats_top_failing() -> None:
    from django_celery_outbox.factories import CeleryOutboxFactory
    from django_celery_outbox.stats import get_queue_stats

    CeleryOutboxFactory.create(task_name='app.tasks.high_fail', retries=10)
    CeleryOutboxFactory.create(task_name='app.tasks.high_fail', retries=5)
    CeleryOutboxFactory.create(task_name='app.tasks.low_fail', retries=2)
    CeleryOutboxFactory.create(task_name='app.tasks.no_fail', retries=0)

    result = get_queue_stats(top_n=10)

    assert len(result.top_failing) == 2
    assert result.top_failing[0]['task_name'] == 'app.tasks.high_fail'
    assert result.top_failing[0]['total_retries'] == 15
    assert result.top_failing[1]['task_name'] == 'app.tasks.low_fail'
    assert result.top_failing[1]['total_retries'] == 2


@pytest.mark.django_db
def test_get_queue_stats_top_n_limits_results() -> None:
    from django_celery_outbox.factories import CeleryOutboxFactory
    from django_celery_outbox.stats import get_queue_stats

    CeleryOutboxFactory.create(task_name='app.tasks.task_a', retries=10)
    CeleryOutboxFactory.create(task_name='app.tasks.task_b', retries=5)
    CeleryOutboxFactory.create(task_name='app.tasks.task_c', retries=2)

    result = get_queue_stats(top_n=2)

    assert len(result.top_failing) == 2


@pytest.mark.django_db
def test_get_queue_stats_top_n_zero_returns_empty_list() -> None:
    from django_celery_outbox.factories import CeleryOutboxFactory
    from django_celery_outbox.stats import get_queue_stats

    CeleryOutboxFactory.create(task_name='app.tasks.task_a', retries=10)

    result = get_queue_stats(top_n=0)

    assert result.top_failing == []
