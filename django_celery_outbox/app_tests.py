from unittest.mock import MagicMock, patch

import pytest
from celery import Celery
from celery.result import AsyncResult
from django.db import transaction

from django_celery_outbox.app import OutboxCelery
from django_celery_outbox.models import CeleryOutbox


@pytest.fixture()
def f_app() -> OutboxCelery:
    return OutboxCelery('test')


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
    with patch('django_celery_outbox.app.settings') as m_settings:
        m_settings.CELERY_OUTBOX_EXCLUDE_TASKS = {'my.excluded.task'}
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
    with patch('django_celery_outbox.app.settings') as m_settings:
        m_settings.CELERY_OUTBOX_EXCLUDE_TASKS = {'my.excluded.task'}
        f_app.send_task('my.excluded.task')

    assert CeleryOutbox.objects.count() == 0


@pytest.mark.django_db
def test_send_task_not_excluded_creates_outbox(f_app: OutboxCelery) -> None:
    with patch('django_celery_outbox.app.settings') as m_settings:
        m_settings.CELERY_OUTBOX_EXCLUDE_TASKS = {'other.task'}
        f_app.send_task('my.task')

    assert CeleryOutbox.objects.count() == 1


@pytest.mark.django_db
def test_send_task_no_exclude_setting_creates_outbox(f_app: OutboxCelery) -> None:
    f_app.send_task('my.task')

    assert CeleryOutbox.objects.count() == 1


@pytest.mark.django_db
@patch.object(Celery, 'send_task', return_value=MagicMock(spec=AsyncResult))
def test_send_task_excluded_passes_all_params(m_super_send: MagicMock, f_app: OutboxCelery) -> None:
    with patch('django_celery_outbox.app.settings') as m_settings:
        m_settings.CELERY_OUTBOX_EXCLUDE_TASKS = {'my.excluded.task'}
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
    with patch('django_celery_outbox.app.settings') as m_settings:
        m_settings.CELERY_OUTBOX_EXCLUDE_TASKS = ['my.excluded.task']
        f_app.send_task('my.excluded.task')

    m_super_send.assert_called_once()
    assert CeleryOutbox.objects.count() == 0
