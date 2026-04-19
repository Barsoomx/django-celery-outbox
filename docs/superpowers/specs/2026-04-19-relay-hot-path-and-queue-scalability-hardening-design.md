# Relay Hot Path And Queue Scalability Hardening - Design Spec

**Date:** 2026-04-19
**Status:** Draft
**Depends On:** `docs/superpowers/specs/2026-04-18-relay-robustness-hardening-design.md`, `docs/superpowers/specs/2026-04-12-operator-cli-stats-design.md`, `docs/superpowers/specs/2026-04-12-dead-letter-purge-design.md`, `docs/superpowers/specs/2026-04-12-observability-security-hardening-design.md`

## Problem

The relay and queue-inspection path still has both correctness and scale issues:

- breaker-open handling can defer already-exceeded rows instead of dead-lettering them
- outage streak is reset every batch, which makes breaker behavior effectively batch-local
- every relay cycle recomputes queue-wide snapshots directly in the hot path
- `celery_outbox_stats` performs the same expensive snapshot work and defaults into a live `GROUP BY task_name`
- selector and retention queries are under-indexed
- dead-letter purge still performs one large delete transaction

The accepted performance follow-ups point in the same direction:

- single-step claim + mark-in-flight where the backend allows it

## Goals

- Fix breaker correctness without reopening the relay architecture.
- Reduce repeated full-table work in the relay and operator snapshot path.
- Add only the indexes and fast paths that directly serve current queries.
- Keep default semantics conservative and safe on both PostgreSQL and MySQL.
- Reduce hot-path work rather than only deduplicating it.

## Non-Goals

- No distributed breaker or external coordination store.
- No asyncio rewrite.
- No approximate counters, rollup tables, or analytics subsystem.
- No rewrite of the `celery_outbox_stats` output shape beyond what is needed to make it cheap-by-default.
- No CLI redesign for dead-letter purge.
- No parallel publish mode in this spec; that work is split into a dedicated follow-up spec.

## Options Considered

### 1. Correctness-only patch

Fix breaker semantics and add indexes. Leave the rest alone.

Pros:

- Smaller change set

Cons:

- Leaves the relay hot path and stats path doing repeated queue-wide work
- Leaves the purge path with avoidable long delete transactions

### 2. Focused runtime and query hardening

Keep the current internal relay split, fix correctness first, then add targeted query/index improvements and optional fast paths.

Pros:

- Matches the existing module layout
- Keeps scale work close to the real bottlenecks
- Leaves room to defer risky throughput work without invalidating the spec

Cons:

- Larger than a bugfix-only patch

### 3. Full relay rewrite

Replace the current relay orchestration model with a new concurrency-first runtime.

Pros:

- Maximum theoretical performance headroom

Cons:

- Excessive scope
- Reopens already-stabilized behavior for no immediate reason

## Decision

Choose option 2.

This spec builds on the current relay collaborators and focuses on direct hot-path wins. The only risky accelerator, `ThreadPoolExecutor`, is explicitly phase 2 and default-off.

## Design

### 1. Supersede batch-local outage streak behavior

`RelayPolicy` must stop resetting the outage streak at the start of every batch.

New rule:

- consecutive outage-classified publish failures accumulate across batch boundaries
- the streak resets only on a non-outage publish success or when the cooldown window expires

This explicitly supersedes the batch-local streak rule in `2026-04-18-relay-robustness-hardening-design.md`.

### 2. Breaker-open handling must partition remaining rows correctly

When the breaker trips in the middle of a selected batch:

- remaining rows that are already at or beyond `max_retries` go directly to `exceeded`
- remaining rows still eligible for retry go to `deferred_due_to_outage`

The implementation must not treat "remaining selected rows" as one homogeneous set.

### 3. Introduce one shared queue snapshot sampler

Create one internal queue-snapshot sampler used by:

- relay finalization metrics/logging
- `celery_outbox_stats`

Responsibilities:

- queue depth
- dead-letter count
- oldest pending age using relay-consistent pending semantics
- optional `top_failing` aggregation only when explicitly requested

Hot-path rule:

- relay finalization must not recompute the full queue snapshot on every batch
- the sampler refreshes expensive queue-wide values at a bounded cadence
- cheap per-batch counters and duration remain per-batch
- batches between refreshes reuse the last sampled snapshot for gauges/logging

