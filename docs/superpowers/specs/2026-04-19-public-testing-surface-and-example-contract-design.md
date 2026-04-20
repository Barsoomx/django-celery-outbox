# Public Testing Surface And Example Contract - Design Spec

**Date:** 2026-04-19
**Status:** Draft
**Depends On:** `docs/superpowers/specs/2026-04-18-export-pytest-fixtures-design.md`, `docs/superpowers/specs/2026-04-12-documentation-example-project-design.md`, `docs/superpowers/specs/2026-04-19-release-integrity-and-ci-contract-hardening-design.md`

## Problem

The package now ships a public pytest plugin and a documented example project, but both still depend too much on unstable internal assumptions:

- the shipped fixtures import private helpers and patch private relay/publisher seams directly
- source-tree contract tests globally patch connection recycling, which hides part of the real runtime behavior they claim to represent
- example-project CI can miss package changes that break the documented integration contract

These are not release-pipeline bugs. They are public-support-surface bugs.

## Goals

- Give the packaged pytest plugin one narrow package-owned support boundary.
- Keep downstream public API limited to the shipped fixtures, not a new general testing framework.
- Treat the example project as documentation-as-contract and keep it running on every push and pull request.
- Stop treating globally patched connection-recycling behavior as acceptable default coverage for "integration" style tests.

## Non-Goals

- No new broad testing API for downstream users.
- No second plugin or testing framework.
- No duplication of release-gating logic already owned by the release-integrity spec.

## Options Considered

### 1. Leave the plugin on private internals

Pros:

- No new files

Cons:

- Every relay/internal refactor risks breaking a supported public fixture surface

### 2. Add one narrow support module and contract-aware example CI

Pros:

- Contains the stability surface to one place
- Keeps the public API small
- Lets example CI catch real package regressions

Cons:

- Adds one more documented internal seam

### 3. Promote many internal helpers to public API

Pros:

- Maximum explicitness

Cons:

- Too much surface area for the actual problem

## Decision

Choose option 2.

The package should own one narrow stable support seam for its own public fixtures instead of pretending private helpers are free to churn.

## Design

### 1. Add one package-owned fixture support module

Introduce one narrow module dedicated to the shipped pytest plugin.

Responsibilities:

- fixture-facing app loading
- fixture-facing drain / relay invocation seam
- fixture-facing fake-relay patch helpers

Rules:

- the support module is semver-stable for package-owned fixtures
- it is not advertised as a general downstream testing API
- the public downstream contract remains the fixtures themselves

### 2. Reclassify the current patched "integration" tests correctly

Current repository tests that patch the broker send path remain valuable, but they are contract tests around package seams, not the required live-broker release lane.

Decision:

- keep them as fast source-tree contract tests
- stop treating them as the only evidence for live integration
- align names/docs with the release-integrity spec's real-broker lane
- stop globally patching connection recycling across the whole suite; patches must be test-local and justified by the exact assertion being made

This keeps the fast feedback loop while making the contract honest.

### 3. Make example-project CI contract-aware

Keep the example workflow always-on for `push` and `pull_request`. Do not add a `paths:` filter. The user-facing example is part of the repository contract, so it should run every time rather than only for selected file changes.

The example workflow must install the same built package artifact produced by CI rather than an unbuilt source tree. That keeps the example project aligned with the actual release artifact and turns the example into a real packaging-contract check instead of only a source-tree smoke test.

## Existing Specs And How This One Extends Them

- `2026-04-18-export-pytest-fixtures-design.md` remains the base for the fixture set and plugin entry point. This spec only stabilizes the fixture support seam behind that public surface.
- `2026-04-12-documentation-example-project-design.md` remains the base for the example app itself. This spec hardens the CI contract around it.
- `2026-04-19-release-integrity-and-ci-contract-hardening-design.md` owns artifact and live-broker release gating. This spec only covers the public testing surface and example contract that feed into those gates.

## Testing And Verification

- fixture tests prove the shipped pytest plugin works through the new support module rather than unrelated private imports
- example CI proves package changes can trigger the example workflow
- example CI proves the example workflow stays always-on for push and pull_request
- example workflow proves the example can install and boot against the same package artifact CI built
- source-tree contract tests remain green after the support-boundary extraction
- source-tree contract tests prove connection-recycling patches are narrow and local rather than global default behavior

## Rollout Notes

- the support module may have an internal-looking name, but the stability rule for package-owned fixtures must be explicit in docs and tests
- docs should stop implying that patched source-tree contract tests are equivalent to the live-broker release lane
