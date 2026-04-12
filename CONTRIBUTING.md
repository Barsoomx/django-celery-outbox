Contributing
============

Thanks for your interest in contributing!

Local development
-----------------

**With Docker (recommended):**

```bash
git clone https://github.com/Barsoomx/django-celery-outbox.git
cd django-celery-outbox
docker compose build
docker compose run --rm app pytest -v
docker compose run --rm app ruff check .
docker compose run --rm app mypy -p django_celery_outbox
```

**Without Docker:**

- Create a virtual environment: `python3 -m venv .venv && source .venv/bin/activate`
- Install dev tools: `pip install -U pip && pip install .[dev]`
- Run linters: `ruff check . && ruff format --check .`
- Run type checks: `mypy django_celery_outbox`

Pre-commit
----------
Install Git hooks to catch issues before CI:

```
pip install pre-commit
pre-commit install
```

Release process
---------------
- Update `django_celery_outbox/__init__.py` version and `CHANGELOG.md`.
- Ensure CI is green on master.
- Create a tag `vX.Y.Z` and push. GitHub Actions will build and publish to PyPI via trusted publishing.

Code of Conduct
---------------
Be respectful and kind; follow the Golden Rule. Reports of abusive behavior may result in removal from participation.
