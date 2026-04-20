import subprocess
import sys
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from celery import Celery
from celery.result import AsyncResult
from django.db import transaction
from django.test import override_settings

from django_celery_outbox.app import OutboxCelery, _redact_options_for_inspection, _send_signal_safe
from django_celery_outbox.models import CeleryOutbox
from django_celery_outbox.signals import outbox_message_created


def sample_redactor(task_name: str, args: list, kwargs: dict) -> tuple[list, dict]:
    return args, dict.fromkeys(kwargs, '[REDACTED]')


def boom(sender: type, **kwargs: object) -> None:
    raise RuntimeError('boom')


def test_send_signal_safe_logs_send_robust_exception_details() -> None:
    signal = MagicMock()
    try:
        raise RuntimeError('boom')
    except RuntimeError as exc:
        response = exc
    signal.send_robust.return_value = [(boom, response)]

    with patch('django_celery_outbox.app._logger') as m_logger:
        _send_signal_safe(
            signal=signal,
            signal_name='outbox_message_created',
            task_id='safe-signal-1',
            task_name='my.task',
        )

    m_logger.error.assert_called_once()
    assert m_logger.error.call_args.args == ('celery_outbox_signal_error',)
    assert m_logger.error.call_args.kwargs['signal'] == 'outbox_message_created'
    assert m_logger.error.call_args.kwargs['task_id'] == 'safe-signal-1'
    assert m_logger.error.call_args.kwargs['task_name'] == 'my.task'
    assert m_logger.error.call_args.kwargs['receiver'] == 'boom'
    assert m_logger.error.call_args.kwargs['exception_type'] == 'RuntimeError'
    assert m_logger.error.call_args.kwargs['exception_message'] == 'boom'

    exc_info = m_logger.error.call_args.kwargs['exc_info']
    assert exc_info[0] is RuntimeError
    assert isinstance(exc_info[1], RuntimeError)
    assert str(exc_info[1]) == 'boom'
    assert exc_info[2] is not None


@pytest.fixture()
def f_app() -> OutboxCelery:
    return OutboxCelery('test')


@pytest.fixture(autouse=True)
def clear_redactor_cache() -> Generator[None, None, None]:
    from django_celery_outbox.app import clear_redactor_cache as clear_cache

    clear_cache()
    yield
    clear_cache()


def test_package_root_import_outbox_celery_before_django_setup() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(  # noqa: S603
        [sys.executable, '-c', 'from django_celery_outbox import OutboxCelery; print(OutboxCelery.__name__)'],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'OutboxCelery'


@pytest.mark.django_db
def test_send_task_creates_outbox_record(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', args=(1, 2), kwargs={'key': 'val'})

    outbox = CeleryOutbox.objects.get()
    assert outbox.task_name == 'my.task'
    assert outbox.args == [1, 2]
    assert outbox.kwargs == {'key': 'val'}


@pytest.mark.django_db
def test_send_task_generates_task_id(f_app: OutboxCelery) -> None:
    result = f_app.send_task('my.task')

    outbox = CeleryOutbox.objects.get()
    assert outbox.task_id
    assert result.id == outbox.task_id


@pytest.mark.django_db
def test_send_task_uses_provided_task_id(f_app: OutboxCelery) -> None:
    result = f_app.send_task('my.task', task_id='custom-id-123')

    outbox = CeleryOutbox.objects.get()
    assert outbox.task_id == 'custom-id-123'
    assert result.id == 'custom-id-123'


@pytest.mark.django_db
def test_send_task_returns_async_result(f_app: OutboxCelery) -> None:
    result = f_app.send_task('my.task')

    assert isinstance(result, AsyncResult)


@patch('django_celery_outbox.app._logger')
@pytest.mark.django_db
def test_send_task_ignores_outbox_message_created_receiver_exception(
    m_logger: MagicMock,
    f_app: OutboxCelery,
) -> None:
    outbox_message_created.connect(boom)
    try:
        result = f_app.send_task('my.task', task_id='safe-signal-1')
    finally:
        outbox_message_created.disconnect(boom)

    assert result.id == 'safe-signal-1'
    assert CeleryOutbox.objects.filter(task_id='safe-signal-1').exists()
    m_logger.error.assert_called_once()
    assert m_logger.error.call_args.args == ('celery_outbox_signal_error',)
    assert m_logger.error.call_args.kwargs['signal'] == 'outbox_message_created'
    assert m_logger.error.call_args.kwargs['task_id'] == 'safe-signal-1'
    assert m_logger.error.call_args.kwargs['task_name'] == 'my.task'
    assert m_logger.error.call_args.kwargs['receiver'] == 'boom'
    assert m_logger.error.call_args.kwargs['exception_type'] == 'RuntimeError'
    assert m_logger.error.call_args.kwargs['exception_message'] == 'boom'

    exc_info = m_logger.error.call_args.kwargs['exc_info']
    assert exc_info[0] is RuntimeError
    assert isinstance(exc_info[1], RuntimeError)
    assert str(exc_info[1]) == 'boom'
    assert exc_info[2] is not None


@pytest.mark.django_db
def test_messages_enqueued_increments_only_after_commit(
    f_app: OutboxCelery,
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[list[Callable[[], object]]]],
) -> None:
    with patch('django_celery_outbox.metrics.increment') as increment:
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            with transaction.atomic():
                f_app.send_task('my.task', task_id='metric-commit-1')
                increment.assert_not_called()

        assert len(callbacks) == 1
        callbacks[0]()
        increment.assert_called_once_with('messages.enqueued', tags={'task_name': 'my.task'})


@pytest.mark.django_db
def test_messages_enqueued_not_emitted_on_rollback(
    f_app: OutboxCelery,
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[list[Callable[[], object]]]],
) -> None:
    with patch('django_celery_outbox.metrics.increment') as increment:
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            with pytest.raises(RuntimeError, match='rollback'):
                with transaction.atomic():
                    f_app.send_task('my.task', task_id='metric-rollback-1')
                    raise RuntimeError('rollback')

        assert callbacks == []
        increment.assert_not_called()


