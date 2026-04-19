# Relay Robustness Hardening - Design Spec

**Issue:** [#21](https://github.com/Barsoomx/django-celery-outbox/issues/21)
**Date:** 2026-04-18
**Status:** Approved
**Depends On:** `docs/superpowers/specs/2026-04-11-audit-refactoring-design.md`

## Problem

Issue `#21` identifies five relay reliability gaps:

1. no explicit publish timeout on `Celery.send_task()`
2. no shutdown deadline for an in-flight batch
3. no batch-level circuit breaker / broker outage cooldown
4. no cap on exponential retry backoff
5. no configurable stale timeout

Since the issue was opened, the repository changed:

- `stale_timeout_seconds` is already implemented in `RelayConfig`, `MessageSelector`, and `celery_outbox_relay --stale-timeout-seconds`
- the relay hot path has now been split into `_publisher.py`, `_mutations.py`, `_runtime.py`, and a thinner `_relay.py`
- the package now exports pytest fixtures that use `Relay._processing()` as a synchronous one-shot relay seam

That changes the design target. The task is no longer "patch the monolithic relay hot path directly". It is "design a follow-on reliability layer on top of the landed relay split without fighting it".

## Goals

- Add explicit relay-level knobs for publish timeout, shutdown timeout, broker outage cooldown, and capped message retry backoff.
- Prevent temporary broker outages from consuming per-message retries and flooding the dead letter queue.
- Keep relay shutdown semantics realistic for Python + Kombu network I/O.
- Preserve the current duplicate-tolerant recovery model and broker-confirm caveat.
- Keep the public surface narrow and compatible with the current management-command-driven relay configuration model.
- Align the design with the current relay collaborator structure produced by the approved relay refactor.

## Non-Goals

- No new Redis or other external dependency for breaker coordination.
- No cluster-wide shared circuit breaker across relay replicas.
- No Django settings API for relay runtime knobs in this change.
- No forced interruption of an already-running `send_task()` system call.
- No redesign of `MessageSelector` or replacement of `stale_timeout_seconds`.
- No attempt to collapse the relay collaborators back into a monolithic `_relay.py`.

## Constraints

- Public `Relay`, `RelayConfig`, management command entry point, settings names, signals, and migration history must remain compatible.
- The relay remains safe for multiple replicas via `SELECT FOR UPDATE SKIP LOCKED`.
- Liveness touching remains batch-based.
- Existing duplicate-tolerant recovery semantics and broker-confirm caveat remain true.
- Any cooldown sleep must happen outside database transactions.
- Exported pytest fixtures must remain viable: `Relay._processing()` stays usable as the synchronous one-shot drain seam, and fake broker interception must continue to work at the raw `Celery.send_task` publish boundary.
- `drain_outbox()` currently creates a fresh `Relay` for each synchronous pass. The reliability design must therefore treat breaker/cooldown state as daemon-process state, not a persisted cross-pass test-helper state.

## Options Considered

### 1. Focused follow-up on target relay seams

Extend the post-refactor relay shape with a small reliability policy layer and a few new CLI / `RelayConfig` knobs.

Pros:

- Compatible with the approved relay refactor
- Keeps reliability logic explicit and testable
- Limits public API growth

Cons:

- Adds one more internal collaborator to a path that was only recently split

### 2. Dedicated policy layer

Add a new internal `_policy.py` module responsible for outage classification, breaker state, shutdown state, and capped backoff decisions. `Relay` orchestrates it alongside `_publisher.py` and `_mutations.py`.

Pros:

- Gives reliability behavior a clear home
- Avoids bloating `_relay.py` again after the split
- Makes policy decisions testable without patch-heavy relay tests

Cons:

- Slightly larger internal design than a purely inline patch

### 3. Shared breaker using Redis or another external store

Coordinate broker-outage state across relay replicas.

Pros:

- Single breaker state across the whole deployment

Cons:

- Adds a new operational dependency
- Complicates failure modes and tests
- Unnecessary for the first version

## Decision

Choose option 2, as a follow-on to option 1's sequencing.

This feature set is now designed against the current relay structure, not the old monolith. The implementation plan should target the already-landed `_publisher.py`, `_mutations.py`, `_runtime.py`, and orchestration-only `_relay.py` directly.

Internally, the new behavior will live in `django_celery_outbox/relay/_policy.py`. The breaker is process-local and in-memory only. Public configuration is still exposed only through `RelayConfig` and management-command flags.

## Public Configuration Contract

### Existing knob retained

- `stale_timeout_seconds` stays as the existing relay selector / stale-row recovery knob.

This issue does not redesign stale-timeout behavior. It only documents the already-implemented knob and clarifies how it interacts with shutdown-aborted messages.

### New knobs

Add these `RelayConfig` fields and matching CLI flags:

- `send_timeout`
- `shutdown_timeout`
- `broker_outage_cooldown`
- `max_backoff`

All four knobs are positive seconds-valued runtime settings. `float` input remains acceptable for CLI and config parsing, matching the existing style of `idle_time`.

Naming should stay operational and literal rather than abstract:

- `send_timeout`: timeout passed to the publish boundary
- `shutdown_timeout`: maximum drain window for starting additional sends after `SIGTERM`
- `broker_outage_cooldown`: process-local breaker cooldown before attempting another batch
- `max_backoff`: upper bound for normal message retry delay

Recommended defaults:

- `send_timeout=10.0`
- `shutdown_timeout=30.0`
- `broker_outage_cooldown=30.0`
- `max_backoff=3600.0`

### Explicitly not added

- no Django settings for relay runtime knobs
- no public breaker-threshold setting in v1

The first version keeps the breaker threshold internal to reduce API surface. Recommended default: open the breaker after `2` consecutive outage-classified publish failures in the same batch.

## Target Internal Architecture

The landed relay structure relevant to this work is:

```text
django_celery_outbox/relay/
├── _config.py
├── _message_selector.py
├── _mutations.py
├── _publisher.py
├── _relay.py
└── _runtime.py
```

The target structure after this change is:

```text
django_celery_outbox/relay/
├── _config.py
├── _message_selector.py
├── _mutations.py
├── _policy.py
├── _publisher.py
├── _relay.py
└── _runtime.py
```

### `_policy.py`

Responsibility:

- classify publish failures into broker-outage vs ordinary failure
- hold process-local breaker state
- hold shutdown/draining state
- expose small policy helpers used by `_relay.py`

Expected capabilities:

- `is_broker_outage(exc: Exception) -> bool`
- `begin_batch() -> None`
- `should_skip_batch(now_monotonic: float) -> bool`
- `seconds_until_batch_retry(now_monotonic: float) -> float`
- `record_success() -> None`
- `record_outage(now_monotonic: float) -> None`
- `begin_shutdown(now_monotonic: float) -> None`
- `shutdown_deadline_exceeded(now_monotonic: float) -> bool`

This module does not publish messages and does not mutate database rows.

The outage streak used for breaker opening is batch-local in v1:

- reset at `begin_batch()`
- reset on publish success
- breaker opens after `2` consecutive outage failures in the same batch

### `_publisher.py`

Responsibility:

- publish one message through raw `Celery.send_task()`
- receive `send_timeout` explicitly and pass it through to the publish boundary
- continue to restore headers, Sentry propagation, and structlog context

The publisher does not decide whether an exception means broker outage. It only raises the publish exception to `_relay.py`.

### `_mutations.py`

Responsibility:

- apply normal failed-message retry updates with capped backoff
- delete published rows
- move exceeded rows to dead letter
- defer outage-interrupted rows without incrementing retries

New required mutation seam:

- `defer_due_to_outage(message_ids: list[int], cooldown_seconds: float) -> None`

Behavior:

- update `updated_at=Now()`
- set `retry_after=Now() + cooldown`
- leave `retries` unchanged

### `_relay.py`

Responsibility:

- orchestrate selection, publish, mutation, metrics, and signals
- consult `_policy.py` before starting a batch and between messages
- stop starting new messages when shutdown deadline is exceeded
- stop the batch early when broker outage opens the breaker

`Relay` should pass four logical groups into mutation / side-effect handling:

- `published`
- `failed`
- `exceeded`
- `deferred_due_to_outage`

Shutdown-aborted but not-yet-started messages are not mutated at all.

## Failure Classification

`_policy.py` must classify outage only from the publish boundary, not from arbitrary code in the relay.

### Treat as broker outage

- `TimeoutError` raised while publishing
- `kombu.exceptions.OperationalError`
- transport-level connection/channel errors surfaced by Celery/Kombu during publish

### Do not treat as broker outage

- option deserialization errors
- malformed task payload or local validation errors
- signal handler errors
- database mutation errors
- unrelated application exceptions outside the broker publish path

The design intentionally keeps the outage classifier narrow. A broad "any `OSError` means outage" rule is too error-prone.

## Batch Processing Semantics

### 1. Breaker check before selection

At the start of each relay iteration:

- if the breaker is open, `Relay` does not select any rows
- it sleeps only until the local cooldown expires
- the sleep happens outside any transaction

Reason:

- broker outage should not stamp new rows as in-flight when the relay already knows it should wait

### 2. Message success

When publish succeeds:

- message goes to `published`
- breaker outage streak resets
- normal sent metrics and sent signal flow continue unchanged

### 3. Ordinary publish failure

When publish fails but the exception is not classified as broker outage:

- message goes to `failed`
- message-level `retries` are incremented during mutation phase
- `retry_after` uses capped backoff
- current `messages.failed` / `messages.exceeded` metrics semantics remain

### 4. Broker outage failure

When publish fails with an outage-classified exception:

- the current message is marked for outage deferral
- the current message does not consume a retry
- the current message does not go to dead letter
- breaker state advances and may open
- if the breaker is not yet open, the batch may continue to the next selected message
- once the breaker opens, the current batch stops processing further sends

### 5. Unstarted messages after breaker opens

If the breaker opens in the middle of a selected batch:

- all remaining already-selected but not-yet-started messages are also deferred via outage cooldown without incrementing retries

This differs intentionally from the shutdown path. Broker outage gets an explicit controlled re-entry via `retry_after`, not stale-timeout recovery.

### 6. Interaction with exported pytest helpers

The public `drain_outbox()` helper remains a strict "flush now or fail" API:

- it may keep constructing a fresh `Relay` for each synchronous pass
- it is not required to preserve breaker/cooldown state across passes
- any no-progress state caused by outage deferral, future `retry_after`, unsupported schema version, or shutdown-aborted rows should still surface as helper failure rather than implicit waiting

This preserves the helper's current contract: deterministic synchronous flushing in the happy path, loud failure when the queue cannot be drained immediately.

## Signals And Logging

Existing public signals remain, but their emission semantics become more explicit:

- ordinary publish success still emits `outbox_message_sent`
- ordinary non-outage failure still emits `outbox_message_failed`
- exceeded messages still emit `outbox_message_dead_lettered`
- outage-deferred messages do not emit `outbox_message_failed`
- shutdown-aborted, not-yet-started messages emit no send/fail/dead-letter signal

The relay should add structured log events for:

- breaker opened
- breaker skipped batch during cooldown
- shutdown deadline exceeded with unstarted selected messages
- outage deferral count for a partially-aborted batch

## Shutdown Semantics

### Design contract

The relay does not attempt to forcibly interrupt an already-running `send_task()` call.

Instead:

- `SIGTERM` or `SIGINT` moves the relay into draining mode
- `_policy.py` stores `shutdown_deadline = monotonic() + shutdown_timeout`
- before starting each next message, `_relay.py` checks whether the deadline is exceeded
- once exceeded, no new publish attempts start

### Consequences

- a currently-running `send_task()` is bounded only by `send_timeout`
- already-selected but not-yet-started messages are not retried, not deferred via outage cooldown, and not dead-lettered
- those messages remain on the existing stale-row recovery path via `stale_timeout_seconds`

### Logging expectation

When shutdown deadline stops a batch early, relay logs the aborted message IDs / task names that were selected but not started. This gives operators visibility into why stale-timeout recovery will occur later.

## Backoff Semantics

### Message-level retry backoff

Ordinary message failures use capped exponential backoff:

```text
delay = min(backoff_time * 2^retries + jitter, max_backoff)
```

Requirements:

- cap applies to the final computed retry delay
- ordinary failed messages continue to increment `retries`
- `max_retries` behavior remains unchanged for ordinary failures

### Broker outage cooldown

Broker outage uses a separate cooldown:

- `broker_outage_cooldown`
- does not increment `retries`
- does not consume retry budget
- does not share the same semantics as `max_backoff`

## Delivery Guarantees

Delivery semantics remain unchanged from the current architecture docs: duplicate-tolerant recovery with broker-confirm caveats, not an unconditional end-to-end at-least-once guarantee.

The docs must explicitly state:

- a publish timeout or transport outage does not prove the broker rejected the message
- if the message actually reached the broker before timeout / disconnect surfaced, a later retry can duplicate delivery
- if the broker accepts a publish without confirms or fails silently, the relay can still delete the outbox row without a true end-to-end acknowledgement
- consumers must remain idempotent

This is not a regression introduced by the new design; it is an explicit restatement of existing outbox semantics at the publish boundary.

## Replica / Coordination Model

The circuit breaker is process-local:

- one breaker object per relay process
- no shared state across pods or processes
- no Redis
- no thread-local storage

Rationale:

- the relay is currently single-threaded
- each replica will independently see the same broker transport failures
- a shared breaker would add operational complexity that is not justified for v1

## Testing Strategy

### `_policy.py` unit tests

- outage vs non-outage classification
- breaker opens after `2` consecutive outage failures in one batch
- `begin_batch()` resets the outage streak
- success resets outage streak
- cooldown expiry closes the breaker
- shutdown deadline logic blocks starting further messages after expiry

### `_publisher.py` tests

- `send_timeout` is passed through to raw `Celery.send_task()`
- existing header / Sentry / structlog behavior remains intact

### `_mutations.py` tests

- ordinary failures increment `retries`
- ordinary failures use capped backoff
- outage deferral sets `retry_after` without incrementing `retries`
- exceeded messages still move to dead letter unchanged

### `_relay.py` orchestration tests

- open breaker skips selection and sleeps until cooldown expiry
- outage in the middle of a batch stops additional sends
- outage-hit message goes through outage deferral even before the breaker opens
- outage-hit message and unstarted selected messages go through outage deferral after breaker open
- shutdown deadline prevents starting new sends
- shutdown-aborted selected messages remain on stale-timeout recovery path
- outage-deferred and shutdown-aborted paths do not emit misleading failure signals

### Documentation verification

Docs must be updated and verified together with the implementation:

- command docs include all relay flags and correct defaults
- tuning docs distinguish message backoff from outage cooldown
- shutdown docs describe draining semantics accurately

## Documentation Changes Required

Update these files in the implementation phase:

- `docs/relay/command-reference.md`
- `docs/relay/tuning.md`
- `docs/relay/overview.md`
- `docs/operations/runbook.md`
- `docs/operations/health-checks.md`
- `docs/architecture.md`
- `ARCHITECTURE.md`
- `README.md` if top-level guarantee/config wording is surfaced there

Specific documentation corrections required:

- document the already-existing `--stale-timeout-seconds`
- document the new `send_timeout`, `shutdown_timeout`, `broker_outage_cooldown`, and `max_backoff` flags
- correct any stale `--backoff-time` default that still says `5.0` instead of the current code default
- clarify that graceful shutdown means "stop starting new sends after deadline", not "asynchronously interrupt an in-flight publish"
- document that broker outage cooldown does not burn retry budget

## Sequencing

This work should be implemented against the current split relay structure:

- `_publisher.py`
- `_mutations.py`
- `_runtime.py`
- orchestration-only `_relay.py`

The original intent of this spec was to avoid colliding with the relay refactor while it was still in flight. That coordination concern is now resolved by the current branch state. The implementation plan can proceed directly on top of the landed seams.
