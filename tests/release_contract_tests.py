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


def test_release_workflows_include_contract_and_live_broker_gates() -> None:
    publish_workflow = Path('.github/workflows/publish.yml').read_text(encoding='utf-8')
    tests_workflow = Path('.github/workflows/tests.yml').read_text(encoding='utf-8')
    docker_compose = Path('docker-compose.yml').read_text(encoding='utf-8')
    pyproject = Path('pyproject.toml').read_text(encoding='utf-8')

    assert 'artifact_smoke:' in publish_workflow
    assert 'release_contract:' in publish_workflow
    assert 'needs: [artifact_smoke, live_broker_smoke]' in publish_workflow
    assert 'needs: [release_contract]' in publish_workflow or 'needs:\n    - release_contract' in publish_workflow
    assert publish_workflow.count('python -m build') == 1
    assert 'actions/download-artifact@' in publish_workflow
    assert 'artifact-smoke-dist' in publish_workflow
    assert "entry_points(group='pytest11')" in publish_workflow

    assert 'live_broker_smoke:' in tests_workflow
    assert 'rabbitmq:' in tests_workflow
    assert 'tests/live_broker_smoke_tests.py' in tests_workflow
    assert "django: '5.0'" in tests_workflow or 'django: "5.0"' in tests_workflow
    assert "django: '5.1'" in tests_workflow or 'django: "5.1"' in tests_workflow
    assert 'pytest -m "not release_artifact and not live_broker_smoke" -v' in tests_workflow

    assert 'rabbitmq:' in docker_compose
    assert 'rabbitmq:\n        condition: service_healthy' in docker_compose

    assert 'Framework :: Django :: 5.0' in pyproject
    assert 'Framework :: Django :: 5.1' in pyproject


def test_release_workflows_use_pinned_actions() -> None:
    workflow_dir = Path('.github/workflows')
    offenders: list[str] = []

    for path in (
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