@patch.object(Celery, 'send_task', return_value=MagicMock(spec=AsyncResult))
@pytest.mark.django_db
def test_send_task_excluded_does_not_increment_messages_enqueued(
    m_super_send: MagicMock,
    f_app: OutboxCelery,
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[list[Callable[[], object]]]],
) -> None:
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        with patch('django_celery_outbox.metrics.increment') as increment:
            with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS={'my.excluded.task'}):
                f_app.send_task('my.excluded.task')

            increment.assert_not_called()

    assert callbacks == []
    m_super_send.assert_called_once()


@patch('django_celery_outbox.app._logger')
@pytest.mark.django_db
def test_messages_enqueued_metric_errors_are_logged_and_swallowed(
    m_logger: MagicMock,
    f_app: OutboxCelery,
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[list[Callable[[], object]]]],
) -> None:
    with patch('django_celery_outbox.metrics.increment', side_effect=RuntimeError('statsd down')):
        with django_capture_on_commit_callbacks(execute=True):
            result = f_app.send_task('my.task', task_id='metric-error-1')

    assert result.id == 'metric-error-1'
    assert CeleryOutbox.objects.filter(task_id='metric-error-1').exists()
    m_logger.warning.assert_any_call(
        'celery_outbox_metric_error',
        metric='messages.enqueued',
        task_name='my.task',
        exc_info=True,
    )


@pytest.mark.django_db
def test_pii_redactor_cache_tracks_setting_changes(f_app: OutboxCelery) -> None:
    def redactor(task_name: str, args: list, kwargs: dict) -> tuple[list, dict]:
        del task_name, kwargs
        return ['redacted', *args], {}

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=redactor):
        with transaction.atomic():
            f_app.send_task('my.task', task_id='redactor-cache-1', args=('secret',))

    first = CeleryOutbox.objects.get(task_id='redactor-cache-1')
    assert first.redacted_args == ['redacted', 'secret']

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=None):
        with transaction.atomic():
            f_app.send_task('my.task', task_id='redactor-cache-2', args=('secret',))

    second = CeleryOutbox.objects.get(task_id='redactor-cache-2')
    assert second.redacted_args is None


