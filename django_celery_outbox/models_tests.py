from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter


@pytest.mark.django_db
def test_default_values() -> None:
    outbox = CeleryOutbox.objects.create(
        task_id='test-task-id',
        task_name='my_app.tasks.do_stuff',
    )

    assert outbox.args == []
    assert outbox.kwargs == {}
    assert outbox.redacted_args is None
    assert outbox.redacted_kwargs is None
    assert outbox.options == {}
    assert outbox.retries == 0


@pytest.mark.django_db
def test_str_format() -> None:
    outbox = CeleryOutbox.objects.create(
        task_id='test-task-id',
        task_name='my_app.tasks.do_stuff',
        retries=3,
    )

    result = str(outbox)

    assert f'id={outbox.id}' in result
    assert 'task_name=my_app.tasks.do_stuff' in result
    assert 'task_id=test-task-id' in result
    assert 'retries=3' in result


def test_verbose_name() -> None:
    assert CeleryOutbox._meta.verbose_name == 'CeleryOutbox'


def test_pending_index_exists() -> None:
    index_names = [idx.name for idx in CeleryOutbox._meta.indexes]

    assert 'celery_outbox_pending_idx' in index_names


def test_outbox_retry_and_stale_indexes_declared() -> None:
    index_names = {index.name for index in CeleryOutbox._meta.indexes}

    assert 'celery_outbox_pending_idx' in index_names
    assert 'celery_outbox_retry_idx' in index_names
    assert 'celery_outbox_stale_idx' in index_names


def test_dead_letter_retention_indexes_declared() -> None:
    index_names = {index.name for index in CeleryOutboxDeadLetter._meta.indexes}

    assert 'celery_outbox_dlq_dead_at_idx' in index_names
    assert 'celery_outbox_dlq_created_idx' in index_names


def test_sentry_baggage_fields_are_text_fields() -> None:
    assert CeleryOutbox._meta.get_field('sentry_baggage').get_internal_type() == 'TextField'
    assert CeleryOutboxDeadLetter._meta.get_field('sentry_baggage').get_internal_type() == 'TextField'


def _redact_payloads(task_name: str, args: list, kwargs: dict) -> tuple[list, dict]:
    del task_name
    redacted_args = [{'email': '[REDACTED]'} if isinstance(item, dict) and 'email' in item else item for item in args]
    redacted_kwargs = {key: '[REDACTED]' if key in {'email', 'token'} else value for key, value in kwargs.items()}
    return redacted_args, redacted_kwargs


@pytest.mark.django_db
def test_outbox_inspection_options_redacts_link_signature() -> None:
    msg = CeleryOutbox.objects.create(
        task_id='inspect-link-1',
        task_name='parent.task',
        options={
            'link': [
                {
                    'task': 'callback.task',
                    'args': [{'email': 'user@example.com'}],
                    'kwargs': {'token': 'secret'},
                    'options': {},
                    'subtask_type': None,
                    'immutable': False,
                    'chord_size': None,
                }
            ],
        },
    )

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=_redact_payloads):
        assert msg.inspection_options['link'][0]['kwargs']['token'] == '[REDACTED]'


@pytest.mark.django_db
def test_outbox_inspection_options_redacts_link_error_chain_and_chord() -> None:
    msg = CeleryOutbox.objects.create(
        task_id='inspect-nested-1',
        task_name='parent.task',
        options={
            'link_error': [
                {
                    'task': 'error.task',
                    'args': [],
                    'kwargs': {'token': 'secret'},
                    'options': {},
                    'subtask_type': None,
                    'immutable': False,
                    'chord_size': None,
                }
            ],
            'chain': [
                {
                    'task': 'chain.task',
                    'args': [{'email': 'user@example.com'}],
                    'kwargs': {},
                    'options': {},
                    'subtask_type': None,
                    'immutable': False,
                    'chord_size': None,
                }
            ],
            'chord': {
                'task': 'chord.task',
                'args': [],
                'kwargs': {'token': 'secret'},
                'options': {},
                'subtask_type': None,
                'immutable': False,
                'chord_size': None,
            },
        },
    )

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=_redact_payloads):
        inspected = msg.inspection_options

    assert inspected['link_error'][0]['kwargs']['token'] == '[REDACTED]'
    assert inspected['chain'][0]['args'][0]['email'] == '[REDACTED]'
    assert inspected['chord']['kwargs']['token'] == '[REDACTED]'


