# Sampled queue-gauge handoff

- `queue.depth`, `dead_letter.count`, and `oldest_pending_age_seconds` are sampled queue-wide gauges, not exact per-batch snapshots.
- `celery_outbox_stats queue_depth` now matches relay live-backlog semantics.
- `celery_outbox_stats --top` defaults to `0`; `GROUP BY task_name` is now opt-in.
