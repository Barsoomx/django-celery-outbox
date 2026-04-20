from datetime import timedelta

from django.db.models import Q
from django.db.models.functions import Now

from django_celery_outbox.serialization import CURRENT_SCHEMA_VERSION, MIN_SUPPORTED_VERSION

_DEFAULT_STALE_TIMEOUT = timedelta(minutes=5)


def get_pending_filter(stale_timeout: timedelta = _DEFAULT_STALE_TIMEOUT) -> Q:
    return (Q(updated_at__isnull=True) | Q(retry_after__lte=Now()) | Q(updated_at__lte=Now() - stale_timeout, retry_after__isnull=True)) & Q(
        schema_version__gte=MIN_SUPPORTED_VERSION,
        schema_version__lte=CURRENT_SCHEMA_VERSION,
    )
