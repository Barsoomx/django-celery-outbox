from django.test import override_settings

from django_celery_outbox.relay._runtime import (
    ProcessResult,
    classify_exception,
    should_log_traceback,
)


def test_process_result_enum_members() -> None:
    assert ProcessResult.PUBLISHED.name == 'PUBLISHED'
    assert ProcessResult.FAILED.name == 'FAILED'
    assert ProcessResult.EXCEEDED.name == 'EXCEEDED'


def test_classify_exception_connection_error() -> None:
    exc = ConnectionError('broker down')
    assert classify_exception(exc) == 'connection'


def test_classify_exception_timeout_error() -> None:
    exc = TimeoutError('timed out')
    assert classify_exception(exc) == 'timeout'


def test_classify_exception_os_error() -> None:
    exc = OSError('system error')
    assert classify_exception(exc) == 'os_error'


def test_classify_exception_unknown() -> None:
    exc = ValueError('some value error')
    assert classify_exception(exc) == 'unknown'


def test_classify_exception_subclass() -> None:
    exc = BrokenPipeError('pipe broken')
    assert classify_exception(exc) == 'connection'


@override_settings(CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK=True)
def test_should_log_traceback_defaults_to_true() -> None:
    assert should_log_traceback() is True


@override_settings(CELERY_OUTBOX_LOG_EXCEPTION_TRACEBACK=False)
def test_should_log_traceback_honors_setting() -> None:
    assert should_log_traceback() is False
