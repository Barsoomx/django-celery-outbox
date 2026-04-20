from unittest.mock import patch

from django_celery_outbox.relay._relay import QueueSnapshotSampler
from django_celery_outbox.stats import QueueStats


def test_queue_snapshot_sampler_fetches_snapshot_on_first_get() -> None:
    sampler = QueueSnapshotSampler(refresh_interval_seconds=5.0)
    snapshot = QueueStats(
        queue_depth=3,
        dlq_count=1,
        oldest_pending_seconds=42.0,
        top_failing=[],
    )

    with patch('django_celery_outbox.relay._relay.get_queue_stats', return_value=snapshot) as m_stats:
        result = sampler.get(now_monotonic=10.0)

    assert result == snapshot
    m_stats.assert_called_once_with(top_n=0, stale_timeout=None)


def test_queue_snapshot_sampler_reuses_cached_snapshot_before_refresh_interval() -> None:
    sampler = QueueSnapshotSampler(refresh_interval_seconds=5.0)
    first = QueueStats(
        queue_depth=1,
        dlq_count=0,
        oldest_pending_seconds=None,
        top_failing=[],
    )
    second = QueueStats(
        queue_depth=2,
        dlq_count=1,
        oldest_pending_seconds=30.0,
        top_failing=[],
    )

    with patch('django_celery_outbox.relay._relay.get_queue_stats', side_effect=[first, second]) as m_stats:
        initial = sampler.get(now_monotonic=10.0)
        cached = sampler.get(now_monotonic=14.9)

    assert initial == first
    assert cached == first
    m_stats.assert_called_once_with(top_n=0, stale_timeout=None)


def test_queue_snapshot_sampler_refreshes_after_interval() -> None:
    sampler = QueueSnapshotSampler(refresh_interval_seconds=5.0)
    first = QueueStats(
        queue_depth=1,
        dlq_count=0,
        oldest_pending_seconds=None,
        top_failing=[],
    )
    second = QueueStats(
        queue_depth=4,
        dlq_count=2,
        oldest_pending_seconds=15.0,
        top_failing=[],
    )

    with patch('django_celery_outbox.relay._relay.get_queue_stats', side_effect=[first, second]) as m_stats:
        sampler.get(now_monotonic=10.0)
        refreshed = sampler.get(now_monotonic=15.0)

    assert refreshed == second
    assert m_stats.call_count == 2
