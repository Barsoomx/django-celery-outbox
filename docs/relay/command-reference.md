# Command Reference

## celery_outbox_relay

Main relay daemon command.

```bash
python manage.py celery_outbox_relay [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--batch-size` | int | 100 | Maximum messages per batch |
| `--idle-time` | float | 1.0 | Seconds to sleep when queue empty |
| `--backoff-time` | int | 120 | Base seconds for exponential backoff |
| `--max-retries` | int | 5 | Retries before dead letter |
| `--stale-timeout-seconds` | int | `CELERY_OUTBOX_STALE_TIMEOUT_SECONDS` or 300 | Seconds before in-flight rows are considered stale |
| `--send-timeout` | float | 10.0 | Timeout passed to broker publish |
| `--shutdown-timeout` | float | 30.0 | Drain window for starting additional sends after SIGTERM |
| `--broker-outage-cooldown` | float | 30.0 | Breaker cooldown before the next batch attempt |
| `--max-backoff` | float | 3600.0 | Upper bound for normal message retry delay |
| `--liveness-file` | path | None | File to touch after each batch |

### Examples

```bash
# Default production-style command with liveness probe
python manage.py celery_outbox_relay --liveness-file /tmp/relay-alive

# Lower-latency development loop
python manage.py celery_outbox_relay --batch-size 25 --idle-time 0.5 --send-timeout 5.0

# Full relay knob surface
python manage.py celery_outbox_relay \
  --batch-size 100 \
  --idle-time 1.0 \
  --backoff-time 120 \
  --max-retries 5 \
  --stale-timeout-seconds 300 \
  --send-timeout 10.0 \
  --shutdown-timeout 30.0 \
  --broker-outage-cooldown 30.0 \
  --max-backoff 3600.0 \
  --liveness-file /tmp/relay-alive
```

## celery_outbox_stats

Show outbox statistics.

```bash
python manage.py celery_outbox_stats [--format text|json] [--top N] [--stale-timeout-seconds N]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--format` | `text` \| `json` | `text` | Render human-readable or JSON output |
| `--top` | int | `10` | Number of top failing task groups to include |
| `--stale-timeout-seconds` | int | `CELERY_OUTBOX_STALE_TIMEOUT_SECONDS` or `300` | Recovery window used when classifying stale in-flight rows as live backlog |

Text output:

```
Queue depth:     42
DLQ count:       3
Oldest pending:  5m 0s

Top failing tasks:
  1. myapp.tasks.process_order (12 retries)
  2. myapp.tasks.send_email (4 retries)
```

JSON output includes `queue_depth`, `dlq_count`, `oldest_pending_seconds`, and `top_failing`.

## celery_outbox_purge_dead_letter

Purge old dead letter entries.

```bash
python manage.py celery_outbox_purge_dead_letter --older-than-dead 30d
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--older-than-dead` | str | None | Delete records where `dead_at` is older than the specified duration |
| `--older-than-created` | str | None | Delete records where `created_at` is older than the specified duration |
| `--task-name` | str | None | Optional task-name glob for filtering dead letters |
| `--dry-run` | flag | `False` | Show what would be deleted without deleting records |

If neither retention flag is provided, the command falls back to `CELERY_OUTBOX_DLQ_RETENTION` from Django settings. CLI retention flags override that settings-based policy.
