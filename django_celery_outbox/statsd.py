from datadog import DogStatsd
from django.conf import settings

_statsd: DogStatsd | None = None


def get_statsd() -> DogStatsd:
    global _statsd
    if _statsd is None:
        _statsd = DogStatsd(
            host=getattr(settings, 'MONITORING_STATSD_HOST', 'localhost'),
            port=getattr(settings, 'MONITORING_STATSD_PORT', 9125),
            namespace=getattr(settings, 'MONITORING_STATSD_PREFIX', 'celery_outbox'),
            constant_tags=_build_constant_tags(),
        )

    return _statsd


def _build_constant_tags() -> list[str]:
    tags_dict: dict[str, str] = getattr(settings, 'MONITORING_STATSD_TAGS', {})

    return [f'{k}:{v}' for k, v in tags_dict.items()]
