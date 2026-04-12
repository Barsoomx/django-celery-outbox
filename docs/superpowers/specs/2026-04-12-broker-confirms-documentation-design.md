# Broker Publisher Confirms Documentation

GitHub Issue: [#23](https://github.com/Barsoomx/django-celery-outbox/issues/23)

## Problem

The README declares at-least-once semantics, but the relay does not verify that the broker actually accepted each message before deleting it from the outbox. `Celery.send_task()` returning successfully does not imply the broker ACKed the publish.

- RabbitMQ: publisher confirms must be enabled explicitly via `confirm_publish=True`
- Redis: does not support confirms at all

Without publisher confirms on RabbitMQ, a broker rejection (queue full, quota exceeded, network loss mid-publish) silently drops the message.

## Solution

Documentation-only changes to clarify broker configuration requirements.

## Changes

### 1. README.md — "Delivery Guarantees" section

Add "Broker Configuration" subsection after the opening paragraph, before the scenario table.

**Content:**

```markdown
### Broker Configuration

The at-least-once guarantee requires the broker to confirm message acceptance. Without confirmation, a broker failure (network loss, queue full, quota exceeded) can silently drop messages after the relay deletes them from the outbox.

**RabbitMQ** — enable publisher confirms:

```python
BROKER_TRANSPORT_OPTIONS = {
    'confirm_publish': True,
}
```

**Redis** — does not support publisher confirms. Message loss is possible if Redis fails between `LPUSH` and relay cleanup. For production workloads requiring strict at-least-once delivery, use RabbitMQ with publisher confirms.
```

### 2. ARCHITECTURE.md — "Delivery Guarantees" table

Add two rows to the failure scenario table:

| Scenario | Outcome |
|----------|---------|
| Broker rejects message (queue full, quota exceeded) | Relay catches exception, message retried with backoff. Requires broker to signal rejection. |
| Broker fails silently (no publisher confirms) | Message lost. Relay proceeds to delete from outbox. **Enable `confirm_publish` on RabbitMQ; Redis has no confirms.** |

## Acceptance Criteria

- [ ] README explicitly lists broker configuration required for at-least-once (RabbitMQ: `confirm_publish=True`, Redis: acknowledged limitations)
- [ ] ARCHITECTURE.md expands the failure table with broker-level failures
- [ ] No code changes
