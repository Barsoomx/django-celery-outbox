# Producer Contract And Observability Hardening - Design Spec

**Date:** 2026-04-19
**Status:** Draft
**Depends On:** `docs/superpowers/specs/2026-04-18-system-checks-config-validation-design.md`, `docs/superpowers/specs/2026-04-12-observability-security-hardening-design.md`, `docs/superpowers/specs/2026-04-12-dead-letter-purge-design.md`

## Problem

The producer path still has three production-readiness gaps:

1. `OutboxCelery.send_task()` writes the outbox row and then calls `outbox_message_created.send()`. A receiver exception can bubble to the caller after durable enqueue.
2. `sentry_baggage` is stored in `CharField(max_length=2048)`. Legitimate long baggage values can raise `DataError` and abort the caller path.
3. The package ships only relay-side metrics. Operators cannot compare enqueue volume against publish volume without their own instrumentation.

The same path also carries accepted follow-up improvements:

- redactor configuration is still validated only at first use
- invalid `CELERY_OUTBOX_DLQ_RETENTION` still surfaces only when purge runs
- redaction only covers top-level args/kwargs, not serialized callback signatures
- signal kwargs are public by behavior, but undocumented
- redactor mode pays avoidable copy cost on every enqueue

## Goals

- Make producer enqueue behavior durable-first and non-surprising.
- Prevent trace-propagation metadata from breaking the enqueue path.
- Add first-class producer visibility without redesigning the whole metrics surface.
- Catch redactor and DLQ-retention misconfiguration before production traffic hits it.
- Close the obvious redaction blind spot for serialized callback signatures.
- Document the signal contract as public API.

## Non-Goals

- No redesign of the relay path.
- No new mandatory dependency on Sentry or Datadog.
- No new async producer queue or background write path.
- No broad tracing API redesign beyond the existing stored fields and headers.

## Options Considered

### 1. Minimal patch

Change `send()` to `send_robust()`, widen `sentry_baggage`, and stop there.

Pros:

- Smallest diff
- Fixes the two immediate correctness bugs

Cons:

- Leaves producer observability weak
- Leaves redactor/configuration issues to fail at first traffic
- Leaves public signal contract implicit

### 2. Contract hardening bundle

Treat the whole producer intercept path as one public contract: durable enqueue, trace field storage, signal emission, redaction, and metrics.

Pros:

- Fixes the correctness bugs and the most important production follow-ups in one place
- Produces one coherent operator story for enqueue behavior
- Builds directly on the existing checks and observability specs

Cons:

- Larger than a bugfix-only patch

### 3. Full producer API redesign

Introduce a new envelope object for payload, redaction, metrics, and signal delivery.

Pros:

- Clean abstraction boundary

Cons:

- Too much API churn for the actual problem
- Reopens stable paths without evidence it is needed

## Decision

Choose option 2.

The producer intercept path already behaves like public API. The package should harden that contract instead of adding a new abstraction layer.

## Design

### 1. Durable enqueue must not be invalidated by signal receivers

Replace raw `Signal.send()` in the producer path with a small internal helper that:

- uses `send_robust()`
- logs receiver failures with signal name and receiver identity
- never re-raises receiver exceptions after the row has been persisted

The intent is explicit:

- `outbox_message_created` remains a pre-commit signal for compatibility
- it is best-effort and observational only
- receiver failures are logged, not propagated

This change hardens failure behavior without redefining signal timing.

This helper should be reused for any future producer-side signals so the behavior stays uniform.

### 2. `sentry_baggage` storage must stop rejecting valid values

Change both `CeleryOutbox.sentry_baggage` and `CeleryOutboxDeadLetter.sentry_baggage` from bounded `CharField(max_length=2048)` to `TextField(blank=True, null=True)`.

Decision rationale:

- the current bug is a DB-storage bug, not a business-rule validation bug
- silent truncation is worse than wider storage because baggage is opaque propagation data
- widening the column is safer than inventing a package-local maximum that may break tracing semantics unpredictably

This spec does not add a custom baggage truncation policy. The relay continues to propagate the stored value as-is.

### 3. Add one canonical producer metric

Add a producer-side counter emitted via `transaction.on_commit(using=CeleryOutbox.objects.db)`:

- `messages.enqueued`

Characteristics:

- same namespace and tagging rules as existing metrics helpers
- same `task_name` tagging policy as relay metrics
- incremented only for committed rows
- outside `transaction.atomic()`, the callback fires immediately after the write
- excluded-task bypasses do not emit it

Failure policy:

