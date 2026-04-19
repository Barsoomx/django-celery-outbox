import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_artifact


def test_built_wheel_excludes_internal_test_modules(tmp_path: Path) -> None:
    dist_dir = tmp_path / 'dist'
    subprocess.run([sys.executable, '-m', 'build', '--outdir', str(dist_dir)], check=True)  # noqa: S603

    wheel_path = next(dist_dir.glob('django_celery_outbox-*.whl'))
    with zipfile.ZipFile(wheel_path) as archive:
        wheel_names = archive.namelist()

    assert not any(name.startswith('django_celery_outbox/') and name.endswith('_tests.py') for name in wheel_names)

    sdist_path = next(dist_dir.glob('django_celery_outbox-*.tar.gz'))
    with tarfile.open(sdist_path) as archive:
        sdist_names = archive.getnames()

    assert not any('django_celery_outbox/' in name and name.endswith('_tests.py') for name in sdist_names)
