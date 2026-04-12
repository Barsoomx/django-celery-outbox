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

Base seconds for exponential backoff on failed messages.

Formula: `delay = backoff_time * 2^retries + jitter`

| Retries | Delay (5s base) |
|---------|-----------------|
| 0 | 5s |
| 1 | 10s |
| 2 | 20s |
| 3 | 40s |
| 4 | 80s |

```bash
--backoff-time 5.0
```

## Max Retries

After this many failures, the message moves to dead letter.

```bash
--max-retries 5
```

## Monitoring Metrics

The relay emits these StatsD metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `queue.depth` | gauge | Messages waiting |
| `dead_letter.count` | gauge | Dead letter entries |
| `batch.duration_ms` | timing | Batch processing time |
| `messages.published` | counter | Successfully sent |
| `messages.failed` | counter | Failed (will retry) |
| `messages.exceeded` | counter | Moved to dead letter |