@pytest.mark.django_db
def test_pii_redactor_cache_accepts_unhashable_callable_instance(f_app: OutboxCelery) -> None:
    class UnhashableRedactor:
        def __call__(self, task_name: str, args: list, kwargs: dict) -> tuple[list, dict]:
            del task_name, kwargs
            return ['instance-redacted', *args], {}

        def __eq__(self, other: object) -> bool:
            return self is other

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=UnhashableRedactor()):
        with transaction.atomic():
            f_app.send_task('my.task', task_id='redactor-unhashable-1', args=('secret',))

    outbox = CeleryOutbox.objects.get(task_id='redactor-unhashable-1')
    assert outbox.redacted_args == ['instance-redacted', 'secret']


@pytest.mark.django_db
def test_send_task_args_none_saves_empty_list(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', args=None)

    outbox = CeleryOutbox.objects.get()
    assert outbox.args == []


@pytest.mark.django_db
def test_send_task_kwargs_none_saves_empty_dict(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', kwargs=None)

    outbox = CeleryOutbox.objects.get()
    assert outbox.kwargs == {}


@pytest.mark.django_db
def test_send_task_expires_in_options(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', expires=300)

    outbox = CeleryOutbox.objects.get()
    assert outbox.options['expires'] == 300


@pytest.mark.django_db
def test_send_task_link_in_options(f_app: OutboxCelery) -> None:
    link_sig = {'task': 'callback.task', 'args': (), 'kwargs': {}, 'options': {}, 'subtask_type': '', 'immutable': False, 'chord_size': None}
    f_app.send_task('my.task', link=link_sig)

    outbox = CeleryOutbox.objects.get()
    assert 'link' in outbox.options


@pytest.mark.django_db
def test_send_task_link_error_in_options(f_app: OutboxCelery) -> None:
    link_err_sig = {'task': 'error.task', 'args': (), 'kwargs': {}, 'options': {}, 'subtask_type': '', 'immutable': False, 'chord_size': None}
    f_app.send_task('my.task', link_error=link_err_sig)

    outbox = CeleryOutbox.objects.get()
    assert 'link_error' in outbox.options


@pytest.mark.django_db
def test_send_task_chord_in_options(f_app: OutboxCelery) -> None:
    chord_sig = {'task': 'chord.task', 'args': (), 'kwargs': {}, 'options': {}, 'subtask_type': '', 'immutable': False, 'chord_size': None}
    f_app.send_task('my.task', chord=chord_sig)

    outbox = CeleryOutbox.objects.get()
    assert 'chord' in outbox.options


@pytest.mark.django_db
def test_send_task_chain_in_options(f_app: OutboxCelery) -> None:
    chain_sig = {'task': 'chain.task', 'args': (), 'kwargs': {}, 'options': {}, 'subtask_type': '', 'immutable': False, 'chord_size': None}
    f_app.send_task('my.task', chain=[chain_sig])

    outbox = CeleryOutbox.objects.get()
    assert 'chain' in outbox.options


@pytest.mark.django_db
def test_send_task_group_id_in_options(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', group_id='group-123')

    outbox = CeleryOutbox.objects.get()
    assert outbox.options['group_id'] == 'group-123'


@pytest.mark.django_db
def test_send_task_group_index_in_options(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', group_index=5)

    outbox = CeleryOutbox.objects.get()
    assert outbox.options['group_index'] == 5


@pytest.mark.django_db
def test_send_task_time_limit_in_options(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', time_limit=60.0)

    outbox = CeleryOutbox.objects.get()
    assert outbox.options['time_limit'] == 60.0


@pytest.mark.django_db
def test_send_task_soft_time_limit_in_options(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', soft_time_limit=30.0)

    outbox = CeleryOutbox.objects.get()
    assert outbox.options['soft_time_limit'] == 30.0


@pytest.mark.django_db
def test_send_task_root_id_in_options(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', root_id='root-abc')

    outbox = CeleryOutbox.objects.get()
    assert outbox.options['root_id'] == 'root-abc'


@pytest.mark.django_db
def test_send_task_parent_id_in_options(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', parent_id='parent-abc')

    outbox = CeleryOutbox.objects.get()
    assert outbox.options['parent_id'] == 'parent-abc'


@pytest.mark.django_db
def test_send_task_route_name_in_options(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', route_name='custom-route')

    outbox = CeleryOutbox.objects.get()
    assert outbox.options['route_name'] == 'custom-route'


@pytest.mark.django_db
def test_send_task_shadow_in_options(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', shadow='shadow-name')

    outbox = CeleryOutbox.objects.get()
    assert outbox.options['shadow'] == 'shadow-name'


@pytest.mark.django_db
def test_send_task_retries_positive_in_options(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', retries=3)

    outbox = CeleryOutbox.objects.get()
    assert outbox.options['retries'] == 3


@pytest.mark.django_db
def test_send_task_retries_zero_not_in_options(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', retries=0)

    outbox = CeleryOutbox.objects.get()
    assert 'retries' not in outbox.options


@pytest.mark.django_db
def test_send_task_invalid_exclude_tasks_string_raises(f_app: OutboxCelery) -> None:
    with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS='my.excluded.task'):
        with pytest.raises(TypeError, match='CELERY_OUTBOX_EXCLUDE_TASKS'):
            f_app.send_task('my.excluded.task')

    assert CeleryOutbox.objects.count() == 0


@pytest.mark.django_db
def test_send_task_invalid_exclude_tasks_member_type_raises(f_app: OutboxCelery) -> None:
    with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS=('my.excluded.task', 1)):
        with pytest.raises(TypeError, match='must contain only strings'):
            f_app.send_task('my.excluded.task')

    assert CeleryOutbox.objects.count() == 0


@pytest.mark.django_db
@patch('django_celery_outbox.app.sentry_sdk')
def test_send_task_saves_sentry_context(m_sentry: MagicMock, f_app: OutboxCelery) -> None:
    m_sentry.get_traceparent.return_value = 'test-trace-id'
    m_sentry.get_baggage.return_value = 'test-baggage'

    f_app.send_task('my.task')

    outbox = CeleryOutbox.objects.get()
    assert outbox.sentry_trace_id == 'test-trace-id'
    assert outbox.sentry_baggage == 'test-baggage'


@pytest.mark.django_db
@patch('django_celery_outbox.app.sentry_sdk')
def test_send_task_accepts_long_sentry_baggage(m_sentry: MagicMock, f_app: OutboxCelery) -> None:
    baggage = 'x' * 3000
    m_sentry.get_traceparent.return_value = 'trace-1'
    m_sentry.get_baggage.return_value = baggage

    f_app.send_task('my.task', task_id='long-baggage-1')

    assert CeleryOutbox.objects.get(task_id='long-baggage-1').sentry_baggage == baggage


@pytest.mark.django_db
@patch('django_celery_outbox.app.sentry_sdk')
def test_send_task_creates_sentry_span(m_sentry: MagicMock, f_app: OutboxCelery) -> None:
    m_span = MagicMock()
    m_sentry.start_span.return_value.__enter__.return_value = m_span
    m_sentry.get_traceparent.return_value = None
    m_sentry.get_baggage.return_value = None

    f_app.send_task('my.task', task_id='span-test-id')

    m_sentry.start_span.assert_called_once_with(op='celery_outbox.intercept', name='my.task')
    m_span.set_data.assert_any_call('messaging.message.id', 'span-test-id')
    m_span.set_data.assert_any_call('messaging.destination.name', 'celery_outbox')
    m_span.set_status.assert_called_once_with('ok')


@pytest.mark.django_db
@patch('django_celery_outbox.app.get_structlog_context_json', return_value='{"key":"val"}')
def test_send_task_saves_structlog_context(m_get_structlog: MagicMock, f_app: OutboxCelery) -> None:
    f_app.send_task('my.task')

    outbox = CeleryOutbox.objects.get()
    assert outbox.structlog_context == '{"key":"val"}'


@pytest.mark.django_db
@patch.object(Celery, 'send_task', return_value=MagicMock(spec=AsyncResult))
def test_send_task_excluded_calls_super(m_super_send: MagicMock, f_app: OutboxCelery) -> None:
    with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS={'my.excluded.task'}):
        f_app.send_task('my.excluded.task', args=(1,), kwargs={'a': 1})

    m_super_send.assert_called_once()
    call_kwargs = m_super_send.call_args
    assert call_kwargs[0][0] == 'my.excluded.task'
    assert call_kwargs[1]['args'] == (1,)
    assert call_kwargs[1]['kwargs'] == {'a': 1}
    assert CeleryOutbox.objects.count() == 0


@pytest.mark.django_db
@patch.object(Celery, 'send_task', return_value=MagicMock(spec=AsyncResult))
def test_send_task_excluded_does_not_create_outbox(m_super_send: MagicMock, f_app: OutboxCelery) -> None:
    with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS={'my.excluded.task'}):
        f_app.send_task('my.excluded.task')

    assert CeleryOutbox.objects.count() == 0


@pytest.mark.django_db
def test_send_task_not_excluded_creates_outbox(f_app: OutboxCelery) -> None:
    with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS={'other.task'}, CELERY_OUTBOX_PII_REDACTOR=None):
        f_app.send_task('my.task')

    assert CeleryOutbox.objects.count() == 1


@pytest.mark.django_db
def test_send_task_no_exclude_setting_creates_outbox(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task')

    assert CeleryOutbox.objects.count() == 1


@pytest.mark.django_db
@patch.object(Celery, 'send_task', return_value=MagicMock(spec=AsyncResult))
def test_send_task_excluded_passes_all_params(m_super_send: MagicMock, f_app: OutboxCelery) -> None:
    with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS={'my.excluded.task'}):
        f_app.send_task(
            'my.excluded.task',
            args=(1, 2),
            kwargs={'k': 'v'},
            countdown=10,
            eta=None,
            task_id='tid',
            expires=300,
            group_id='gid',
            retries=2,
            time_limit=60,
            soft_time_limit=30,
            root_id='rid',
            parent_id='pid',
            route_name='rn',
            shadow='sh',
        )

    call_kwargs = m_super_send.call_args[1]
    assert call_kwargs['countdown'] == 10
    assert call_kwargs['task_id'] == 'tid'
    assert call_kwargs['expires'] == 300
    assert call_kwargs['group_id'] == 'gid'
    assert call_kwargs['retries'] == 2
    assert call_kwargs['time_limit'] == 60
    assert call_kwargs['soft_time_limit'] == 30
    assert call_kwargs['root_id'] == 'rid'
    assert call_kwargs['parent_id'] == 'pid'
    assert call_kwargs['route_name'] == 'rn'
    assert call_kwargs['shadow'] == 'sh'


@pytest.mark.django_db
def test_send_task_multiple_options_combined(f_app: OutboxCelery) -> None:
    f_app.send_task(
        'my.task',
        group_id='g1',
        time_limit=120,
        root_id='r1',
        shadow='s1',
    )

    outbox = CeleryOutbox.objects.get()
    assert outbox.options['group_id'] == 'g1'
    assert outbox.options['time_limit'] == 120
    assert outbox.options['root_id'] == 'r1'
    assert outbox.options['shadow'] == 's1'


@pytest.mark.django_db
def test_send_task_with_countdown(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task', countdown=60)

    outbox = CeleryOutbox.objects.get()
    assert 'eta' in outbox.options


@pytest.mark.django_db
def test_send_task_with_custom_result_cls(f_app: OutboxCelery) -> None:
    result = f_app.send_task('my.task', task_id='test-id', result_cls=AsyncResult)

    assert isinstance(result, AsyncResult)
    assert result.id == 'test-id'


@pytest.mark.django_db(transaction=True)
def test_send_task_logs_warning_outside_atomic(f_app: OutboxCelery) -> None:
    with patch('django_celery_outbox.app._logger') as m_logger:
        f_app.send_task('my.task')

    m_logger.warning.assert_called_once()
    assert m_logger.warning.call_args[0][0] == 'celery_outbox_not_in_transaction'


@pytest.mark.django_db
def test_send_task_no_warning_inside_atomic(f_app: OutboxCelery) -> None:
    with patch('django_celery_outbox.app._logger') as m_logger:
        with transaction.atomic():
            f_app.send_task('my.task')

    m_logger.warning.assert_not_called()


@pytest.mark.django_db
@patch.object(Celery, 'send_task', return_value=MagicMock(spec=AsyncResult))
def test_send_task_exclude_tasks_as_list(m_super_send: MagicMock, f_app: OutboxCelery) -> None:
    with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS=['my.excluded.task']):
        f_app.send_task('my.excluded.task')

    m_super_send.assert_called_once()
    assert CeleryOutbox.objects.count() == 0


@pytest.mark.django_db
def test_send_task_applies_pii_redactor(
    f_app: OutboxCelery,
) -> None:
    def redactor(name: str, args: list, kwargs: dict) -> tuple[list, dict]:
        args[0]['email'] = '[REDACTED]'
        redacted_kwargs = {k: '[REDACTED]' if k == 'email' else v for k, v in kwargs.items()}
        return args, redacted_kwargs

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=redactor):
        f_app.send_task(
            'test.task',
            args=({'email': 'user@example.com'},),
            kwargs={'email': 'user@example.com', 'safe': 1},
        )

    msg = CeleryOutbox.objects.first()
    assert msg is not None
    assert msg.args == [{'email': 'user@example.com'}]
    assert msg.redacted_args == [{'email': '[REDACTED]'}]
    assert msg.kwargs == {'email': 'user@example.com', 'safe': 1}
    assert msg.redacted_kwargs == {'email': '[REDACTED]', 'safe': 1}


@pytest.mark.django_db
def test_send_task_no_redactor_stores_original(
    f_app: OutboxCelery,
) -> None:
    with override_settings(CELERY_OUTBOX_PII_REDACTOR=None):
        f_app.send_task('test.task', kwargs={'email': 'user@example.com'})

    msg = CeleryOutbox.objects.first()
    assert msg is not None
    assert msg.kwargs == {'email': 'user@example.com'}
    assert msg.redacted_args is None
    assert msg.redacted_kwargs is None


@pytest.mark.django_db
def test_send_task_redactor_exception_propagates(
    f_app: OutboxCelery,
) -> None:
    def bad_redactor(name: str, args: list, kwargs: dict) -> tuple[list, dict]:
        raise ValueError('blocked')

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=bad_redactor):
        with pytest.raises(ValueError, match='blocked'):
            f_app.send_task('test.task', kwargs={})


@pytest.mark.django_db
def test_send_task_applies_pii_redactor_from_string_path(
    f_app: OutboxCelery,
) -> None:
    with override_settings(CELERY_OUTBOX_PII_REDACTOR='django_celery_outbox.app_tests.sample_redactor'):
        f_app.send_task(
            'test.task',
            kwargs={'email': 'user@example.com'},
        )

    msg = CeleryOutbox.objects.first()
    assert msg is not None
    assert msg.kwargs == {'email': 'user@example.com'}
    assert msg.redacted_kwargs == {'email': '[REDACTED]'}


@pytest.mark.django_db
def test_send_task_redactor_invoked_once_for_top_level_payload(
    f_app: OutboxCelery,
) -> None:
    redactor = MagicMock(return_value=([{'email': '[REDACTED]'}], {'token': '[REDACTED]'}))

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=redactor):
        f_app.send_task(
            'test.task',
            args=({'email': 'user@example.com'},),
            kwargs={'token': 'secret'},
        )

    redactor.assert_called_once_with(
        'test.task',
        [{'email': 'user@example.com'}],
        {'token': 'secret'},
    )


def test_redact_options_for_inspection_returns_original_options_when_redactor_disabled() -> None:
    options = {'link': [{'task': 'child.task'}]}

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=None):
        result = _redact_options_for_inspection('parent.task', options)

    assert result is options


@pytest.mark.django_db
def test_send_task_without_redactor_skips_deepcopy(
    f_app: OutboxCelery,
) -> None:
    with patch('django_celery_outbox.app.deepcopy') as m_deepcopy:
        with override_settings(CELERY_OUTBOX_PII_REDACTOR=None):
            f_app.send_task(
                'test.task',
                args=({'email': 'user@example.com'},),
                kwargs={'token': 'secret'},
            )

        m_deepcopy.assert_not_called()


@pytest.mark.django_db
def test_send_task_with_redactor_clones_payload_once(
    f_app: OutboxCelery,
) -> None:
    from copy import deepcopy as real_deepcopy

    with patch('django_celery_outbox.app.deepcopy', side_effect=real_deepcopy) as m_deepcopy:
        with override_settings(CELERY_OUTBOX_PII_REDACTOR='django_celery_outbox.app_tests.sample_redactor'):
            f_app.send_task(
                'test.task',
                args=({'email': 'user@example.com'},),
                kwargs={'email': 'user@example.com'},
            )

        m_deepcopy.assert_called_once()