- metric emission from the `on_commit()` callback must itself be best-effort
- metrics backend exceptions are logged and swallowed so a successful commit does not still surface as an application error

This spec intentionally does not add a producer latency histogram or a second family of failure counters. The immediate gap is enqueue volume.

This spec also owns the matching documentation update in `docs/observability/metrics.md`; the operator spec may reference that metric later, but it does not own the metric definition.

### 4. Extend startup validation to redactor and DLQ retention

Extend the existing checks framework with two additional settings validations:

- `celery_outbox.E007`: invalid `CELERY_OUTBOX_PII_REDACTOR`
- `celery_outbox.E008`: invalid `CELERY_OUTBOX_DLQ_RETENTION`

Validation rules:

- redactor may be `None`, dotted path, or callable
- resolved redactor must be callable with the current `(task_name, args, kwargs)` shape
- `CELERY_OUTBOX_DLQ_RETENTION` must match the already-supported purge contract, not a second schema

Runtime code should reuse the same parsing helpers so `manage.py check` and first-use behavior do not drift apart.

### 5. Redaction coverage must include serialized callback signatures

Keep the current public redactor callable shape:

```python
Callable[[str, list, dict], tuple[list, dict]]
```

Do not introduce a new redactor API in this change.

Instead, add an inspection-time traversal step that:

- finds embedded Celery signatures in serialized `options`
- applies the same redactor callable to each embedded task payload
- exposes the redacted result through an inspection-oriented helper/property without mutating the stored publish payload

Compatibility rule:

- enqueue-time redaction semantics do not change in this spec
- `OutboxCelery.send_task()` still invokes the redactor only for top-level `args` / `kwargs`
- nested signature redaction happens only when an inspection surface asks for the inspection-oriented view

The package remains responsible for recursively applying the existing redactor contract where inspection needs it; users should not need a second hook just to cover linked tasks.

Scope boundary:

- `options` remains the stored and published broker payload
- this change extends inspection redaction coverage for signature-bearing option keys only
- this change does not add a second persisted `options` copy
- redactor failures in inspection-time nested traversal must degrade safely to raw `options` plus a log entry rather than breaking enqueue behavior retroactively

### 6. Reduce copy cost without changing semantics

Consolidate top-level producer redaction work into one helper that:

- returns immediately when no redactor is configured
- performs cloning only inside the top-level redaction path
- removes avoidable repeated `deepcopy()` work for `args` / `kwargs`

Nested signature inspection is a separate traversal over serialized `options`; it should not force a larger producer-path rewrite just to satisfy this optimization.

This is deliberately a local optimization around the existing callable contract. It must not silently convert the redactor into a new pure-function API in this change.

### 7. Document the signal kwargs contract

Document, in one dedicated section, the kwargs sent by:

- `outbox_message_created`
- `outbox_message_sent`
- `outbox_message_failed`
- `outbox_message_dead_lettered`

The docs should spell out:

- stable kwarg names
- whether values are scalar or batched lists
- when each signal fires
- best-effort delivery semantics for producer-side signal receivers

This is documentation plus test coverage, not a new runtime signal API.

## Existing Specs And How This One Extends Them

- `2026-04-18-system-checks-config-validation-design.md` already establishes the checks framework and helper reuse pattern. This spec extends that pattern to the redactor and DLQ-retention settings.
- `2026-04-12-observability-security-hardening-design.md` already establishes the redactor concept and the relay-side observability vocabulary. This spec tightens the producer side and clarifies the public contract.

## Testing And Verification

- regression test: producer signal receiver raises, row still persists, `send_task()` still returns `AsyncResult`
- migration test: long `sentry_baggage` persists successfully in outbox and dead letter models
- metric test: `messages.enqueued` increments only on commit, does not increment on rollback, and does not fire for excluded-task bypasses
- metric failure test: metrics backend error during `on_commit()` is logged and swallowed
- checks tests: invalid redactor path, bad callable shape, malformed DLQ retention
- redaction tests: callback, `link_error`, `chain`, and `chord` payloads are redacted with the same callable
- compatibility test: top-level enqueue still invokes the redactor exactly once during `send_task()`
- docs verification: signal kwargs reference matches actual emitted kwargs and `docs/observability/metrics.md` includes `messages.enqueued`

## Rollout Notes

- widening `sentry_baggage` is a straightforward additive schema change
- `send_robust()` behavior changes failure semantics intentionally; docs and changelog must call this out as a producer-contract hardening change
- the producer metric must be reflected in the operator docs, but the canonical metric definition lands here
- inspection-time nested redaction is an additive inspection-surface enhancement, not a change to enqueue-time redactor semantics
