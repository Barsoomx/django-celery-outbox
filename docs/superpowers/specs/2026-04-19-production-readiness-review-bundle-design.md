# Production Readiness Review Bundle - Design Spec

**Date:** 2026-04-19
**Status:** Draft
**Input:** `review-codex.md`

## Problem

`review-codex.md` validates a mixed set of production-readiness gaps:

- producer-side correctness and configuration failures
- relay runtime correctness and throughput limits
- operator observability, recovery, and admin/tooling gaps
- packaging, release, CI, and public-surface integrity issues

One umbrella spec would be too broad for one implementation plan. The failure modes do not share one dependency graph, and bundling runtime code, docs, admin/tooling, and release pipeline changes into one plan would make parallel execution noisy and unsafe.

## Goals

- Cover every real issue and every accepted important nice-to-have from `review-codex.md`.
- Split the work into a small number of specs that can turn into independent implementation plans.
- Reuse already-approved specs where they still apply, and explicitly supersede them where the review changed the target behavior.
- Produce a reading order and implementation order that matches the actual dependency graph.

## Non-Goals

- No code changes in this document.
- No line-by-line restatement of existing approved specs.
- No attempt to collapse all follow-up work into a single execution plan.

## Decision

Create six implementation specs plus this index:

1. `2026-04-19-producer-contract-and-observability-hardening-design.md`
2. `2026-04-19-relay-hot-path-and-queue-scalability-hardening-design.md`
3. `2026-04-19-parallel-publish-mode-design.md`
4. `2026-04-19-operator-observability-and-recovery-tooling-design.md`
5. `2026-04-19-release-integrity-and-ci-contract-hardening-design.md`
6. `2026-04-19-public-testing-surface-and-example-contract-design.md`

This keeps the bundle large enough to cover the whole review, but small enough that each child spec can produce one coherent plan.

## Ownership Map

### Producer Contract And Observability Hardening

Owns:

- real issue 1: `outbox_message_created.send()` can bubble after durable enqueue
- real issue 2: `sentry_baggage` storage can fail on legitimate long values
- real issue 14: no producer-side enqueue metric
- wanted: reduce redactor-path copy cost
- wanted: system check for `CELERY_OUTBOX_PII_REDACTOR`
- wanted: startup validation for `CELERY_OUTBOX_DLQ_RETENTION`
- wanted: document signal kwargs contract
- wanted: extend redaction to serialized callback signatures

Depends on / extends:

- `2026-04-18-system-checks-config-validation-design.md`
- `2026-04-12-observability-security-hardening-design.md`

### Relay Hot Path And Queue Scalability Hardening

Owns:

- real issue 3: breaker defers already-exceeded rows instead of DLQ
- real issue 4: outage streak resets every batch
- real issue 10: repeated queue-wide aggregation in the relay loop
- real issue 11: expensive `stats.py` snapshot and live `GROUP BY task_name`
- real issue 12: insufficient selector and DLQ-retention index coverage
- wanted: single-step claim + mark-in-flight SQL
- wanted: chunked dead-letter purge

Depends on / extends:

- `2026-04-18-relay-robustness-hardening-design.md`
- `2026-04-12-operator-cli-stats-design.md`
- `2026-04-12-dead-letter-purge-design.md`

### Parallel Publish Mode

Owns:

- wanted: bounded parallel publish via `ThreadPoolExecutor`

Depends on / extends:

- `2026-04-19-relay-hot-path-and-queue-scalability-hardening-design.md`

### Operator Observability And Recovery Tooling

Owns:

- real issue 6: Kubernetes grace period example is too short
- real issue 9: no built-in DLQ replay CLI
- real issue 13: shipped alert rule assumes a scrape target the package does not provide
- additional issue 1: no first-class operator workflow for `celery_outbox_relay_iteration_failed`
- additional issue 2: outage states under-covered by metrics and alerts
- additional issue 3: admin undercounts live backlog
- additional issue 4: DB setup docs conflict with security guidance
- additional issue 8: dead-letter alert thresholds are inconsistent across docs

Depends on / extends:

- `2026-04-18-operational-runbook-design.md`
- `2026-04-12-operator-cli-stats-design.md`
- `2026-04-12-observability-security-hardening-design.md`
- producer metric from `2026-04-19-producer-contract-and-observability-hardening-design.md`

### Release Integrity And CI Contract Hardening

Owns:

- real issue 5: `CHANGELOG.md` advertises ghost features
- real issue 7: wheel includes internal `*_tests.py` modules
- real issue 8: publish workflow lacks built-artifact smoke test
- real issue 15: release validation relies on patched local seams and lacks a required live-broker CI lane
- additional issue 5: compatibility metadata overstates CI coverage
- additional issue 6: GitHub Actions pinned to moving tags

Depends on / extends:

- `2026-04-12-ci-security-scanning-design.md`
- `2026-04-12-celery-version-matrix-design.md`

### Public Testing Surface And Example Contract

Owns:

- additional issue 7: example-project CI only runs on `examples/**` changes
- remaining half of real issue 15: source-tree contract tests globally patch connection recycling and need an honest, narrower support boundary
- wanted: stabilize pytest-plugin dependency surface

Depends on / extends:

- `2026-04-18-export-pytest-fixtures-design.md`
- `2026-04-12-documentation-example-project-design.md`
- `2026-04-19-release-integrity-and-ci-contract-hardening-design.md`

## Existing Specs To Reuse Or Supersede

- Reuse the relay module split and reliability seams from `2026-04-18-relay-robustness-hardening-design.md`, but supersede two choices from that spec:
  - outage streak must not be batch-local
  - breaker-open handling must not defer already-exceeded rows
- Reuse the CLI and retention contract from `2026-04-12-dead-letter-purge-design.md`, but extend it with chunked execution and supporting indexes.
- Reuse the `celery_outbox_stats` command surface from `2026-04-12-operator-cli-stats-design.md`, but allow this bundle to change the default cost profile when production safety requires it.
- Reuse system-check structure from `2026-04-18-system-checks-config-validation-design.md`, but extend it to redactor and DLQ-retention validation.
- Reuse the packaged pytest-plugin decision from `2026-04-18-export-pytest-fixtures-design.md`, but add a stricter internal support boundary so the public plugin does not depend on unstable internals.

## Recommended Implementation Order

1. Producer contract and observability hardening
2. Relay hot path and queue scalability hardening
3. Parallel publish mode
4. Operator observability and recovery tooling
5. Release integrity and CI contract hardening
6. Public testing surface and example contract

Reasoning:

- operator docs and alerts should describe the corrected producer/runtime behavior, not the old one
- parallel publish mode is intentionally sequenced after serial relay hardening
- release integrity can run mostly in parallel with runtime work
- public testing surface depends on the release-integrity artifact story and on the final fixture support boundary

## Risks

- The relay scalability spec is the only child with a meaningful risk of overengineering. It must keep `ThreadPoolExecutor` explicitly optional and default-off.
- The operator spec must not silently redefine backlog semantics without preserving a clear admin story for "never attempted" vs "live backlog".
- The packaging spec must reconcile the existing CI-matrix design with the new review finding about overclaimed compatibility instead of letting both documents coexist unqualified.

## Success Criteria

- Every item in `review-codex.md` has exactly one owning child spec.
- No child spec requires reopening the whole design of another child spec.
- The bundle can turn into six independent implementation plans with a clear order and minimal overlap.
