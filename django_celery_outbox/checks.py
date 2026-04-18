from collections.abc import Collection
import sys
from types import FrameType

from django.conf import settings
from django.core.checks import Error, Tags, register
from django.db import DatabaseError, connections
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

from django_celery_outbox._settings import (
    get_exclude_tasks_setting,
    get_outbox_db_alias,
    load_celery_app_setting,
)

_REQUIRED_OUTBOX_TABLES = frozenset({'celery_outbox', 'celery_outbox_dead_letter'})


def _is_migrate_command() -> bool:
    if 'migrate' in sys.argv[1:]:
        return True

    frame: FrameType | None = sys._getframe()
    while frame is not None:
        filename = frame.f_code.co_filename.replace('\\', '/')
        if filename.endswith('/django/core/management/commands/migrate.py'):
            return True
        frame = frame.f_back

    return False


def _selected_outbox_aliases(databases: object) -> list[str]:
    outbox_alias = get_outbox_db_alias()
    if databases is None:
        return [outbox_alias]
    if isinstance(databases, Collection) and not isinstance(databases, (str, bytes)) and outbox_alias in databases:
        return [outbox_alias]
    return []


@register()
def check_celery_outbox_app_setting(
    app_configs: object,
    **kwargs: object,
) -> list[Error]:
    setting_value = getattr(settings, 'CELERY_OUTBOX_APP', None)
    if setting_value in (None, ''):
        return [
            Error(
                'CELERY_OUTBOX_APP setting is required.',
                hint='Set CELERY_OUTBOX_APP to the dotted path of your Celery app instance.',
                id='celery_outbox.E002',
            )
        ]

    try:
        load_celery_app_setting()
    except ImportError as exc:
        return [
            Error(
                f'Could not import CELERY_OUTBOX_APP {setting_value!r}: {exc}',
                hint='Set CELERY_OUTBOX_APP to the dotted path of your Celery app instance.',
                id='celery_outbox.E003',
            )
        ]
    except ValueError as exc:
        return [
            Error(
                str(exc),
                hint='Set CELERY_OUTBOX_APP to the dotted path of your Celery app instance.',
                id='celery_outbox.E003',
            )
        ]
    except Exception as exc:
        return [
            Error(
                str(exc),
                hint='Set CELERY_OUTBOX_APP to the dotted path of your Celery app instance.',
                id='celery_outbox.E003',
            )
        ]

    return []


@register()
def check_celery_outbox_exclude_tasks_setting(
    app_configs: object,
    **kwargs: object,
) -> list[Error]:
    try:
        get_exclude_tasks_setting()
    except TypeError as exc:
        return [
            Error(
                str(exc),
                hint='Use a set, frozenset, list, or tuple of task-name strings.',
                id='celery_outbox.E004',
            )
        ]

    return []


@register(Tags.database)
def check_database_supports_skip_locked(
    app_configs: object,
    **kwargs: object,
) -> list[Error]:
    errors: list[Error] = []
    for db_alias in _selected_outbox_aliases(kwargs.get('databases')):
        connection = connections[db_alias]
        if not connection.features.has_select_for_update_skip_locked:
            errors.append(
                Error(
                    'Database does not support SELECT FOR UPDATE SKIP LOCKED.',
                    hint='Use PostgreSQL >= 9.5 or MySQL >= 8.0.1 for django-celery-outbox.',
                    id='celery_outbox.E001',
                )
            )

    return errors


@register(Tags.database)
def check_outbox_migrations_applied(
    app_configs: object,
    **kwargs: object,
) -> list[Error]:
    if _is_migrate_command():
        return []

    errors: list[Error] = []

    for db_alias in _selected_outbox_aliases(kwargs.get('databases')):
        connection = connections[db_alias]

        try:
            table_names = set(connection.introspection.table_names())
            if 'django_migrations' not in table_names or not _REQUIRED_OUTBOX_TABLES.issubset(table_names):
                return [
                    Error(
                        f'Could not verify django-celery-outbox schema on database "{db_alias}".',
                        hint='Ensure the configured database is reachable and run `python manage.py migrate`.',
                        id='celery_outbox.E006',
                    )
                ]

            applied = {name for (app_label, name) in MigrationRecorder(connection).applied_migrations() if app_label == 'django_celery_outbox'}
            expected = {
                name
                for (app_label, name) in MigrationLoader(
                    connection,
                    ignore_no_migrations=True,
                ).disk_migrations
                if app_label == 'django_celery_outbox'
            }
        except DatabaseError as exc:
            return [
                Error(
                    f'Could not verify django-celery-outbox schema on database "{db_alias}": {exc}',
                    hint='Ensure the configured database is reachable and run `python manage.py migrate`.',
                    id='celery_outbox.E006',
                )
            ]

        missing = sorted(expected - applied)
        if missing:
            errors.append(
                Error(
                    'django-celery-outbox migrations are not fully applied.',
                    hint='Run `python manage.py migrate` to apply missing django-celery-outbox migrations.',
                    id='celery_outbox.E005',
                )
            )

    return errors
