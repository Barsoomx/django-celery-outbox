import importlib
import importlib.util

from celery import Celery
from django.conf import settings


def load_celery_app_setting() -> Celery:
    app_path = getattr(settings, 'CELERY_OUTBOX_APP', None)
    if not isinstance(app_path, str):
        if app_path is None:
            raise ValueError(
                'CELERY_OUTBOX_APP setting is required. Set it to the dotted path of your Celery app instance, e.g. "myproject.celery_app.app".'
            )
        raise ValueError(f'CELERY_OUTBOX_APP must be a dotted path string, got {type(app_path).__name__}.')

    path_parts = app_path.split('.')
    if len(path_parts) < 2 or any(not part for part in path_parts):
        raise ValueError(f'CELERY_OUTBOX_APP must be a dotted path (e.g. "myproject.celery_app.app"), got: "{app_path}"')

    module_path, attr_name = app_path.rsplit('.', 1)

    try:
        module_spec = importlib.util.find_spec(module_path)
    except ModuleNotFoundError as exc:
        if exc.name and module_path.startswith(f'{exc.name}.') or exc.name == module_path:
            raise ValueError(f'CELERY_OUTBOX_APP module could not be imported: "{module_path}".') from exc
        raise

    if module_spec is None:
        raise ValueError(f'CELERY_OUTBOX_APP module could not be imported: "{module_path}".')

    module = importlib.import_module(module_path)

    try:
        app = getattr(module, attr_name)
    except AttributeError as exc:
        raise ValueError(f'CELERY_OUTBOX_APP attribute "{attr_name}" was not found in "{module_path}".') from exc

    if not isinstance(app, Celery):
        raise ValueError(f'CELERY_OUTBOX_APP must point to a Celery instance, got {type(app).__name__}.')

    return app


def get_exclude_tasks_setting() -> set[str]:
    value = getattr(settings, 'CELERY_OUTBOX_EXCLUDE_TASKS', ())
    if isinstance(value, (str, bytes)) or not isinstance(value, (set, frozenset, list, tuple)):
        raise TypeError('CELERY_OUTBOX_EXCLUDE_TASKS must be a set, frozenset, list, or tuple of strings.')

    invalid_members = [item for item in value if not isinstance(item, str)]
    if invalid_members:
        raise TypeError('CELERY_OUTBOX_EXCLUDE_TASKS must contain only strings.')

    return set(value)


def get_outbox_db_alias() -> str:
    from django_celery_outbox.models import CeleryOutbox

    return CeleryOutbox.objects.db
