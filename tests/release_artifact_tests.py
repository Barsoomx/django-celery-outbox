import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_artifact


def _find_built_artifact(dist_dir: Path, pattern: str) -> Path:
    matches = sorted(dist_dir.glob(pattern))
    assert matches, f'No built artifacts matching {pattern!r} found in {dist_dir}'
    assert len(matches) == 1, f'Expected exactly one built artifact matching {pattern!r} in {dist_dir}, found {matches}'
    return matches[0]


@pytest.fixture()
def built_release_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    dist_dir = Path('dist')
    wheel_src = _find_built_artifact(dist_dir, 'django_celery_outbox-*.whl')
    sdist_src = _find_built_artifact(dist_dir, 'django_celery_outbox-*.tar.gz')

    artifact_dir = tmp_path / 'artifacts'
    artifact_dir.mkdir()

    wheel_path = artifact_dir / wheel_src.name
    sdist_path = artifact_dir / sdist_src.name
    shutil.copy2(wheel_src, wheel_path)
    shutil.copy2(sdist_src, sdist_path)

    return wheel_path, sdist_path


def test_built_wheel_excludes_internal_test_modules(built_release_artifacts: tuple[Path, Path]) -> None:
    wheel_path, sdist_path = built_release_artifacts
    with zipfile.ZipFile(wheel_path) as archive:
        wheel_names = archive.namelist()

    assert not any(name.startswith('django_celery_outbox/') and name.endswith('_tests.py') for name in wheel_names)

    with tarfile.open(sdist_path) as archive:
        sdist_names = archive.getnames()

    assert not any('django_celery_outbox/' in name and name.endswith('_tests.py') for name in sdist_names)


def test_built_wheel_ignores_stale_build_cache(built_release_artifacts: tuple[Path, Path]) -> None:
    wheel_path, _ = built_release_artifacts
    with zipfile.ZipFile(wheel_path) as archive:
        wheel_names = archive.namelist()

    assert 'django_celery_outbox/stale_cache_tests.py' not in wheel_names