@pytest.mark.django_db
def test_outbox_inspection_options_redacts_nested_signature_options() -> None:
    msg = CeleryOutbox.objects.create(
        task_id='inspect-recursive-1',
        task_name='parent.task',
        options={
            'link': [
                {
                    'task': 'callback.task',
                    'args': [],
                    'kwargs': {},
                    'options': {
                        'link': [
                            {
                                'task': 'inner.task',
                                'args': [],
                                'kwargs': {'token': 'secret'},
                                'options': {},
                                'subtask_type': None,
                                'immutable': False,
                                'chord_size': None,
                            }
                        ]
                    },
                    'subtask_type': None,
                    'immutable': False,
                    'chord_size': None,
                }
            ],
        },
    )

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=_redact_payloads):
        inspected = msg.inspection_options

    assert inspected['link'][0]['options']['link'][0]['kwargs']['token'] == '[REDACTED]'


@pytest.mark.django_db
def test_outbox_inspection_options_uses_nested_signature_task_names() -> None:
    def task_aware_redactor(task_name: str, args: list, kwargs: dict) -> tuple[list, dict]:
        del args
        if task_name == 'inner.task':
            return [], {'token': '[REDACTED]'}
        return [], kwargs

    msg = CeleryOutbox.objects.create(
        task_id='inspect-nested-task-name-1',
        task_name='parent.task',
        options={
            'link': [
                {
                    'task': 'callback.task',
                    'args': [],
                    'kwargs': {},
                    'options': {
                        'link': [
                            {
                                'task': 'inner.task',
                                'args': [],
                                'kwargs': {'token': 'secret'},
                                'options': {},
                                'subtask_type': None,
                                'immutable': False,
                                'chord_size': None,
                            }
                        ]
                    },
                    'subtask_type': None,
                    'immutable': False,
                    'chord_size': None,
                }
            ],
        },
    )

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=task_aware_redactor):
        inspected = msg.inspection_options

    assert inspected['link'][0]['options']['link'][0]['kwargs']['token'] == '[REDACTED]'


@patch('django_celery_outbox.app._logger')
@pytest.mark.django_db
def test_outbox_inspection_options_falls_back_to_raw_options_when_nested_redaction_fails(
    m_logger: MagicMock,
) -> None:
    def bad_redactor(task_name: str, args: list, kwargs: dict) -> tuple[list, dict]:
        del task_name, args, kwargs
        raise RuntimeError('broken nested redaction')

    msg = CeleryOutbox.objects.create(
        task_id='inspect-fallback-1',
        task_name='parent.task',
        options={
            'link': [
                {
                    'task': 'callback.task',
                    'args': [],
                    'kwargs': {'token': 'secret'},
                    'options': {},
                    'subtask_type': None,
                    'immutable': False,
                    'chord_size': None,
                }
            ]
        },
    )

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=bad_redactor):
        assert msg.inspection_options == msg.options

    m_logger.warning.assert_any_call(
        'celery_outbox_inspection_redaction_failed',
        task_name='parent.task',
        exc_info=True,
    )


@pytest.mark.django_db
def test_created_at_auto_set() -> None:
    outbox = CeleryOutbox.objects.create(
        task_id='test-created',
        task_name='my_app.tasks.created',
    )

    assert outbox.created_at is not None


@pytest.mark.django_db
def test_updated_at_default_none() -> None:
    outbox = CeleryOutbox.objects.create(
        task_id='test-updated',
        task_name='my_app.tasks.updated',
    )

    assert outbox.updated_at is None


def test_verbose_name_plural() -> None:
    assert CeleryOutbox._meta.verbose_name_plural == 'CeleryOutbox'


def test_db_table() -> None:
    assert CeleryOutbox._meta.db_table == 'celery_outbox'
