# Relay Tuning

## Batch Size

Controls how many messages are processed per database round-trip.

| Scenario | Recommended | Rationale |
|----------|-------------|-----------|
| Low volume (<100/min) | 10-50 | Lower latency |
| Medium volume | 100-200 | Balance |
| High volume (>1000/min) | 500-1000 | Throughput |

```bash
--batch-size 500
```

## Idle Time

How long to sleep when the queue is empty.

| Scenario | Recommended | Rationale |
|----------|-------------|-----------|
| Real-time required | 0.1-0.5 | Sub-second latency |
| Standard | 1.0-2.0 | Balance |
| Background jobs | 5.0-10.0 | Reduce DB load |

```bash
--idle-time 1.0
```

## Backoff Time

Base seconds for exponential backoff on ordinary publish failures.

Formula: `delay = min(backoff_time * 2^retries + jitter, max_backoff)`

With the defaults, `backoff_time=120`, jitter is up to 10% of `backoff_time`, and
`max_backoff=3600.0`.

| Retries | Delay range (120s base) |
|---------|--------------------------|
| 0 | 120-132s |
| 1 | 240-252s |
| 2 | 480-492s |
| 3 | 960-972s |
| 4 | 1920-1932s |

```bash
--backoff-time 120
--max-backoff 3600.0
```

If you raise `--max-retries` above the default, later failures still cap at `--max-backoff`
instead of growing without bound.

## Max Retries

After this many failures, the message moves to dead letter.

```bash
--max-retries 5
```

## Broker Outage Cooldown

`--broker-outage-cooldown` is separate from retry backoff.

- It applies only when the relay classifies the failure as a broker outage.
- The relay defers the already-selected rows for the cooldown window.
- It does not increment `retries`.
- It does not consume retry budget from `--max-retries`.
- The breaker is process-local, so each relay process tracks its own cooldown.

```bash
--broker-outage-cooldown 30.0
```

## Stale Timeout

`--stale-timeout-seconds` controls when rows stamped as in-flight become reclaimable again.
The default is `300` seconds.

This is recovery logic, not normal retry logic:

- It is used for rows that were selected but never completed because a relay crashed or was interrupted.
- It is how selected-but-not-yet-started rows become visible again after shutdown deadline aborts.
- It does not change `retries` on its own.

```bash
--stale-timeout-seconds 300
```

## Send Timeout and Shutdown Timeout

`--send-timeout` bounds a single `Celery.send_task()` publish attempt. `--shutdown-timeout`
controls how long the relay may keep starting additional sends after `SIGTERM` or `SIGINT`.

Pick `--shutdown-timeout` to cover a healthy drain window, and size `--send-timeout` to the
slowest broker publish you still consider healthy.

## Publish Concurrency

`--publish-concurrency` enables a bounded parallel publish mode. The default is `1`, which keeps
the serial relay path and remains the recommended baseline.

Treat higher values as advanced tuning:

- Start with `1`.
- Increase gradually only after verifying behavior against the supported live RabbitMQ smoke lane.
- Remember that only broker publish I/O runs in worker threads. Result classification, signals,
  metrics, and database mutation still happen on the main relay thread.

```bash
--publish-concurrency 2
```

## Queue Snapshot Refresh Cadence

`--queue-snapshot-refresh-seconds` controls how often the relay refreshes queue-wide snapshot data
used by:

- `queue.depth`
- `dead_letter.count`
- `oldest_pending_age_seconds`
- `celery_outbox_batch_processed` summary fields

These values are sampled queue-wide gauges, not exact per-batch recomputations. The default is
`5.0` seconds, which keeps hot-path DB work bounded while still updating dashboards and logs
frequently enough for normal operations.

```bash
--queue-snapshot-refresh-seconds 5.0
```

## Planner Behavior

The shipped selector and dead-letter purge shapes were verified against large synthetic PostgreSQL
15 and MySQL 8 tables during release hardening.

Observed planner behavior:

- Sparse active outbox on PostgreSQL used a `BitmapOr` over `celery_outbox_pending_idx`,
  `celery_outbox_retry_idx`, and `celery_outbox_stale_idx`.
- Sparse active outbox on MySQL used `index_merge` over the retry/stale selector indexes.
- Dead-letter destructive chunks now order by the active retention field (`dead_at, pk` or
  `created_at, pk`), which lets both PostgreSQL and MySQL use the matching retention index on the
  chunk-selection path.

When almost every row matches the filter, planners may still prefer the primary key or a sequential
scan for `ORDER BY ... LIMIT ...`. That is expected for dense-match tables and does not invalidate
the sparse-backlog fast path the package is optimized for.

## Monitoring Metrics

The relay emits these StatsD metrics:

| Metric | Type | Tags | Description |
|--------|------|------|-------------|
| `queue.depth` | gauge | | Sampled live backlog gauge refreshed at most once per `--queue-snapshot-refresh-seconds` window |
| `dead_letter.count` | gauge | | Sampled dead-letter backlog gauge refreshed at most once per `--queue-snapshot-refresh-seconds` window |
| `oldest_pending_age_seconds` | gauge | | Sampled age of the oldest live-backlog row |
| `batch.duration_ms` | timing | | Batch processing time |
| `send_latency_ms` | timing | `task_name` | Time from enqueue to publish |
| `messages.published` | counter | `task_name` | Successfully sent |
| `messages.failed` | counter | `task_name`, `exception_type` | Failed (will retry) |
| `messages.exceeded` | counter | `task_name`, `exception_type` | Moved to dead letter |
