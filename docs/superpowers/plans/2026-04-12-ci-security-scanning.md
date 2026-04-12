# CI Security Scanning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automated vulnerability scanning to CI pipeline with pip-audit, CodeQL, and Dependabot security updates.

**Architecture:** Four independent changes: (1) pip-audit job in tests.yml, (2) new CodeQL workflow, (3) Dependabot security config, (4) README badge.

**Tech Stack:** GitHub Actions, pip-audit, CodeQL, Dependabot

**Spec:** `docs/superpowers/specs/2026-04-12-ci-security-scanning-design.md`

**Issue:** [#35](https://github.com/Barsoomx/django-celery-outbox/issues/35)

---

### Task 1: Add pip-audit job to tests.yml

**Files:**
- Modify: `.github/workflows/tests.yml`

- [ ] **Step 1: Add security job with pip-audit**

Add new `security` job before existing jobs in `.github/workflows/tests.yml`:

```yaml
  security:
    name: Security Audit
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - name: Install dependencies
        run: pip install -e '.[dev,test]'
      - name: Run pip-audit
        uses: pypa/gh-action-pip-audit@v1.1.0
```

Insert after line 16 (`jobs:`), before `lint:` job.

- [ ] **Step 2: Verify YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/tests.yml'))"`
Expected: No output (valid YAML)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/tests.yml
git commit -m "ci: add pip-audit security scanning to CI

Closes part of #35"
```

---

### Task 2: Create CodeQL workflow

**Files:**
- Create: `.github/workflows/codeql.yml`

- [ ] **Step 1: Create CodeQL workflow file**

Create `.github/workflows/codeql.yml`:

```yaml
name: CodeQL

on:
  push:
    branches:
      - master
  pull_request:
  schedule:
    - cron: '0 6 * * 1'

permissions:
  contents: read
  security-events: write

jobs:
  analyze:
    name: Analyze Python
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Initialize CodeQL
        uses: github/codeql-action/init@v3
        with:
          languages: python

      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@v3
        with:
          category: /language:python
```

- [ ] **Step 2: Verify YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/codeql.yml'))"`
Expected: No output (valid YAML)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/codeql.yml
git commit -m "ci: add CodeQL security analysis workflow

Closes part of #35"
```

---

### Task 3: Add Dependabot security updates

**Files:**
- Modify: `.github/dependabot.yml`

- [ ] **Step 1: Update Dependabot config with security group**

Replace `.github/dependabot.yml` with:

```yaml
version: 2

updates:
  - package-ecosystem: pip
    directory: /
    open-pull-requests-limit: 15
    schedule:
      interval: weekly
      day: monday
      timezone: Etc/UTC
    labels:
      - dependencies
    groups:
      security:
        applies-to: security-updates
        patterns:
          - '*'
```

- [ ] **Step 2: Verify YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/dependabot.yml'))"`
Expected: No output (valid YAML)

- [ ] **Step 3: Commit**

```bash
git add .github/dependabot.yml
git commit -m "ci: enable Dependabot security update grouping

Closes part of #35"
```

---

### Task 4: Add security badge to README

**Files:**
- Modify: `README.md:3`

- [ ] **Step 1: Add CodeQL badge after CI badge**

In `README.md`, after line 3 (CI badge), add:

```markdown
[![CodeQL](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/codeql.yml/badge.svg)](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/codeql.yml)
```

Line 3 becomes:
```markdown
[![CI](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/ci.yml/badge.svg)](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/codeql.yml/badge.svg)](https://github.com/Barsoomx/django-celery-outbox/actions/workflows/codeql.yml)
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add CodeQL security badge to README

Closes #35"
```

---

## Verification

After all tasks complete:

- [ ] Push branch and create PR
- [ ] Verify pip-audit job runs on PR
- [ ] Verify CodeQL workflow triggers
- [ ] Check Dependabot settings in repo Security tab
