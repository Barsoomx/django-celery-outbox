import json
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import sentry_sdk
import sentry_sdk.transport
import structlog.contextvars
from celery import Celery
from celery.canvas import Signature
from django.conf import LazySettings
from django.db import transaction

from django_celery_outbox.app import OutboxCelery
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter
from django_celery_outbox.relay import Relay

_DUMMY_DSN = 'https://examplePublicKey@o0.ingest.sentry.io/0'


@pytest.fixture()
def f_outbox_app() -> OutboxCelery:
    return OutboxCelery('test-integration')


@pytest.fixture()
def f_relay_app() -> Celery:
    return Celery('test-integration')


@pytest.fixture()
def f_relay(f_relay_app: Celery) -> Relay:
    return Relay(
        app=f_relay_app,
        batch_size=10,
        idle_time=0,
        backoff_time=120,
        max_retries=3,
    )


@pytest.fixture()
def m_celery_send() -> Generator[MagicMock]:
    with patch('django_celery_outbox.relay.Celery.send_task') as mock:
        yield mock


class _NoopTransport(sentry_sdk.transport.Transport):
    def capture_envelope(self, *args: Any, **kwargs: Any) -> None:
        pass


@pytest.fixture()
def f_sentry_init() -> Generator[None]:
    sentry_sdk.init(
        dsn=_DUMMY_DSN,
        traces_sample_rate=1.0,
        transport=_NoopTransport,
    )
    yield
    client = sentry_sdk.get_client()
    if client is not None:
        client.close()
    sentry_sdk.init()


@pytest.fixture(autouse=True)
def f_clean_structlog() -> Generator[None]:
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


# ============================================================
# E2E Flow Tests
# ============================================================


