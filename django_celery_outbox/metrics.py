from django.conf import settings

from django_celery_outbox.statsd import get_statsd


def _is_enabled() -> bool:
    return getattr(settings, 'MONITORING_METRICS_ENABLED', True)


def _to_tags(tags: dict[str, str] | None) -> list[str] | None:
    if not tags:
        return None

    return [f'{k}:{v}' for k, v in tags.items()]


def increment(name: str, value: int = 1, tags: dict[str, str] | None = None) -> None:
    if not _is_enabled():
        return

    get_statsd().increment(name, value=value, tags=_to_tags(tags))


def gauge(name: str, value: int | float, tags: dict[str, str] | None = None) -> None:
    if not _is_enabled():
        return

    get_statsd().gauge(name, value=value, tags=_to_tags(tags))


def timing(name: str, value_ms: float, tags: dict[str, str] | None = None) -> None:
    if not _is_enabled():
        return

    get_statsd().timing(name, value=value_ms, tags=_to_tags(tags))
