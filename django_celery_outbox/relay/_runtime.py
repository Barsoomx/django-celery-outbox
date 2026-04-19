from django.conf import settings

_EXCEPTION_CATEGORIES: dict[type[Exception], str] = {
    ConnectionError: 'connection',
    TimeoutError: 'timeout',
    OSError: 'os_error',
}


def classify_exception(exc: Exception) -> str:
    for exc_class, label in _EXCEPTION_CATEGORIES.items():
        if isinstance(exc, exc_class):
            return label

    return 'unknown'


def should_log_traceback() -> bool:
    return getattr(settings, 'CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK', True)
