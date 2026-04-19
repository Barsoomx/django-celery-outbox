# Public Testing Surface And Example Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the internal support seam behind the shipped pytest fixtures, narrow source-tree contract test patching, and make the example project validate the built package artifact on contract-relevant changes.

**Architecture:** Add one small package-owned support module behind `fixtures.py`, keep the public downstream API as the fixtures themselves, and separate fast contract tests from live-broker release validation. Wire example CI to package-contract changes and make it install the built artifact from CI rather than the unbuilt source tree.

**Tech Stack:** pytest plugin entry points, Django/Celery fixture helpers, GitHub Actions YAML, docker compose

---

### Task 1: Extract A Stable Fixture Support Module

**Files:**
- Add: `django_celery_outbox/_fixture_support.py`
- Modify: `django_celery_outbox/fixtures.py`
- Modify: `django_celery_outbox/fixtures_tests.py`
- Modify: `django_celery_outbox/fixtures_plugin_tests.py`

- [ ] **Step 1: Add failing fixture-support tests**

```python
def test_fake_relay_uses_fixture_support_patch_target(mocker) -> None:
    helper = mocker.patch('django_celery_outbox.fixtures.patch_fake_relay_send_task')
    generator = fixtures_module.fake_relay.__wrapped__()

    next(generator)

    helper.assert_called_once()
    with pytest.raises(StopIteration):
        next(generator)


def test_drain_outbox_uses_fixture_support_run_once(mocker) -> None:
    helper = mocker.patch('django_celery_outbox.fixtures.run_drain_outbox_once')
    drain_outbox = fixtures_module.drain_outbox_fixture.__wrapped__(outbox=CeleryOutbox)

    with patch.object(CeleryOutbox.objects, 'count', side_effect=[1, 0]):
        drain_outbox()

    helper.assert_called_once()
```

- [ ] **Step 2: Run fixture tests**

Run:

```bash
docker compose run --rm app python -m pytest django_celery_outbox/fixtures_tests.py django_celery_outbox/fixtures_plugin_tests.py -v
```

Expected: FAIL once the tests assert the new support seam because `fixtures.py` still imports private internals directly.

- [ ] **Step 3: Implement the support module and switch fixtures**

```python
def load_fixture_celery_app() -> Celery:
    return load_celery_app_setting()


def patch_fake_relay_send_task(recorder: FakeRelayRecorder) -> ContextManager[Any]:
    return patch("django_celery_outbox.relay._publisher.Celery.send_task", side_effect=_record)


def run_drain_outbox_once(app: Celery, *, idle_time: float = 0.0) -> None:
    relay = Relay(app=app, config=RelayConfig.init(idle_time=idle_time))
    with patch("django_celery_outbox.relay._relay.close_old_connections"):
        with patch("django_celery_outbox.relay._relay.time.sleep"):
            relay._processing()
```

- [ ] **Step 4: Re-run fixture tests**

Run:

```bash
docker compose run --rm app python -m pytest django_celery_outbox/fixtures_tests.py django_celery_outbox/fixtures_plugin_tests.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/_fixture_support.py django_celery_outbox/fixtures.py django_celery_outbox/fixtures_tests.py django_celery_outbox/fixtures_plugin_tests.py
git commit -m "feat: stabilize pytest fixture support boundary"
```

### Task 2: Narrow Source-Tree Contract Test Patching

**Files:**
- Modify: `django_celery_outbox/integration_tests.py`
- Modify: `docs/usage/testing-with-pytest.md`

- [ ] **Step 1: Add failing tests or assertions around global patch usage**

```python
def test_contract_tests_do_not_patch_close_old_connections_globally() -> None:
    source = Path('django_celery_outbox/integration_tests.py').read_text(encoding='utf-8')

    assert 'def m_close_old_connections' not in source
    assert "patch('django_celery_outbox.relay._relay.close_old_connections')" in source
```

