from __future__ import annotations

import os
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
        (wheel_dir / 'django_celery_outbox-0.2.0-py3-none-any.whl').write_text('', encoding='utf-8')

        return subprocess.CompletedProcess(args[0], 0, stdout='', stderr='')

    monkeypatch.setattr(subprocess, 'run', fake_run)

    _build_project_wheel(wheel_dir)

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


def _build_project_wheel(wheel_dir: Path) -> Path:
    wheel_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(  # noqa: S603
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
        cwd=REPO_ROOT,
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
    result = subprocess.run(
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
