# Release Integrity And CI Contract Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make release artifacts truthful and reproducible by tightening package contents, adding built-artifact and live-broker release gates, aligning support claims with CI, pinning workflows to SHAs, and hardening changelog release checks.

**Architecture:** Keep the existing GitHub Actions layout but add a strict release contract around it. Artifact inspection and built-wheel smoke tests block release before publish. Compatibility claims stay only if CI proves them. Workflow pinning and changelog checks are release-gating hygiene, not optional docs cleanup.

**Tech Stack:** setuptools/pyproject packaging, GitHub Actions YAML, pytest, docker compose, bash/python helper scripts

---

### Task 1: Exclude Internal Test Modules From Published Artifacts

**Files:**
- Add: `setup.py`
- Modify: `MANIFEST.in`
- Add: `tests/release_artifact_tests.py`

- [ ] **Step 1: Add failing artifact-content verification**

```python
pytestmark = pytest.mark.release_artifact


def test_built_wheel_excludes_internal_test_modules(tmp_path: Path) -> None:
    dist_dir = tmp_path / 'dist'
    subprocess.run([sys.executable, '-m', 'build', '--outdir', str(dist_dir)], check=True)

    wheel_path = next(dist_dir.glob('django_celery_outbox-*.whl'))
    with zipfile.ZipFile(wheel_path) as archive:
        names = archive.namelist()

    assert not any(
        name.startswith('django_celery_outbox/') and name.endswith('_tests.py')
        for name in names
    )

    sdist_path = next(dist_dir.glob('django_celery_outbox-*.tar.gz'))
    with tarfile.open(sdist_path) as archive:
        sdist_names = archive.getnames()

    assert not any(
        'django_celery_outbox/' in name and name.endswith('_tests.py')
        for name in sdist_names
    )
```

- [ ] **Step 2: Run the artifact verification**

Run:

```bash
docker compose run --rm app bash -lc "python -m pip install -q build && python -m build && python -m pytest tests/release_artifact_tests.py -v"
```

Expected: FAIL because the wheel still contains `*_tests.py`.

- [ ] **Step 3: Tighten package discovery**

```python
from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class build_py(_build_py):
    def find_package_modules(self, package: str, package_dir: str) -> list[tuple[str, str, str]]:
        modules = super().find_package_modules(package, package_dir)
        return [
            module
            for module in modules
            if not module[1].endswith('_tests')
        ]


setup(cmdclass={'build_py': build_py})
```

```text
recursive-exclude django_celery_outbox *_tests.py
```

- [ ] **Step 4: Re-run artifact verification**

Run:

```bash
docker compose run --rm app bash -lc "python -m pip install -q build && python -m build && python -m pytest tests/release_artifact_tests.py -v"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add setup.py MANIFEST.in tests/release_artifact_tests.py
git commit -m "build: exclude internal test modules from release artifacts"
```

### Task 2: Add Built-Artifact Smoke Gate And Changelog Contract Gate

