# CI Security Scanning Design

**Issue:** [#35](https://github.com/Barsoomx/django-celery-outbox/issues/35)
**Date:** 2026-04-12

## Problem

CI runs ruff, mypy, pytest but has no automated vulnerability scanning. CVEs in transitive dependencies (sentry-sdk, structlog, datadog, celery, Django) ship undetected.

## Solution

### 1. pip-audit step

Add `security` job to `.github/workflows/tests.yml`:
- Uses `pypa/gh-action-pip-audit@v1.1.0`
- Runs on every PR and push to master
- Fails if known-vulnerable pinned versions detected

### 2. GitHub CodeQL workflow

New file `.github/workflows/codeql.yml`:
- Standard GitHub CodeQL analysis for Python
- Triggers on push to master and PRs
- Requires `security-events: write` permission

### 3. Dependabot security updates

Update `.github/dependabot.yml`:
- Add `groups` configuration for security updates
- Keep existing weekly schedule for regular updates

### 4. README badge

Add CodeQL security badge after existing CI badge in `README.md`.

## Files to Change

| File | Action |
|------|--------|
| `.github/workflows/tests.yml` | Add `security` job with pip-audit |
| `.github/workflows/codeql.yml` | Create new CodeQL workflow |
| `.github/dependabot.yml` | Add security updates group |
| `README.md` | Add security badge |

## Acceptance Criteria

- [x] pip-audit step on every PR; failing on known-vulnerable pinned versions
- [x] GitHub CodeQL workflow enabled for Python
- [x] Dependabot security-advisory updates enabled
- [x] README badge for security scan status