This is what closes review item `#10`; a helper alone is not enough.

Semantics change:

- `queue.depth`, `dead_letter.count`, and `oldest_pending_age_seconds` become sampled queue-wide gauges rather than exact per-batch snapshots
- this spec owns that runtime semantic change
- the operator spec owns the corresponding docs/runbook updates so dashboards and alert guidance describe sampled behavior honestly

### 4. Make `celery_outbox_stats` cheap by default

The stats command keeps the same fields, but changes the cost profile:

- default `--top=0`
- `--top > 0` remains the explicit expensive drilldown path

Reasoning:

- queue depth, DLQ count, and oldest pending age are the production-safe snapshot path
- live `GROUP BY task_name` over a large outbox should be opt-in, not the default

This intentionally supersedes the default-cost assumption in `2026-04-12-operator-cli-stats-design.md` while preserving the command itself.

### 5. Add only targeted supporting indexes

Keep the existing partial "new pending rows" index and add only the indexes required for the actual selector and retention branches:

- outbox retry branch: index on `retry_after, id` for retryable rows
- outbox stale-recovery branch: index on `updated_at, id` for rows with `retry_after IS NULL`
- dead-letter retention: index on `dead_at`
- dead-letter retention: index on `created_at`

Do not add GIN, trigram, or speculative composite-index matrices.

Acceptance rule:

- index choices must be justified by `EXPLAIN` evidence on PostgreSQL and MySQL for the actual selector or retention query shape
- if the planner does not use the proposed indexes effectively, the implementation must fall back to selector rewrite or backend-specific fast paths instead of shipping inert indexes

### 6. Single-step claim + mark-in-flight is an optional fast path

Preserve `MessageSelector.run()` as the seam, but allow a backend-specific fast path underneath it:

- preferred fast path: one SQL statement that selects eligible rows with `SKIP LOCKED`, marks them in-flight, and returns the claimed rows
- fallback: current ORM select-then-update behavior

Rules:

- fast path may be PostgreSQL-first
- MySQL can join later if parity is straightforward
- unsupported backends keep the current ORM path

This keeps the public and test seams stable while allowing a measurable DB round-trip win where it is easy.

### 7. Change dead-letter purge to ordered chunked deletes

Preserve the current CLI and retention contract, but change delete execution from one large `queryset.delete()` to ordered PK chunks.

Behavior:

- dry-run remains aggregate-oriented
- destructive mode deletes deterministic PK chunks until exhausted
- chunk size is internal configuration, not new public CLI

This reduces long transactions, WAL growth, and replication lag risk on large DLQ tables.

## Existing Specs And How This One Extends Them

- `2026-04-18-relay-robustness-hardening-design.md` remains the baseline for relay collaborator boundaries, but this spec supersedes two concrete decisions:
  - batch-local outage streak reset
  - homogeneous outage deferral of remaining selected rows
- `2026-04-12-operator-cli-stats-design.md` remains the baseline for the stats command, but this spec changes the default cost profile and snapshot internals.
- `2026-04-12-dead-letter-purge-design.md` remains the baseline for purge CLI and retention semantics; this spec only changes execution strategy and supporting indexes.
- `2026-04-12-observability-security-hardening-design.md` is partially superseded for queue-wide gauge semantics; this spec aligns `oldest_pending_age_seconds` with the real relay selector semantics and moves `queue.depth` / `dead_letter.count` to sampled queue-wide gauges instead of exact per-batch snapshots.

## Testing And Verification

- breaker regression: remaining selected rows split between retryable and already-exceeded; exceeded rows must DLQ immediately
- low-volume regression: two consecutive outages across separate batches still open the breaker
- query-count regression: relay finalization samples queue-wide state at a bounded cadence instead of every batch
- stats regression: default `--top=0` avoids `GROUP BY task_name`; `--top > 0` still returns the same shape
- migration and index verification on PostgreSQL and MySQL with `EXPLAIN` evidence for selector and retention queries
- selector parity tests between ORM fallback and SQL fast path, if fast path is implemented
- purge tests: ordered chunked delete removes all matches and preserves dry-run output

## Rollout Notes

- correctness fixes land before optional concurrency work
- any future parallel publish mode is intentionally split into a dedicated follow-up spec
- docs should call out the new cheap-by-default `celery_outbox_stats` behavior explicitly
