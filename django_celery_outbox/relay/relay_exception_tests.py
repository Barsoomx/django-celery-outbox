from django_celery_outbox.relay._relay import _classify_exception


def test_classify_exception_connection_error() -> None:
    exc = ConnectionError('broker down')
    assert _classify_exception(exc) == 'connection'


def test_classify_exception_timeout_error() -> None:
    exc = TimeoutError('timed out')
    assert _classify_exception(exc) == 'timeout'


def test_classify_exception_os_error() -> None:
    exc = OSError('system error')
    assert _classify_exception(exc) == 'os_error'


def test_classify_exception_unknown() -> None:
    exc = ValueError('some value error')
    assert _classify_exception(exc) == 'unknown'


def test_classify_exception_subclass() -> None:
    exc = BrokenPipeError('pipe broken')
    assert _classify_exception(exc) == 'connection'
