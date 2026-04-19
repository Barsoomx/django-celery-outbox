import importlib
import importlib.util
import inspect
from collections.abc import Callable
from datetime import timedelta
from typing import cast

from celery import Celery
from django.conf import settings
from django.utils.module_loading import import_string


def load_celery_app_setting() -> Celery:
    app_path = getattr(settings, 'CELERY_OUTBOX_APP', None)
    if app_path in (None, ''):
        raise ValueError(
            'CELERY_OUTBOX_APP setting is required. Set it to the dotted path of your Celery app instance, e.g. "myproject.celery_app.app".'
        )
    if not isinstance(app_path, str):
        raise ValueError(f'CELERY_OUTBOX_APP must be a dotted path string, got {type(app_path).__name__}.')

    path_parts = app_path.split('.')
    if len(path_parts) < 2 or any(not part for part in path_parts):
        raise ValueError(f'CELERY_OUTBOX_APP must be a dotted path (e.g. "myproject.celery_app.app"), got: "{app_path}"')

    module_path, attr_name = app_path.rsplit('.', 1)

    try:
        module_spec = importlib.util.find_spec(module_path)
    except ModuleNotFoundError as exc:
        if (exc.name and module_path.startswith(f'{exc.name}.')) or exc.name == module_path:
            raise ValueError(f'CELERY_OUTBOX_APP module could not be imported: "{module_path}".') from exc
        raise ValueError(f'CELERY_OUTBOX_APP "{app_path}" could not be loaded because resolving module "{module_path}" failed: {exc}') from exc

    if module_spec is None:
        raise ValueError(f'CELERY_OUTBOX_APP module could not be imported: "{module_path}".')

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ValueError(f'CELERY_OUTBOX_APP "{app_path}" could not be loaded because importing module "{module_path}" failed: {exc}') from exc

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


def load_pii_redactor_setting() -> Callable[[str, list, dict], tuple[list, dict]] | None:
    value = getattr(settings, 'CELERY_OUTBOX_PII_REDACTOR', None)
    if value is None:
        return None

    if isinstance(value, str):
        value = import_string(value)

    if not callable(value):
        raise TypeError('CELERY_OUTBOX_PII_REDACTOR must be a callable or dotted path.')

    try:
        inspect.signature(value).bind('', [], {})
    except TypeError as exc:
        raise TypeError('CELERY_OUTBOX_PII_REDACTOR must accept (task_name, args, kwargs).') from exc

    return cast(Callable[[str, list, dict], tuple[list, dict]], value)


def load_dlq_retention_setting() -> dict[str, timedelta | str | None] | None:
    from django_celery_outbox.purge import parse_duration

    retention = getattr(settings, 'CELERY_OUTBOX_DLQ_RETENTION', None)
    if retention is None:
        return None

    if not isinstance(retention, dict):
        raise TypeError('CELERY_OUTBOX_DLQ_RETENTION must be a dict.')

    if not retention.get('older_than_dead') and not retention.get('older_than_created'):
        raise ValueError('CELERY_OUTBOX_DLQ_RETENTION must specify older_than_dead or older_than_created')

    older_than_dead = parse_duration(retention['older_than_dead']) if retention.get('older_than_dead') else None
    older_than_created = parse_duration(retention['older_than_created']) if retention.get('older_than_created') else None

    return {
        'older_than_dead': older_than_dead,
        'older_than_created': older_than_created,
        'task_name_pattern': retention.get('task_name'),
    }


def load_stale_timeout_seconds_setting(default: int = 300) -> int:
    value = getattr(settings, 'CELERY_OUTBOX_STALE_TIMEOUT_SECONDS', default)
    try:
        stale_timeout_seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('CELERY_OUTBOX_STALE_TIMEOUT_SECONDS must be an integer.') from exc

    if stale_timeout_seconds <= 0:
        raise ValueError('CELERY_OUTBOX_STALE_TIMEOUT_SECONDS must be > 0.')

    return stale_timeout_seconds


def get_outbox_db_alias() -> str:
    from django_celery_outbox.models import CeleryOutbox

    return CeleryOutbox.objects.db
