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
| `--backoff-time` | float | 5.0 | Base seconds for exponential backoff |
| `--max-retries` | int | 5 | Retries before dead letter |
| `--liveness-file` | path | None | File to touch after each batch |

### Examples

```bash
# Development (fast polling)
python manage.py celery_outbox_relay --batch-size 10 --idle-time 0.5

# Production (larger batches)
python manage.py celery_outbox_relay --batch-size 500 --idle-time 2.0

# With liveness probe
python manage.py celery_outbox_relay --liveness-file /tmp/relay-alive
```

## celery_outbox_stats

Show outbox statistics.

```bash
python manage.py celery_outbox_stats
```

Output:

```
Pending:      42
Dead Letter:  3
Oldest:       2024-01-15 10:30:00 (5m ago)
```

## celery_outbox_dead_letter_purge

Purge old dead letter entries.

```bash
python manage.py celery_outbox_dead_letter_purge --older-than 30
```

Deletes entries older than 30 days.
