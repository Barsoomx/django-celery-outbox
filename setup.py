import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class BuildPy(_build_py):
    def run(self) -> None:
        shutil.rmtree(Path(self.build_lib) / 'django_celery_outbox', ignore_errors=True)
        super().run()

    def find_package_modules(self, package: str, package_dir: str) -> list[tuple[str, str, str]]:
        modules = super().find_package_modules(package, package_dir)
        return [module for module in modules if not module[1].endswith('_tests')]


setup(cmdclass={'build_py': BuildPy})
