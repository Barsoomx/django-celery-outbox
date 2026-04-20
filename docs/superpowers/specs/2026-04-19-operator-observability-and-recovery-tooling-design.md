# Operator Observability And Recovery Tooling - Design Spec

**Date:** 2026-04-19
**Status:** Draft
**Depends On:** `docs/superpowers/specs/2026-04-18-operational-runbook-design.md`, `docs/superpowers/specs/2026-04-12-operator-cli-stats-design.md`, `docs/superpowers/specs/2026-04-12-observability-security-hardening-design.md`, `docs/superpowers/specs/2026-04-19-producer-contract-and-observability-hardening-design.md`, `docs/superpowers/specs/2026-04-19-relay-hot-path-and-queue-scalability-hardening-design.md`

## Problem

The package ships useful operational pieces, but they do not yet form a coherent operator surface:

- the bundled alert example assumes a scrape target the package does not provide
- the generic top-level relay failure event is not a first-class documented operator signal
- broker-outage states are under-covered by docs and alerts
- the admin summary undercounts live backlog
- deployment docs recommend a DB-privilege model that conflicts with the security guide
- dead-letter alert guidance is inconsistent across docs
- the supported replay path for dead letters is Django admin only
- the Kubernetes example still uses a grace period shorter than the package's own documented drain requirement

## Goals

- Make the shipped operator docs and alert examples match the real runtime signals.
- Give operators one coherent story for backlog, failures, and replay.
- Add a built-in DLQ replay CLI so incident recovery is scriptable.
- Align admin, CLI, docs, and security guidance on the same semantics.
- Keep the package deployment-agnostic while removing misleading examples.

## Non-Goals

- No shipped Prometheus exporter.
- No full dashboard product.
- No web UI beyond the existing Django admin.
- No package-owned HTTP health endpoint.

## Options Considered

### 1. Docs-only cleanup

Fix the alert examples and the documentation wording.

Pros:

- Smallest change

Cons:

- Leaves recovery ergonomics weak
- Leaves admin semantics misleading

### 2. Operator surface hardening

Fix docs, alerts, admin semantics, and DLQ replay ergonomics together.

Pros:

- Produces one coherent operator story
- Matches the actual incident-response surface

Cons:

- Broader than docs-only work

### 3. New operator subsystem

Add dedicated APIs, dashboards, and replay services beyond the current management-command/admin model.

Pros:

- Richest surface

Cons:

- Overkill for the validated gaps

## Decision

Choose option 2.

The package already has the right surface area. It needs the pieces aligned and one missing CLI path.

## Design

### 1. Ship only alert examples that rely on package-provided signals

Remove `up{job="celery-outbox-relay"}` from bundled alert examples.

Replacement strategy:

- use package-emitted metrics for queue growth, oldest pending age, and dead-letter growth
- split the alert story in two on purpose:
  - package-owned `docs/observability/alert-rules.yml` contains only alerts backed by package-emitted metrics
  - deployment docs contain the relay-down examples, based on liveness-file freshness or platform-native workload health

Concrete replacement:

- packaged Prometheus alert rules cover queue-age breach and new-dead-letter growth only
- logging docs and runbook cover `celery_outbox_relay_iteration_failed` as a first-class log/event signal
- deployment docs and the runbook provide the "relay process is dead" examples for Kubernetes and generic process supervision

This keeps the package from pretending it provides a scrape target or health series of its own.

### 2. Promote `celery_outbox_relay_iteration_failed` to a first-class operator signal

Add the generic failure event to:

- `docs/observability/logging-events.md`
- `docs/operations/runbook.md`
- logging guidance with an explicit "wire this event into your log-alerting stack" example

The runbook should explain that this event is the "catch-all relay loop failure" and must have a documented triage path.

### 3. Cover broker-outage and breaker-open states explicitly

Operator docs must stop implying that `messages.failed > 0` is the only broker-health signal.

Add explicit guidance for:

- breaker-open cooldown periods
- outage-deferred messages
- delayed-delivery setup failures

These signals belong in metrics docs, logging docs, and the runbook. The packaged alert examples should include a practical operator expression for "relay process alive, but not delivering", while the deployment docs own "relay process dead" detection.

### 4. Fix backlog semantics in admin without hiding "never attempted"

The admin summary should stop overloading one count as "pending" when it really means "never updated".

Decision:

- define `live_backlog` once as the same pending semantics used by the relay selector and the `celery_outbox_stats queue_depth` snapshot
- show `live_backlog` in admin using that shared definition
- keep a separate `never_attempted` count for operators who still want that narrower view

This spec does not redefine backlog math itself. It consumes the shared backlog/snapshot semantics introduced in the relay scalability spec so admin, CLI, docs, and runbook language stay aligned:

- CLI `queue_depth` == live backlog
- admin `live_backlog` == the same number by definition
- admin `never_attempted` is additional drilldown data, not a competing backlog definition

### 5. Add a built-in DLQ replay CLI backed by shared replay logic

Introduce a management command that replays dead-letter rows back into `celery_outbox`.

Rules:

- admin bulk action and CLI must share the same replay helper
- replay preserves stored payload, trace context, redacted fields, and schema version
- v1 CLI selection is explicit dead-letter row IDs only
- v1 CLI supports `--limit` as the only batching control
- queryset-style filters remain an admin workflow or a future follow-up, not part of v1 CLI scope

This spec intentionally keeps replay simple and explicit. It is an operator recovery tool, not a second relay.

### 6. Make the security guide authoritative for database privileges

Align `docs/deployment/database-setup.md` with `docs/security.md`:

- no `GRANT ALL PRIVILEGES` examples
- deployment docs use least-privilege examples only
- security guide remains the normative source

### 7. Standardize dead-letter alert guidance on new events, not raw absolute count

Adopt one operator recommendation:

- alert on any new dead letters over a rolling time window

Reason:

- raw absolute `dead_letter.count > N` is deployment-specific and inconsistent across docs
- operators care about fresh exceedances, not whether an old baseline is non-zero forever
- one rolling-window rule resolves the current cross-doc conflict instead of replacing it with a second ambiguity

### 8. Fix Kubernetes grace-period guidance

Update deployment examples so `terminationGracePeriodSeconds` is never shorter than one worst-case batch plus margin.

The deployment docs and runbook must agree on this point.

## Existing Specs And How This One Extends Them

- `2026-04-18-operational-runbook-design.md` remains the base incident-playbook document. This spec extends it with missing signals and corrected deployment guidance.
- `2026-04-12-operator-cli-stats-design.md` remains the base for queue snapshot commands. This spec only depends on shared backlog semantics and does not redesign the CLI.
- `2026-04-12-observability-security-hardening-design.md` remains the base for metrics and logging vocabulary. This spec extends that vocabulary where the review proved it incomplete.

## Testing And Verification

- docs build succeeds with strict link checking
- alert-rule examples no longer include `up{job="celery-outbox-relay"}`
- packaged Prometheus alert examples cover queue-age breach and new-dead-letter growth, while logging docs carry the relay-iteration-failed alerting example and deployment docs carry the relay-down examples
- logging docs and runbook both include `celery_outbox_relay_iteration_failed`
- admin and CLI tests verify `live_backlog` / `queue_depth` parity plus separate `never_attempted` counts
- replay command tests prove parity with the admin bulk action and field preservation
- docs verification proves DB setup no longer recommends over-privileged grants
- deployment docs and runbook agree on shutdown grace guidance

## Rollout Notes

- operator docs should reference the producer-side `messages.enqueued` metric once that spec lands
- the replay CLI should be documented as the supported automation path, while admin remains the manual recovery path
