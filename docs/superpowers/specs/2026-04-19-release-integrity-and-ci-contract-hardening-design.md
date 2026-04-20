# Release Integrity And CI Contract Hardening - Design Spec

**Date:** 2026-04-19
**Status:** Draft
**Depends On:** `docs/superpowers/specs/2026-04-18-export-pytest-fixtures-design.md`, `docs/superpowers/specs/2026-04-12-ci-security-scanning-design.md`, `docs/superpowers/specs/2026-04-12-celery-version-matrix-design.md`

## Problem

The current release contract still overpromises or under-validates in several places:

- `CHANGELOG.md` documents features that do not exist
- the wheel ships internal `*_tests.py` modules
- the publish workflow does not install and smoke-test the built artifact before release
- release validation still relies on patched local seams instead of a required live-broker CI lane
- compatibility metadata and CI coverage are not aligned tightly enough
- GitHub Actions are pinned to moving tags

## Goals

- Make published artifacts match the intended public package surface.
- Make release workflows validate the built artifact, not just the source tree.
- Make release gating include at least one real broker path before publish.
- Make the documented compatibility story match what CI actually proves.
- Reduce CI supply-chain drift by pinning critical actions immutably.

## Non-Goals

- No exhaustive full-matrix CI across every version combination.
- No replacement of GitHub Actions as the CI platform.
- No full broker farm across the whole matrix.

## Options Considered

### 1. Metadata cleanup only

Fix `CHANGELOG.md`, tighten package discovery, and stop there.

Pros:

- Smallest diff

Cons:

- Leaves release validation and public-surface drift mostly untouched

### 2. Release-contract hardening

Treat package contents, built-artifact smoke tests, live-broker gating, and CI support claims as one release contract.

Pros:

- Directly addresses the validated release risks
- Still keeps CI cost bounded

Cons:

- Requires touching workflows, packaging metadata, and compatibility policy together

### 3. Maximum CI expansion

Add very broad version matrices and real-broker jobs everywhere.

Pros:

- Highest theoretical confidence

Cons:

- Too expensive for the validated gaps
- Not necessary if artifact smoke tests and targeted support jobs exist

## Decision

Choose option 2.

This spec hardens the release contract rather than trying to brute-force confidence with an oversized CI matrix. Public fixture support and example-project contract work are intentionally split into a separate spec.

## Design

### 1. Published artifacts must exclude internal test modules

Tighten package discovery so wheels and sdists include only runtime modules, typing markers, templates, migrations, and documented public plugin files.

Decision:

- `django_celery_outbox/*_tests.py` stays in the repo and source-tree test runs
- those files must not be present in the built wheel

The artifact boundary is the release contract, not the repository layout.

### 2. Publish workflow must smoke-test the built wheel before release

Add a pre-publish release gate that:

- builds sdist and wheel from a clean tree
- installs the wheel into a fresh environment
- verifies package importability
- verifies the management-command entry points load
- verifies the packaged pytest plugin entry point loads from the installed wheel

This smoke test must run on the built artifact, not against the source checkout.

### 3. Add one required live-broker CI lane before release

Keep current source-tree tests as fast local contract tests, but add one explicit live-broker lane to normal CI and require it before publish.

Scope:

- one broker
- minimal publish-and-consume path
- one bounded matrix lane in the normal test workflow
- publish workflow must depend on that lane or rerun the same lane before trusted publishing

This closes the validated gap directly:

- the repository keeps fast patched tests for local contract coverage
- release gating gains one real broker path that blocks shipping regressions

### 4. Reconcile support claims with actual CI

Adopt one consistent policy:

- core matrix remains bounded
- any Django version claimed in package metadata must have at least one explicit CI lane

That means either:

- add targeted smoke lanes for the claimed intermediate Django versions, or
- remove those classifiers

Decision:

- keep the broader compatibility claim only if each claimed version has at least one explicit CI lane

This supersedes the earlier looser interpretation that intermediate versions may remain in classifiers without direct CI coverage.

This explicitly supersedes the compatibility-claim decision in `2026-04-12-celery-version-matrix-design.md` for future releases.

### 5. Pin GitHub Actions to immutable SHAs

All release-critical workflows must use commit SHAs instead of moving tags:

- tests
- publish
- docs
- example CI

Version labels can remain in comments for readability, but execution should use immutable references.

### 6. Changelog must become a release contract

Fix the existing ghost entries and adopt one rule going forward:

- versioned changelog sections describe shipped behavior only
- forward-looking work belongs in issue/spec docs or an explicit unreleased section

Enforcement:

- add a required `release_contract` CI job that blocks publish
- that job verifies the target version section exists, rejects speculative markers in versioned sections, and depends on the built-artifact smoke and live-broker lane

This is intentionally a hard release gate, not only a checklist in prose.

## Existing Specs And How This One Extends Them

- `2026-04-12-ci-security-scanning-design.md` remains the base for CI safety work. This spec extends it to immutable action pinning and artifact validation.
- `2026-04-12-celery-version-matrix-design.md` is partially superseded by this spec's stricter rule: claimed support must have at least one explicit lane.

## Testing And Verification

- wheel and sdist inspection prove no internal test modules are shipped
- built-artifact smoke job proves imports, management commands, and pytest entry points work from the installed wheel
- one required live-broker CI lane proves a real publish path works before release
- CI config verification proves every claimed supported Django version has at least one lane
- workflow audit proves release-critical actions are pinned to SHAs
- release-contract job blocks publish if changelog/version checks fail

## Rollout Notes

- changelog cleanup lands together with release-workflow hardening so the public release story is corrected end-to-end