**Files:**
- Modify: `.github/workflows/publish.yml`
- Modify: `.github/workflows/tests.yml`
- Add: `scripts/check_release_contract.py`
- Add: `tests/release_contract_tests.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add failing contract/smoke checks**

```python
def test_release_contract_rejects_speculative_markers(tmp_path: Path) -> None:
    changelog = tmp_path / 'CHANGELOG.md'
    changelog.write_text('## 1.0.0\n- WIP finalize release notes\n', encoding='utf-8')

    result = subprocess.run(
        [sys.executable, 'scripts/check_release_contract.py', str(changelog)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert 'WIP' in result.stdout + result.stderr


def test_publish_workflow_blocks_on_release_contract_and_live_broker_lane() -> None:
    workflow = Path('.github/workflows/publish.yml').read_text(encoding='utf-8')

    assert 'artifact_smoke:' in workflow
    assert 'release_contract:' in workflow
    assert 'needs: [artifact_smoke, live_broker_smoke]' in workflow
    assert 'needs: [release_contract]' in workflow or 'needs:\n      - release_contract' in workflow
```

- [ ] **Step 2: Run the local release-contract checks**

Run:

```bash
docker compose run --rm app bash -lc "python scripts/check_release_contract.py CHANGELOG.md && python -m pytest tests/release_contract_tests.py -k 'release_contract or publish_workflow' -v"
```

Expected: FAIL until the script and changelog cleanup land.

- [ ] **Step 3: Implement the gate and cleanup**

```yaml
jobs:
  artifact_smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - run: python -m pip install -q build
      - run: pip install -e '.[test]'
      - run: python -m build
      - run: pytest tests/release_artifact_tests.py -v
      - run: pip uninstall -y django-celery-outbox && pip install --force-reinstall dist/*.whl
      - run: |
          cd /tmp
          python - <<'PY'
          import importlib.metadata as metadata
          import json
          import django_celery_outbox
          import django_celery_outbox.management.commands.celery_outbox_relay
          import django_celery_outbox.management.commands.celery_outbox_stats
          import django_celery_outbox.management.commands.celery_outbox_purge_dead_letter

          data = json.loads(metadata.distribution('django-celery-outbox').read_text('direct_url.json'))
          assert data['url'].endswith('.whl'), data
          print(django_celery_outbox.__file__)
          PY

  release_contract:
    needs: [artifact_smoke, live_broker_smoke]
```

- [ ] **Step 4: Re-run local checks, inspect sdist, and smoke the installed wheel**

Run:

```bash
docker compose run --rm app bash -lc "set -e; python -m pip install -q build && python -m build && tar -tf dist/*.tar.gz | sed -n '1,40p' && pip uninstall -y django-celery-outbox && pip install --force-reinstall dist/*.whl && cd /tmp && python - <<'PY'\nimport importlib.metadata as metadata\nimport json\nimport django_celery_outbox\nimport django_celery_outbox.management.commands.celery_outbox_relay\nimport django_celery_outbox.management.commands.celery_outbox_stats\nimport django_celery_outbox.management.commands.celery_outbox_purge_dead_letter\nfrom importlib.metadata import entry_points\n\ndata = json.loads(metadata.distribution('django-celery-outbox').read_text('direct_url.json'))\nassert data['url'].endswith('.whl'), data\npytest11 = entry_points(group='pytest11')\nassert any(ep.name == 'django_celery_outbox' for ep in pytest11)\nprint(django_celery_outbox.__file__)\nPY\ncd /app && python scripts/check_release_contract.py CHANGELOG.md"
```

Expected: PASS, with the sdist inspectable and the installed wheel proving package importability, management-command module importability, pytest entry-point registration, and `direct_url.json` pointing at the wheel rather than the source checkout.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/publish.yml .github/workflows/tests.yml scripts/check_release_contract.py tests/release_contract_tests.py CHANGELOG.md
git commit -m "ci: add release contract and built artifact smoke gates"
```

### Task 3: Add Required Live-Broker CI Lane And Align Support Claims

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `docker-compose.yml`
- Add: `tests/live_broker_smoke_tests.py`

- [ ] **Step 1: Add failing CI/support-policy assertions**

```python
def test_claimed_django_versions_have_explicit_ci_lane() -> None:
    workflow = Path('.github/workflows/tests.yml').read_text(encoding='utf-8')
    pyproject = Path('pyproject.toml').read_text(encoding='utf-8')

    assert 'django: "5.0"' in workflow
    assert 'django: "5.1"' in workflow
    assert 'live_broker_smoke:' in workflow
    assert 'rabbitmq:' in workflow
    assert 'tests/live_broker_smoke_tests.py' in workflow
    assert 'Framework :: Django :: 5.0' in pyproject
    assert 'Framework :: Django :: 5.1' in pyproject
```

- [ ] **Step 2: Run repo-local support-policy checks**

Run:

```bash
docker compose run --rm app python -m pytest tests/release_contract_tests.py -k "ci_lane or support_claim" -v
```

Expected: FAIL because support claims and CI lanes are still misaligned.

- [ ] **Step 3: Implement the required lane and metadata alignment**

```yaml
jobs:
  live_broker_smoke:
    runs-on: ubuntu-latest
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
      rabbitmq:
        image: rabbitmq:3.13-management-alpine
        options: >-
          --health-cmd "rabbitmq-diagnostics check_running"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 10
        ports:
          - 5672:5672
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - run: pip install -e '.[test]'
      - run: pip install "Django~=5.1" "celery~=5.6"
      - env:
          CELERY_BROKER_URL: amqp://guest:guest@127.0.0.1:5672//
          DB_ENGINE: postgresql
          DB_HOST: 127.0.0.1
          DB_NAME: test_db
          DB_USER: test
          DB_PASSWORD: test
          DB_PORT: 5432
        run: pytest tests/live_broker_smoke_tests.py -v

matrix:
  include:
    - python-version: "3.12"
      django: "5.0"
      db: "postgresql"
    - python-version: "3.12"
      django: "5.1"
      db: "postgresql"
```

```python
pytestmark = pytest.mark.live_broker_smoke


@pytest.mark.django_db(transaction=True)
def test_live_broker_smoke_round_trip() -> None:
    app = OutboxCelery('live-broker')
    app.conf.broker_url = os.environ['CELERY_BROKER_URL']
    app.conf.task_default_queue = 'outbox-smoke'
    app.send_task('smoke.task', task_id='live-broker-1')

    relay = Relay(app=app, config=RelayConfig.init(batch_size=1, idle_time=0, max_retries=1))
    relay._processing()

    with Connection(os.environ['CELERY_BROKER_URL']) as connection:
        queue = connection.SimpleQueue('outbox-smoke')
        message = queue.get(timeout=10)
        try:
            assert message.payload['headers']['id'] == 'live-broker-1'
        finally:
            message.ack()
            queue.close()
```

```toml
[tool.pytest.ini_options]
markers = [
  "release_artifact: tests that validate built wheel and sdist contents",
  "live_broker_smoke: tests that require a live RabbitMQ broker",
]
```

```yaml
- name: Run default test matrix
  run: pytest -m "not release_artifact and not live_broker_smoke" -v

- name: Run bleeding-edge suite
  run: pytest -m "not release_artifact and not live_broker_smoke" -v
```

```yaml
services:
  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    healthcheck:
      test: ['CMD', 'rabbitmq-diagnostics', 'check_running']
      interval: 5s
      timeout: 5s
      retries: 10
```

- [ ] **Step 4: Re-run support-policy checks and the local live-broker smoke**

Run:

```bash
docker compose up -d postgres rabbitmq --wait
docker compose run --rm -e CELERY_BROKER_URL=amqp://guest:guest@rabbitmq:5672// app python -m pytest tests/release_contract_tests.py -k "ci_lane or support_claim" -v
docker compose run --rm -e CELERY_BROKER_URL=amqp://guest:guest@rabbitmq:5672// app python -m pytest tests/live_broker_smoke_tests.py -v
docker compose down -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/tests.yml pyproject.toml README.md docker-compose.yml tests/release_contract_tests.py tests/live_broker_smoke_tests.py
git commit -m "ci: align compatibility claims with explicit test coverage"
```

### Task 4: Pin Release-Critical Workflows To SHAs

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `.github/workflows/publish.yml`
- Modify: `.github/workflows/docs.yml`
- Modify: `.github/workflows/example.yml`

- [ ] **Step 1: Add a failing workflow-audit check**

```bash
rg -n 'uses: .+@v[0-9]+' .github/workflows
```

- [ ] **Step 2: Run the workflow audit**

Run:

```bash
docker compose run --rm app bash -lc "python - <<'PY'\nfrom pathlib import Path\nimport re\nfor path in Path('.github/workflows').glob('*.yml'):\n    text = path.read_text()\n    for line in text.splitlines():\n        if 'uses:' in line and '@' in line and re.search(r'@[0-9a-f]{40}$', line.strip()) is None:\n            print(f'{path}: {line.strip()}')\nPY"
```

Expected: current workflows still use moving tags.

- [ ] **Step 3: Replace moving tags with SHAs and comments**

```yaml
- uses: actions/checkout@<sha> # v4
```

- [ ] **Step 4: Re-run the workflow audit**

Run:

```bash
docker compose run --rm app bash -lc "python - <<'PY'\nfrom pathlib import Path\nimport re\nbad = []\nfor path in Path('.github/workflows').glob('*.yml'):\n    text = path.read_text()\n    for line in text.splitlines():\n        if 'uses:' in line and '@' in line and re.search(r'@[0-9a-f]{40}$', line.strip()) is None:\n            bad.append((path, line.strip()))\nprint(bad)\nraise SystemExit(1 if bad else 0)\nPY"
```

Expected: no moving-tag matches remain in release-critical workflows.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/tests.yml .github/workflows/publish.yml .github/workflows/docs.yml .github/workflows/example.yml
git commit -m "ci: pin release critical github actions to shas"
```

### Task 5: Final Release-Gate Verification

**Files:**
- Verify only

- [ ] **Step 1: Run the full local release contract suite**

Run:

```bash
docker compose run --rm app bash -lc "python -m pip install -q build && python -m build && tar -tf dist/*.tar.gz | sed -n '1,40p' && python -m pytest tests/release_artifact_tests.py tests/release_contract_tests.py -v"
```

Expected: PASS.

- [ ] **Step 2: Commit the verification checkpoint**

```bash
git commit --allow-empty -m "chore: verify release integrity plan"
```
