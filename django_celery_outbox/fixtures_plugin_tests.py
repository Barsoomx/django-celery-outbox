from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_build_project_wheel_uses_pip_wheel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wheel_dir = tmp_path / 'wheelhouse'
    captured: dict[str, Any] = {}

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured['args'] = args
        captured['kwargs'] = kwargs

        wheel_dir.mkdir(exist_ok=True)
        (wheel_dir / 'django_celery_outbox-0.3.0-py3-none-any.whl').write_text('', encoding='utf-8')

        return subprocess.CompletedProcess(args[0], 0, stdout='', stderr='')

    monkeypatch.setattr(subprocess, 'run', fake_run)

    _build_project_wheel(wheel_dir, source_root=REPO_ROOT)

    assert captured['args'] == (
        [
            sys.executable,
            '-m',
            'pip',
            'wheel',
            '--no-deps',
            '--wheel-dir',
            str(wheel_dir),
            str(REPO_ROOT),
        ],
    )
    assert captured['kwargs'] == {
        'cwd': REPO_ROOT,
        'capture_output': True,
        'text': True,
        'check': False,
    }


def _prepare_wheel_source(target_dir: Path) -> Path:
    shutil.copytree(
        REPO_ROOT,
        target_dir,
        ignore=shutil.ignore_patterns(
            '.git',
            '.mypy_cache',
            '.pytest_cache',
            '.ruff_cache',
            '.venv',
            '.venv-wsl',
            '__pycache__',
            'build',
            'dist',
            '*.egg-info',
        ),
    )
    return target_dir


def _build_project_wheel(wheel_dir: Path, *, source_root: Path | None = None) -> Path:
    wheel_dir.mkdir(parents=True, exist_ok=True)
    build_source_root = source_root or _prepare_wheel_source(wheel_dir.parent / 'source')

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            '-m',
            'pip',
            'wheel',
            '--no-deps',
            '--wheel-dir',
            str(wheel_dir),
            str(build_source_root),
        ],
        cwd=build_source_root,
        capture_output=True,
        text=True,
        check=False,
    )

    combined_output = result.stdout + result.stderr

    assert result.returncode == 0, combined_output

    wheel_paths = list(wheel_dir.glob('django_celery_outbox-*.whl'))

    assert len(wheel_paths) == 1, combined_output

    return wheel_paths[0]


def _prepend_pythonpath(path: Path, env: dict[str, str]) -> dict[str, str]:
    updated_env = dict(env)
    existing_pythonpath = updated_env.get('PYTHONPATH')

    updated_env['PYTHONPATH'] = f'{path}{os.pathsep}{existing_pythonpath}' if existing_pythonpath else str(path)

    return updated_env


def test_pytest11_entry_point_registered(tmp_path: Path) -> None:
    wheel_path = _build_project_wheel(tmp_path / 'wheelhouse')

    env = _prepend_pythonpath(wheel_path, dict(os.environ))
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            '-c',
            (
                'from importlib.metadata import distribution\n'
                'dist = distribution("django-celery-outbox")\n'
                'entry_points = {\n'
                '    entry_point.name: entry_point.value\n'
                '    for entry_point in dist.entry_points\n'
                '    if entry_point.group == "pytest11"\n'
                '}\n'
                'print(entry_points.get("django_celery_outbox", ""))\n'
            ),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == 'django_celery_outbox.fixtures'


def test_pytest_autoloads_plugin_without_django_setup(tmp_path: Path) -> None:
    wheel_path = _build_project_wheel(tmp_path / 'wheelhouse')
    pytest_ini = tmp_path / 'pytest.ini'
    pytest_ini.write_text('[pytest]\n', encoding='utf-8')

    test_file = tmp_path / 'test_smoke.py'
    test_file.write_text(
        'def test_placeholder():\n    assert True\n',
        encoding='utf-8',
    )

    env = dict(os.environ)
    env.pop('DJANGO_SETTINGS_MODULE', None)
    env.pop('PYTEST_DISABLE_PLUGIN_AUTOLOAD', None)
    env = _prepend_pythonpath(wheel_path, env)

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            '-m',
            'pytest',
            '--trace-config',
            '-c',
            str(pytest_ini),
            str(test_file),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    combined_output = result.stdout + result.stderr

    assert result.returncode == 0, combined_output
    assert 'django_celery_outbox.fixtures' in combined_output


def test_outbox_fixture_cleans_between_tests(tmp_path: Path) -> None:
    source_root = _prepare_wheel_source(tmp_path / 'source')
    wheel_path = _build_project_wheel(tmp_path / 'wheelhouse', source_root=source_root)
    pytest_ini = tmp_path / 'pytest.ini'
    pytest_ini.write_text('[pytest]\n', encoding='utf-8')

    test_file = tmp_path / 'test_cleanup.py'
    test_file.write_text(
        'from django_celery_outbox.models import CeleryOutbox\n'
        '\n'
        '\n'
        'def test_first(outbox):\n'
        "    CeleryOutbox.objects.create(task_id='task-1', task_name='demo.task')\n"
        '    assert outbox.objects.count() == 1\n'
        '\n'
        '\n'
        'def test_second(outbox):\n'
        '    assert outbox.objects.count() == 0\n',
        encoding='utf-8',
    )

    env = dict(os.environ)
    env['DB_ENGINE'] = 'sqlite'
    env['DJANGO_SETTINGS_MODULE'] = 'tests.settings'
    env.pop('PYTEST_DISABLE_PLUGIN_AUTOLOAD', None)
    env = _prepend_pythonpath(source_root, env)
    env = _prepend_pythonpath(wheel_path, env)

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            '-m',
            'pytest',
            '-c',
            str(pytest_ini),
            str(test_file),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_example_workflow_uses_built_artifact() -> None:
    workflow = Path('.github/workflows/example.yml').read_text(encoding='utf-8')
    compose = Path('examples/minimal_django/docker-compose.yml').read_text(encoding='utf-8')
    readme = Path('examples/minimal_django/README.md').read_text(encoding='utf-8')

    assert 'django_celery_outbox/**' in workflow
    assert 'pyproject.toml' in workflow
    assert 'MANIFEST.in' in workflow
    assert 'setup.py' in workflow
    assert 'Dockerfile' in workflow
    assert 'rm -rf dist/example' in workflow
    assert 'python -m build --outdir dist/example' in workflow
    assert '/package/dist/example/django_celery_outbox-*.whl' in compose
    assert 'Expected exactly one built wheel' in compose
    assert 'cp -r /package /tmp/package && pip install /tmp/package' not in compose
    assert 'python -m build --outdir dist/example' in readme
    assert 'docker compose -f examples/minimal_django/docker-compose.yml up -d' in readme