- [ ] **Step 2: Run the focused contract-test checks**

Run:

```bash
docker compose run --rm app python -m pytest django_celery_outbox/integration_tests.py -k "close_old_connections or contract" -v
```

Expected: FAIL because current tests still patch too broadly.

- [ ] **Step 3: Narrow patch scope and rename/document tests honestly**

```python
# remove the file-level autouse fixture that patched every integration test
with mock.patch("django_celery_outbox.relay._relay.close_old_connections"):
    f_relay._processing()
```

- [ ] **Step 4: Re-run the focused contract-test checks**

Run:

```bash
docker compose run --rm app python -m pytest django_celery_outbox/integration_tests.py -k "close_old_connections or contract" -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/integration_tests.py docs/usage/testing-with-pytest.md
git commit -m "test: narrow connection recycling patches in contract tests"
```

### Task 3: Make Example CI Install The Built Artifact On Contract Changes

**Files:**
- Modify: `.github/workflows/example.yml`
- Modify: `examples/minimal_django/docker-compose.yml`
- Modify: `examples/minimal_django/README.md`

- [ ] **Step 1: Add failing workflow and example-run assertions**

```python
def test_example_workflow_uses_built_artifact() -> None:
    workflow = Path('.github/workflows/example.yml').read_text(encoding='utf-8')
    compose = Path('examples/minimal_django/docker-compose.yml').read_text(encoding='utf-8')

    assert 'django_celery_outbox/**' in workflow
    assert 'MANIFEST.in' in workflow
    assert 'Dockerfile' in workflow
    assert 'python -m build' in workflow
    assert 'pip install /package/dist/*.whl' in compose
    assert 'cp -r /package /tmp/package && pip install /tmp/package' not in compose
```

- [ ] **Step 2: Run local built-artifact example verification**

Run:

```bash
docker compose run --rm app bash -lc "python -m pip install -q build && python -m build"
docker compose -f examples/minimal_django/docker-compose.yml up -d --build --wait --wait-timeout 180
docker compose -f examples/minimal_django/docker-compose.yml exec -T app python - <<'PY'
import importlib.metadata as metadata
import json

data = json.loads(metadata.distribution('django-celery-outbox').read_text('direct_url.json'))
print(data['url'])
assert data['url'].endswith('.whl'), data
PY
```

Expected: FAIL because the example still installs from a copied source tree, so `direct_url.json` points at `/tmp/package` instead of a wheel artifact.

- [ ] **Step 3: Update workflow triggers and install the built wheel in example services**

```yaml
paths:
  - "django_celery_outbox/**"
  - "pyproject.toml"
  - "MANIFEST.in"
  - "Dockerfile"
  - ".github/workflows/example.yml"
  - "examples/**"
```

```yaml
- name: Build package artifact
  run: python -m pip install -q build && python -m build
```

```yaml
command: >
  sh -c "pip install /package/dist/*.whl &&
         python manage.py migrate &&
         python manage.py runserver 0.0.0.0:8000"
```

- [ ] **Step 4: Re-run built-artifact example verification**

Run:

```bash
docker compose run --rm app bash -lc "python -m pip install -q build && python -m build"
docker compose -f examples/minimal_django/docker-compose.yml up -d --build --wait --wait-timeout 180
docker compose -f examples/minimal_django/docker-compose.yml exec -T app python - <<'PY'
import importlib.metadata as metadata
import json

data = json.loads(metadata.distribution('django-celery-outbox').read_text('direct_url.json'))
print(data['url'])
assert data['url'].endswith('.whl'), data
PY
docker compose -f examples/minimal_django/docker-compose.yml down -v
```

Expected: PASS, with `direct_url.json` resolving to a wheel file under `/package/dist/` rather than a copied source tree.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/example.yml examples/minimal_django/docker-compose.yml examples/minimal_django/README.md
git commit -m "ci: run example project against built artifact on contract changes"
```