@pytest.mark.django_db
def test_e2e_basic_flow_preserves_task_data(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    with transaction.atomic():
        result = f_outbox_app.send_task(
            'my.task',
            args=(1, 'hello', [3, 4]),
            kwargs={'key': 'value', 'nested': {'a': 1}},
            task_id='test-task-id-001',
        )

    f_relay._processing()

    m_celery_send.assert_called_once()
    call_kwargs = m_celery_send.call_args
    assert call_kwargs.kwargs['name'] == 'my.task'
    assert call_kwargs.kwargs['args'] == [1, 'hello', [3, 4]]
    assert call_kwargs.kwargs['kwargs'] == {'key': 'value', 'nested': {'a': 1}}
    assert call_kwargs.kwargs['task_id'] == 'test-task-id-001'
    assert result.id == 'test-task-id-001'


@pytest.mark.django_db
def test_e2e_countdown_converts_to_eta(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    with transaction.atomic():
        f_outbox_app.send_task('my.task', countdown=120)

    msg = CeleryOutbox.objects.get()
    stored_eta = datetime.fromisoformat(msg.options['eta'])

    f_relay._processing()

    call_kwargs = m_celery_send.call_args
    eta = call_kwargs.kwargs['eta']
    assert isinstance(eta, datetime)
    assert eta == stored_eta


@pytest.mark.django_db
def test_e2e_eta_datetime_roundtrip(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    original_eta = datetime(2030, 6, 15, 12, 30, 0, tzinfo=timezone.utc)

    with transaction.atomic():
        f_outbox_app.send_task('my.task', eta=original_eta)

    f_relay._processing()

    call_kwargs = m_celery_send.call_args
    eta = call_kwargs.kwargs['eta']
    assert isinstance(eta, datetime)
    assert eta == original_eta


@pytest.mark.django_db
def test_e2e_link_signature_roundtrip(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    f_relay_app: Celery,
    m_celery_send: MagicMock,
) -> None:
    link_sig = Signature('callback.task', args=(42,), kwargs={'x': 1}, app=f_relay_app)

    with transaction.atomic():
        f_outbox_app.send_task('my.task', link=link_sig)

    f_relay._processing()

    call_kwargs = m_celery_send.call_args
    restored_links = call_kwargs.kwargs['link']
    assert isinstance(restored_links, list)
    assert len(restored_links) == 1
    restored = restored_links[0]
    assert isinstance(restored, Signature)
    assert restored.task == 'callback.task'
    assert list(restored.args) == [42]
    assert dict(restored.kwargs) == {'x': 1}


@pytest.mark.django_db
def test_e2e_chain_signatures_roundtrip(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    f_relay_app: Celery,
    m_celery_send: MagicMock,
) -> None:
    sig1 = Signature('step1.task', args=(1,), app=f_relay_app)
    sig2 = Signature('step2.task', args=(2,), app=f_relay_app)
    chain_sigs = [sig1, sig2]

    with transaction.atomic():
        f_outbox_app.send_task('my.task', chain=chain_sigs)

    f_relay._processing()

    call_kwargs = m_celery_send.call_args
    restored_chain = call_kwargs.kwargs['chain']
    assert isinstance(restored_chain, list)
    assert len(restored_chain) == 2
    assert restored_chain[0].task == 'step1.task'
    assert restored_chain[1].task == 'step2.task'


@pytest.mark.django_db
def test_e2e_chord_signature_roundtrip(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    f_relay_app: Celery,
    m_celery_send: MagicMock,
) -> None:
    chord_sig = Signature('chord.callback', args=(99,), app=f_relay_app)

    with transaction.atomic():
        f_outbox_app.send_task('my.task', chord=chord_sig)

    f_relay._processing()

    call_kwargs = m_celery_send.call_args
    restored_chord = call_kwargs.kwargs['chord']
    assert isinstance(restored_chord, Signature)
    assert restored_chord.task == 'chord.callback'
    assert list(restored_chord.args) == [99]


@pytest.mark.django_db
def test_e2e_expires_int_roundtrip(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    with transaction.atomic():
        f_outbox_app.send_task('my.task', expires=300)

    f_relay._processing()

    call_kwargs = m_celery_send.call_args
    assert call_kwargs.kwargs['expires'] == 300


@pytest.mark.django_db
def test_e2e_expires_datetime_roundtrip(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    original_expires = datetime(2030, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    with transaction.atomic():
        f_outbox_app.send_task('my.task', expires=original_expires)

    f_relay._processing()

    call_kwargs = m_celery_send.call_args
    restored_expires = call_kwargs.kwargs['expires']
    assert isinstance(restored_expires, datetime)
    assert restored_expires == original_expires


@pytest.mark.django_db
def test_e2e_time_limit_and_soft_time_limit_roundtrip(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    with transaction.atomic():
        f_outbox_app.send_task('my.task', time_limit=600, soft_time_limit=300)

    f_relay._processing()

    call_kwargs = m_celery_send.call_args
    assert call_kwargs.kwargs['time_limit'] == 600
    assert call_kwargs.kwargs['soft_time_limit'] == 300


@pytest.mark.django_db
def test_e2e_combined_options_roundtrip(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    with transaction.atomic():
        f_outbox_app.send_task(
            'my.task',
            group_id='group-1',
            root_id='root-1',
            shadow='my-shadow',
            time_limit=120,
        )

    f_relay._processing()

    call_kwargs = m_celery_send.call_args
    assert call_kwargs.kwargs['group_id'] == 'group-1'
    assert call_kwargs.kwargs['root_id'] == 'root-1'
    assert call_kwargs.kwargs['shadow'] == 'my-shadow'
    assert call_kwargs.kwargs['time_limit'] == 120


@pytest.mark.django_db
def test_e2e_processing_deletes_published_message(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    with transaction.atomic():
        f_outbox_app.send_task('my.task', args=(1,))

    assert CeleryOutbox.objects.count() == 1

    f_relay._processing()

    assert CeleryOutbox.objects.count() == 0


@pytest.mark.django_db
def test_e2e_failed_delivery_increments_retries(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    m_celery_send.side_effect = ConnectionError('broker down')

    with transaction.atomic():
        f_outbox_app.send_task('my.task', args=(1,))

    f_relay._processing()

    msg = CeleryOutbox.objects.get()
    assert msg.retries == 1
    assert msg.retry_after is not None


@pytest.mark.django_db
def test_e2e_dead_letter_on_max_retries_exceeded(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    with transaction.atomic():
        f_outbox_app.send_task('my.task', args=(1,), task_id='dead-task-1')

    CeleryOutbox.objects.update(retries=3)

    f_relay._processing()

    assert CeleryOutbox.objects.count() == 0
    dead = CeleryOutboxDeadLetter.objects.get()
    assert dead.task_id == 'dead-task-1'
    assert dead.failure_reason == 'max retries exceeded'


@pytest.mark.django_db
def test_e2e_dead_letter_preserves_all_data(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    structlog.contextvars.bind_contextvars(request_id='req-dead')

    with transaction.atomic():
        f_outbox_app.send_task(
            'my.important.task',
            args=(1, 2, 3),
            kwargs={'key': 'val'},
            task_id='dead-preserve-1',
            expires=300,
        )

    CeleryOutbox.objects.update(retries=3)

    f_relay._processing()

    dead = CeleryOutboxDeadLetter.objects.get()
    assert dead.task_id == 'dead-preserve-1'
    assert dead.task_name == 'my.important.task'
    assert dead.args == [1, 2, 3]
    assert dead.kwargs == {'key': 'val'}
    assert dead.options.get('expires') == 300
    assert dead.retries == 3
    assert dead.failure_reason == 'max retries exceeded'
    assert dead.structlog_context is not None
    ctx = json.loads(dead.structlog_context)
    assert ctx['request_id'] == 'req-dead'


@pytest.mark.django_db
def test_e2e_multiple_messages_batch_processing(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    with transaction.atomic():
        f_outbox_app.send_task('task.one', args=(1,))
        f_outbox_app.send_task('task.two', args=(2,))
        f_outbox_app.send_task('task.three', args=(3,))

    f_relay._processing()

    assert m_celery_send.call_count == 3
    task_names = {call.kwargs['name'] for call in m_celery_send.call_args_list}
    assert task_names == {'task.one', 'task.two', 'task.three'}
    assert CeleryOutbox.objects.count() == 0


# ============================================================
# Sentry Integration Tests
# ============================================================


@pytest.mark.django_db
def test_sentry_captures_traceparent_and_baggage(
    f_sentry_init: None,
    f_outbox_app: OutboxCelery,
) -> None:
    with sentry_sdk.start_transaction(name='test-tx'):
        traceparent = sentry_sdk.get_traceparent()
        baggage = sentry_sdk.get_baggage()
        assert traceparent is not None
        assert baggage is not None

        with transaction.atomic():
            f_outbox_app.send_task('my.task', task_id='sentry-test-1')

    msg = CeleryOutbox.objects.get()
    assert msg.sentry_trace_id is not None
    assert msg.sentry_baggage is not None
    parts = msg.sentry_trace_id.split('-')
    assert len(parts) >= 2


@pytest.mark.django_db
def test_sentry_relay_restores_headers(
    f_sentry_init: None,
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    with sentry_sdk.start_transaction(name='test-tx'):
        with transaction.atomic():
            f_outbox_app.send_task('my.task', task_id='sentry-relay-1')

    f_relay._processing()

    call_kwargs = m_celery_send.call_args
    headers = call_kwargs.kwargs['headers']
    assert 'sentry-trace' in headers
    assert 'baggage' in headers
    parts = headers['sentry-trace'].split('-')
    assert len(parts) >= 2


@pytest.mark.django_db
def test_sentry_full_trace_id_consistency(
    f_sentry_init: None,
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    with sentry_sdk.start_transaction(name='test-tx'):
        traceparent = sentry_sdk.get_traceparent()
        assert traceparent is not None
        trace_id = traceparent.split('-')[0]

        with transaction.atomic():
            f_outbox_app.send_task('my.task', task_id='trace-consistency-1')

    msg = CeleryOutbox.objects.get()
    assert msg.sentry_trace_id is not None
    stored_trace_id = msg.sentry_trace_id.split('-')[0]
    assert stored_trace_id == trace_id

    f_relay._processing()

    call_kwargs = m_celery_send.call_args
    relay_trace = call_kwargs.kwargs['headers']['sentry-trace']
    relay_trace_id = relay_trace.split('-')[0]
    assert relay_trace_id == trace_id


@pytest.mark.django_db
def test_sentry_no_trace_data_no_headers(
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    CeleryOutbox.objects.create(
        task_id='no-trace-1',
        task_name='my.task',
        args=[1],
        kwargs={},
        options={},
        sentry_trace_id=None,
        sentry_baggage=None,
    )

    f_relay._processing()

    call_kwargs = m_celery_send.call_args
    headers = call_kwargs.kwargs['headers']
    assert 'sentry-trace' not in headers
    assert 'baggage' not in headers


# ============================================================
# Structlog Integration Tests
# ============================================================


@pytest.mark.django_db
def test_structlog_context_captured_and_restored(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    captured_ctx: dict = {}

    def capture_context(*args: Any, **kwargs: Any) -> None:
        captured_ctx.update(structlog.contextvars.get_contextvars())

    m_celery_send.side_effect = capture_context

    structlog.contextvars.bind_contextvars(request_id='req-123', user_id='user-456')

    with transaction.atomic():
        f_outbox_app.send_task('my.task')

    structlog.contextvars.clear_contextvars()

    f_relay._processing()

    assert captured_ctx['request_id'] == 'req-123'
    assert captured_ctx['user_id'] == 'user-456'


@pytest.mark.django_db
def test_structlog_key_filtering(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
    settings: LazySettings,
) -> None:
    captured_ctx: dict = {}

    def capture_context(*args: Any, **kwargs: Any) -> None:
        captured_ctx.update(structlog.contextvars.get_contextvars())

    m_celery_send.side_effect = capture_context
    settings.CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS = ['request_id']

    structlog.contextvars.bind_contextvars(request_id='req-filtered', user_id='user-filtered')

    with transaction.atomic():
        f_outbox_app.send_task('my.task')

    structlog.contextvars.clear_contextvars()

    f_relay._processing()

    assert captured_ctx.get('request_id') == 'req-filtered'
    assert 'user_id' not in captured_ctx


@pytest.mark.django_db
def test_structlog_disabled_no_context_stored(
    f_outbox_app: OutboxCelery,
    settings: LazySettings,
) -> None:
    settings.CELERY_OUTBOX_STRUCTLOG_ENABLED = False

    structlog.contextvars.bind_contextvars(request_id='req-disabled')

    with transaction.atomic():
        f_outbox_app.send_task('my.task')

    msg = CeleryOutbox.objects.get()
    assert msg.structlog_context is None


@pytest.mark.django_db
def test_structlog_context_isolation_between_messages(
    f_outbox_app: OutboxCelery,
    f_relay: Relay,
    m_celery_send: MagicMock,
) -> None:
    captured_contexts: list[dict] = []

    def capture_context(*args: Any, **kwargs: Any) -> None:
        captured_contexts.append(dict(structlog.contextvars.get_contextvars()))

    m_celery_send.side_effect = capture_context

    structlog.contextvars.bind_contextvars(request_id='req-A')
    with transaction.atomic():
        f_outbox_app.send_task('task.a')

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id='req-B')
    with transaction.atomic():
        f_outbox_app.send_task('task.b')

    structlog.contextvars.clear_contextvars()

    f_relay._processing()

    assert len(captured_contexts) == 2
    ctx_a = next(c for c in captured_contexts if c.get('request_id') == 'req-A')
    ctx_b = next(c for c in captured_contexts if c.get('request_id') == 'req-B')
    assert ctx_a['request_id'] == 'req-A'
    assert ctx_b['request_id'] == 'req-B'
