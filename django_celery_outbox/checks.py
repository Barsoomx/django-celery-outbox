from django.core.checks import Error, Tags, register
from django.db import connections

from django_celery_outbox.models import CeleryOutbox


@register(Tags.database)
def check_database_supports_skip_locked(
    app_configs: object,
    **kwargs: object,
) -> list[Error]:
    errors: list[Error] = []
    db_alias = CeleryOutbox.objects.db
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
