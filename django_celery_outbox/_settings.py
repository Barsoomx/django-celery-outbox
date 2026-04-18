import importlib

from celery import Celery
from django.conf import settings

from django_celery_outbox.models import CeleryOutbox


def load_celery_app_setting() -> Celery:
    app_path = getattr(settings, 'CELERY_OUTBOX_APP', None)
    if not isinstance(app_path, str):
        if app_path is None:
            raise ValueError(
                'CELERY_OUTBOX_APP setting is required. '
                'Set it to the dotted path of your Celery app instance, e.g. '
                '"myproject.celery_app.app".'
            )
        raise ValueError(
            f'CELERY_OUTBOX_APP must be a dotted path string, got {type(app_path).__name__}.'
        )

    path_parts = app_path.split('.')
    if len(path_parts) < 2 or any(not part for part in path_parts):
        raise ValueError(
            f'CELERY_OUTBOX_APP must be a dotted path '
            f'(e.g. "myproject.celery_app.app"), got: "{app_path}"'
        )

    try:
        module_path, attr_name = app_path.rsplit('.', 1)
    except ValueError as exc:
        raise ValueError(
            f'CELERY_OUTBOX_APP must be a dotted path '
            f'(e.g. "myproject.celery_app.app"), got: "{app_path}"'
        ) from exc

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ValueError(
            f'CELERY_OUTBOX_APP module could not be imported: "{module_path}".'
        ) from exc

    try:
        app = getattr(module, attr_name)
    except AttributeError as exc:
        raise ValueError(
            f'CELERY_OUTBOX_APP attribute "{attr_name}" was not found in "{module_path}".'
        ) from exc

    if not isinstance(app, Celery):
        raise ValueError(
            f'CELERY_OUTBOX_APP must point to a Celery instance, got {type(app).__name__}.'
        )

    return app


def get_exclude_tasks_setting() -> set[str]:
    value = getattr(settings, 'CELERY_OUTBOX_EXCLUDE_TASKS', ())
    if isinstance(value, (str, bytes)) or not isinstance(value, (set, frozenset, list, tuple)):
        raise TypeError(
            'CELERY_OUTBOX_EXCLUDE_TASKS must be a set, frozenset, list, or tuple of strings.'
        )

    invalid_members = [item for item in value if not isinstance(item, str)]
    if invalid_members:
        raise TypeError('CELERY_OUTBOX_EXCLUDE_TASKS must contain only strings.')

    return set(value)


def get_outbox_db_alias() -> str:
    return CeleryOutbox.objects.db
