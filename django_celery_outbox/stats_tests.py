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
