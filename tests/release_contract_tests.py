import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_contract


def test_release_contract_rejects_speculative_markers(tmp_path: Path) -> None:
    changelog = tmp_path / 'CHANGELOG.md'
    changelog.write_text('## 1.0.0\n- WIP finalize release notes\n', encoding='utf-8')

    result = subprocess.run(  # noqa: S603
        [sys.executable, 'scripts/check_release_contract.py', str(changelog)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert 'WIP' in result.stdout + result.stderr


def test_release_contract_rejects_known_ghost_entries(tmp_path: Path) -> None:
    changelog = tmp_path / 'CHANGELOG.md'
    changelog.write_text(
        '## [0.2.0] — 2026-04-13\n- **PII redaction**: Configurable payload scrubbing for sensitive data in logs (`CELERY_OUTBOX_REDACT_FIELDS`)\n',
        encoding='utf-8',
    )

    result = subprocess.run(  # noqa: S603
        [sys.executable, 'scripts/check_release_contract.py', str(changelog)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert 'ghost changelog entry' in result.stdout + result.stderr
    assert 'CELERY_OUTBOX_REDACT_FIELDS' in result.stdout + result.stderr


def test_release_contract_requires_requested_version_section(tmp_path: Path) -> None:
    changelog = tmp_path / 'CHANGELOG.md'
    changelog.write_text('## [Unreleased]\n- Ready to ship\n', encoding='utf-8')

    result = subprocess.run(  # noqa: S603
        [sys.executable, 'scripts/check_release_contract.py', '--version', '1.2.3', str(changelog)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert '1.2.3' in result.stdout + result.stderr


def test_release_contract_requires_real_heading_for_requested_version(tmp_path: Path) -> None:
    changelog = tmp_path / 'CHANGELOG.md'
    changelog.write_text('## [Unreleased]\n\n```md\n## [1.2.3]\n```\n', encoding='utf-8')

    result = subprocess.run(  # noqa: S603
        [sys.executable, 'scripts/check_release_contract.py', '--version', '1.2.3', str(changelog)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert 'missing changelog section for release 1.2.3' in result.stdout + result.stderr


def test_installed_wheel_smoke_script_bootstraps_django_before_command_imports() -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, 'scripts/smoke_installed_wheel.py'],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert 'django_celery_outbox' in result.stdout


def test_installed_wheel_smoke_script_accepts_wheel_origin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    spec = importlib.util.spec_from_file_location('smoke_installed_wheel', Path('scripts/smoke_installed_wheel.py'))
    assert spec is not None
    assert spec.loader is not None
    smoke_script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke_script)
    load_calls: list[str] = []

    class Distribution:
        @staticmethod
        def read_text(name: str) -> str:
            assert name == 'direct_url.json'
            return '{"url": "file:///tmp/django_celery_outbox-0.3.0-py3-none-any.whl"}'

    class EntryPoint:
        name = 'django_celery_outbox'

        @staticmethod
        def load() -> object:
            load_calls.append('django_celery_outbox')
            return object()

    monkeypatch.setattr(smoke_script.metadata, 'distribution', lambda _: Distribution())
    monkeypatch.setattr(
        smoke_script.metadata,
        'entry_points',
        lambda *, group: [EntryPoint()] if group == 'pytest11' else [],
    )

    smoke_script.verify_distribution(expect_wheel_origin=True)

    assert load_calls == ['django_celery_outbox']
    assert 'django_celery_outbox-0.3.0-py3-none-any.whl' in capsys.readouterr().out


def test_installed_wheel_smoke_script_imports_pytest_plugin_and_replay_command() -> None:
    smoke_script = Path('scripts/smoke_installed_wheel.py').read_text(encoding='utf-8')

    assert 'import django_celery_outbox.fixtures' in smoke_script
    assert 'import django_celery_outbox.management.commands.celery_outbox_replay_dead_letter' in smoke_script


def test_release_workflows_include_contract_and_live_broker_gates() -> None:
    publish_workflow = Path('.github/workflows/publish.yml').read_text(encoding='utf-8')
    tests_workflow = Path('.github/workflows/tests.yml').read_text(encoding='utf-8')
    example_workflow = Path('.github/workflows/example.yml').read_text(encoding='utf-8')
    docker_compose = Path('docker-compose.yml').read_text(encoding='utf-8')
    pyproject = Path('pyproject.toml').read_text(encoding='utf-8')
    smoke_script = Path('scripts/smoke_installed_wheel.py').read_text(encoding='utf-8')

    assert 'artifact_smoke:' in publish_workflow
    assert 'release_contract:' in publish_workflow
    assert 'parallel_broker_smoke:' in publish_workflow
    assert 'needs: [artifact_smoke, live_broker_smoke, parallel_broker_smoke]' in publish_workflow
    assert 'needs: [release_contract]' in publish_workflow or 'needs:\n    - release_contract' in publish_workflow
    assert publish_workflow.count('python -Im build') == 1
    assert 'actions/download-artifact@' in publish_workflow
    assert 'artifact-smoke-dist' in publish_workflow
    assert 'smoke_installed_wheel.py' in publish_workflow
    assert '--expect-wheel-origin' in publish_workflow
    assert '--version "${GITHUB_REF_NAME#v}" CHANGELOG.md' in publish_workflow
    assert "metadata.entry_points(group='pytest11')" in smoke_script
    assert '.load()' in smoke_script

    assert 'live_broker_smoke:' in tests_workflow
    assert 'parallel_broker_smoke:' in tests_workflow
    assert 'rabbitmq:' in tests_workflow
    assert 'tests/live_broker_smoke_tests.py' in tests_workflow
    assert 'tests/parallel_broker_smoke_tests.py' in tests_workflow
    assert "django: '5.0'" in tests_workflow or 'django: "5.0"' in tests_workflow
    assert "django: '5.1'" in tests_workflow or 'django: "5.1"' in tests_workflow
    assert 'Run Django compatibility smoke tests' in tests_workflow
    assert 'pytest -m "not release_artifact and not live_broker_smoke" -v' in tests_workflow

    assert 'name: Test Example Project' in example_workflow
    assert 'push:\n    branches:\n      - master' in example_workflow
    assert 'pull_request:' in example_workflow
    assert 'paths:' not in example_workflow
    assert 'Create order' in example_workflow
    assert 'Verify outbox processed' in example_workflow

    assert 'rabbitmq:' in docker_compose
    assert 'rabbitmq:\n        condition: service_healthy' in docker_compose

    assert 'Framework :: Django :: 5.0' in pyproject
    assert 'Framework :: Django :: 5.1' in pyproject


def test_architecture_docs_explicitly_mark_signal_payload_shape() -> None:
    architecture = Path('docs/architecture.md').read_text(encoding='utf-8')

    assert '| Signal | Sender | Shape | Kwargs |' in architecture
    assert '| `outbox_message_created` | `OutboxCelery` | scalar | `task_id`, `task_name` |' in architecture
    assert '| `outbox_message_sent` | `Relay` | scalar | `task_id`, `task_name` |' in architecture
    assert '| `outbox_message_failed` | `Relay` | scalar | `task_id`, `task_name`, `retries` |' in architecture
    assert '| `outbox_message_dead_lettered` | `Relay` | batched | `task_ids`, `task_names` |' in architecture


def test_logging_events_docs_include_relay_iteration_failed_alert_snippet() -> None:
    logging_events = Path('docs/observability/logging-events.md').read_text(encoding='utf-8')

    assert 'celery_outbox_relay_iteration_failed' in logging_events
    assert 'LogQL' in logging_events
    assert '{app="relay"} |= "celery_outbox_relay_iteration_failed"' in logging_events


def test_relay_index_explain_note_records_non_empty_table_evidence() -> None:
    note = Path('docs/superpowers/plans/notes/2026-04-19-relay-index-explain.txt').read_text(encoding='utf-8')

    assert 'BitmapOr' in note
    assert 'index_merge' in note
    assert 'rows=1 width=2298' not in note
    assert 'dead_at, id' in note
    assert 'created_at, id' in note


def test_packaged_alert_rules_only_include_package_owned_alerts() -> None:
    alert_rules = Path('docs/observability/alert-rules.yml').read_text(encoding='utf-8')

    assert 'CeleryOutboxQueueAgeHigh' in alert_rules
    assert 'CeleryOutboxNewDeadLetters' in alert_rules
    assert 'CeleryOutboxQueueBacklog' not in alert_rules
    assert 'CeleryOutboxHighFailureRate' not in alert_rules


def test_release_workflows_use_pinned_actions() -> None:
    workflow_dir = Path('.github/workflows')
    offenders: list[str] = []

    for path in (
        workflow_dir / 'codeql.yml',
        workflow_dir / 'stale.yml',
        workflow_dir / 'publish.yml',
        workflow_dir / 'tests.yml',
        workflow_dir / 'docs.yml',
        workflow_dir / 'example.yml',
    ):
        text = path.read_text(encoding='utf-8')
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('uses:') and '@' in stripped:
                if '@' not in stripped or not stripped.split('@', 1)[1] or stripped.endswith('@'):
                    offenders.append(f'{path}: {stripped}')
                    continue
                ref = stripped.split('@', 1)[1]
                if not (len(ref) == 40 and all(ch in '0123456789abcdef' for ch in ref.lower())):
                    offenders.append(f'{path}: {stripped}')

    assert not offenders, offenders
