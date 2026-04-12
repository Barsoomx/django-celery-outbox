# Celery Version Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Celery version matrix (5.3, 5.4, 5.5, 5.6) to CI with bleeding-edge job for early warning.

**Architecture:** PostgreSQL gets full Celery matrix (24 jobs), MySQL gets only latest Celery (6 jobs), plus one bleeding-edge job. Django reduced to LTS (4.2) + latest (5.2). Total: 31 jobs.

**Tech Stack:** GitHub Actions, pytest, PostgreSQL 15, MySQL 8.0

**Spec:** `docs/superpowers/specs/2026-04-12-celery-version-matrix-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `.github/workflows/tests.yml` | Modify | CI workflow with matrix |
| `README.md` | Modify | Add Compatibility table |

---

### Task 1: Update tests.yml matrix strategy

**Files:**
- Modify: `.github/workflows/tests.yml:51-59`

- [ ] **Step 1: Update matrix definition**

Replace current matrix (lines 54-59):
```yaml
        python-version: ['3.10', '3.11', '3.12']
        django: ['4.2', '5.0', '5.1', '5.2']
        db: ['postgresql', 'mysql']
```

With new matrix + include:
```yaml
        python-version: ['3.10', '3.11', '3.12']
        django: ['4.2', '5.2']
        celery: ['5.3', '5.4', '5.5', '5.6']
        db: ['postgresql']
        include:
          - python-version: '3.10'
            django: '4.2'
            celery: '5.6'
            db: 'mysql'
          - python-version: '3.11'
            django: '4.2'
            celery: '5.6'
            db: 'mysql'
          - python-version: '3.12'
            django: '4.2'
            celery: '5.6'
            db: 'mysql'
          - python-version: '3.10'
            django: '5.2'
            celery: '5.6'
            db: 'mysql'
          - python-version: '3.11'
            django: '5.2'
            celery: '5.6'
            db: 'mysql'
          - python-version: '3.12'
            django: '5.2'
            celery: '5.6'
            db: 'mysql'
```

- [ ] **Step 2: Update job name**

Change line 52:
```yaml
    name: Python ${{ matrix.python-version }} - Django ${{ matrix.django }} - ${{ matrix.db }}
```

To:
```yaml
    name: Py${{ matrix.python-version }} Dj${{ matrix.django }} Cel${{ matrix.celery }} ${{ matrix.db }}
```

- [ ] **Step 3: Add Install Celery version step**

After line 111-112 (Install Django version):
```yaml
      - name: Install Django version
        run: pip install "Django~=${{ matrix.django }}"
```

Add:
```yaml
      - name: Install Celery version
        run: pip install "celery~=${{ matrix.celery }}"
```

- [ ] **Step 4: Validate YAML syntax**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/tests.yml'))"
```

Expected: No output (valid YAML)

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/tests.yml
git commit -m "ci: add Celery version matrix to test workflow"
```

---

### Task 2: Add bleeding-edge job

**Files:**
- Modify: `.github/workflows/tests.yml` (append after test job)

- [ ] **Step 1: Add bleeding-edge job**

Append after the `test` job (after line 122):

```yaml

  bleeding-edge:
    name: Bleeding Edge (latest Django + Celery)
    runs-on: ubuntu-latest
    continue-on-error: true
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - name: Upgrade pip
        run: python -m pip install --upgrade pip
      - name: Install package with test dependencies
        run: pip install -e '.[test]'
      - name: Install latest Django and Celery
        run: pip install --upgrade Django celery
      - name: Run tests
        env:
          DB_ENGINE: postgresql
          DB_HOST: 127.0.0.1
          DB_NAME: test_db
          DB_USER: test
          DB_PASSWORD: test
          DB_PORT: 5432
        run: pytest -v
```

- [ ] **Step 2: Validate YAML syntax**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/tests.yml'))"
```

Expected: No output (valid YAML)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/tests.yml
git commit -m "ci: add bleeding-edge job for latest Django/Celery"
```

---

### Task 3: Add Compatibility table to README

**Files:**
- Modify: `README.md:36` (after Database Requirements section)

- [ ] **Step 1: Add Compatibility section**

After line 36 (`SQLite is **not supported** and will raise an error at startup.`), add:

```markdown

## Compatibility

| Dependency | Versions |
|------------|----------|
| Python     | 3.10, 3.11, 3.12 |
| Django     | 4.2 LTS, 5.0, 5.1, 5.2 * |
| Celery     | 5.3, 5.4, 5.5, 5.6 |
| Database   | PostgreSQL 15+, MySQL 8.0+ |

\* CI tests LTS (4.2) and latest (5.2); intermediate versions supported but not tested in every combination.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add Compatibility table to README"
```

---

### Task 4: Final verification

- [ ] **Step 1: Count matrix jobs**

Run:
```bash
echo "PostgreSQL jobs: $((3 * 2 * 4))"
echo "MySQL jobs: 6"
echo "Bleeding-edge: 1"
echo "Total: $((3 * 2 * 4 + 6 + 1))"
```

Expected:
```
PostgreSQL jobs: 24
MySQL jobs: 6
Bleeding-edge: 1
Total: 31
```

- [ ] **Step 2: Verify all changes**

Run:
```bash
git log --oneline -3
```

Expected: 3 new commits for this feature

- [ ] **Step 3: Push branch**

Run:
```bash
git push origin feature/ci-security-scanning
```
