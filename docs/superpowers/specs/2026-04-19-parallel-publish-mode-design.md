# Parallel Publish Mode - Design Spec

**Date:** 2026-04-19
**Status:** Draft
**Depends On:** `docs/superpowers/specs/2026-04-19-relay-hot-path-and-queue-scalability-hardening-design.md`

## Problem

For deployments that outgrow strictly serial broker publish, the clearest next lever is bounded concurrency. The reviewed package still publishes one message at a time, which means throughput tracks broker round-trip latency closely.

At the same time, relay correctness now depends on strict invariants around:

- breaker opening mid-batch
- shutdown deadlines
- single-threaded DB mutation and signal emission

That makes parallel publish a separate design problem, not a footnote inside general relay hardening.

## Goals

- Define a safe optional parallel publish mode for high-throughput deployments.
- Keep all DB selection, mutation, and signal emission in the main thread.
- Preserve breaker, shutdown, and duplicate-tolerant semantics.
- Keep serial publish as the default and recommended mode.

## Non-Goals

- No asyncio rewrite.
- No distributed work stealing across relay replicas.
- No guarantee that every broker transport benefits equally.
- No change to the default relay throughput mode.

## Decision

Treat bounded parallel publish as a dedicated follow-up feature with its own implementation plan.

## Design

### 1. Add one optional runtime knob

- `publish_concurrency`, default `1`

When `publish_concurrency == 1`, relay behavior is identical to the serial path.

### 2. Use a sliding window, not eager whole-batch submission

The relay must not enqueue futures for the full selected batch up front.

Use a bounded sliding window:

- submit at most `publish_concurrency` sends
- as each future completes, decide whether another send may start
- stop opening new futures once shutdown deadline is reached
- stop opening new futures once the breaker opens

This preserves the current "stop starting new sends" invariant even though some sends may already be in flight.

Classification rule when shutdown or breaker-open hits:

- already-submitted futures are allowed to complete and are classified from their real publish outcome
- messages not yet submitted stay under main-thread control and are classified using the same serial rules:
  - shutdown path -> `shutdown_aborted`
  - breaker-open path -> partition into `exceeded` vs `deferred_due_to_outage`

### 3. Keep DB mutation and signals on the main thread

Worker threads may do only broker publish I/O against already-materialized message payloads.

Main thread responsibilities:

- result collection
- breaker state updates
- shutdown checks
- metrics
- signal emission
- DB mutations

### 4. Preserve the same result partitioning contract

Parallel publish must still end the batch with the same logical groups:

- `published`
- `failed`
- `exceeded`
- `deferred_due_to_outage`
- `shutdown_aborted`

The difference is only how publish I/O is scheduled, not how outcomes are classified.

### 5. Bound scope to a proven broker path first

The first implementation should target one known-good broker path and one bounded CI lane. It should not promise transport-agnostic speedups without evidence.

## Testing And Verification

- sliding-window tests prove the relay never exceeds `publish_concurrency`
- shutdown tests prove no new futures start after deadline
- breaker tests prove no new futures start after breaker open
- thread-safety tests prove DB mutations and signal emission stay on the main thread
- one real-broker performance smoke path proves the mode works beyond mocks

## Rollout Notes

- serial mode remains the default and recommended baseline
- this feature should land only after the serial relay hardening spec is complete
