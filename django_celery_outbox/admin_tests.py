from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from django.contrib import admin, messages
from django.test import override_settings
from django.utils import timezone

if TYPE_CHECKING:
    from django.contrib.auth.models import User

from django_celery_outbox.admin import CeleryOutboxAdmin, CeleryOutboxDeadLetterAdmin
from django_celery_outbox.factories import CeleryOutboxDeadLetterFactory, CeleryOutboxFactory
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter


def _redact_payloads(task_name: str, args: list, kwargs: dict) -> tuple[list, dict]:
    del task_name
    redacted_args = [{'email': '[REDACTED]'} if isinstance(item, dict) and 'email' in item else item for item in args]
    redacted_kwargs = {key: '[REDACTED]' if key in {'email', 'token'} else value for key, value in kwargs.items()}
    return redacted_args, redacted_kwargs


def test_registered_for_model() -> None:
    assert CeleryOutbox in admin.site._registry
    assert isinstance(admin.site._registry[CeleryOutbox], CeleryOutboxAdmin)


def test_has_add_permission_returns_false() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    assert admin_instance.has_add_permission(request=MagicMock()) is False


def test_has_change_permission_returns_false() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    assert admin_instance.has_change_permission(request=MagicMock()) is False


def test_list_display() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    expected = ['id', 'task_name', 'task_id', 'retries', 'schema_version', 'created_at', 'updated_at']
    assert admin_instance.list_display == expected


def test_list_filter() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    assert admin_instance.list_filter == ['task_name', 'retries', 'schema_version']


def test_search_fields() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    assert admin_instance.search_fields == ['task_id', 'task_name']


def test_readonly_fields() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    expected = [
        'id',
        'task_name',
        'task_id',
        'display_args',
        'display_kwargs',
        'display_options',
        'retries',
        'schema_version',
        'created_at',
        'updated_at',
        'retry_after',
        'sentry_trace_id',
        'sentry_baggage',
        'structlog_context',
    ]
    assert admin_instance.readonly_fields == expected


@pytest.mark.django_db
def test_admin_display_options_uses_inspection_options() -> None:
    admin_instance: CeleryOutboxAdmin = admin.site._registry[CeleryOutbox]  # type: ignore[assignment]
    entry = CeleryOutboxFactory.build(
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

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=_redact_payloads):
        displayed = admin_instance.display_options(entry)

    assert displayed['link'][0]['kwargs']['token'] == '[REDACTED]'


def test_has_delete_permission_returns_false() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    assert admin_instance.has_delete_permission(request=MagicMock()) is False


def test_actions_include_reset_retries() -> None:
    admin_instance: CeleryOutboxAdmin = admin.site._registry[CeleryOutbox]  # type: ignore[assignment]

    assert 'reset_retries' in admin_instance.actions


def test_change_list_template() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    assert admin_instance.change_list_template == 'admin/django_celery_outbox/celeryoutbox/change_list.html'


@pytest.mark.django_db
def test_changelist_view_injects_summary_stats() -> None:
    CeleryOutboxFactory.create()
    CeleryOutboxFactory.create(updated_at=timezone.now())
    CeleryOutboxFactory.create(retries=3)

    admin_instance = admin.site._registry[CeleryOutbox]
    m_request = MagicMock()
    m_request.GET = {}

    with patch.object(admin.ModelAdmin, 'changelist_view', return_value=MagicMock()) as m_super:
        admin_instance.changelist_view(m_request)

    extra_context = m_super.call_args[1]['extra_context']
    assert extra_context['pending_count'] == 2
    assert extra_context['failed_count'] == 1
    assert extra_context['total_count'] == 3
    assert extra_context['oldest_pending'] is not None


@pytest.mark.django_db
def test_changelist_view_oldest_pending_none_when_no_pending() -> None:
    CeleryOutboxFactory.create(updated_at=timezone.now())

    admin_instance = admin.site._registry[CeleryOutbox]
    m_request = MagicMock()
    m_request.GET = {}

    with patch.object(admin.ModelAdmin, 'changelist_view', return_value=MagicMock()) as m_super:
        admin_instance.changelist_view(m_request)

    extra_context = m_super.call_args[1]['extra_context']
    assert extra_context['oldest_pending'] is None


@pytest.mark.django_db
def test_changelist_view_oldest_pending_is_timedelta() -> None:
    CeleryOutboxFactory.create()

    admin_instance = admin.site._registry[CeleryOutbox]
    m_request = MagicMock()
    m_request.GET = {}

    with patch.object(admin.ModelAdmin, 'changelist_view', return_value=MagicMock()) as m_super:
        admin_instance.changelist_view(m_request)

    extra_context = m_super.call_args[1]['extra_context']
    assert isinstance(extra_context['oldest_pending'], timedelta)


@pytest.mark.django_db
def test_reset_retries_action(f_user: 'User') -> None:
    entry1 = CeleryOutboxFactory.create(retries=5, retry_after=timezone.now(), updated_at=timezone.now())
    entry2 = CeleryOutboxFactory.create(retries=3, retry_after=timezone.now(), updated_at=timezone.now())

    admin_instance: CeleryOutboxAdmin = admin.site._registry[CeleryOutbox]  # type: ignore[assignment]
    queryset = CeleryOutbox.objects.filter(pk__in=[entry1.pk, entry2.pk])
    m_request = MagicMock()
    m_request.user = f_user

    admin_instance.reset_retries(m_request, queryset)

    entry1.refresh_from_db()
    entry2.refresh_from_db()
    assert entry1.retries == 0
    assert entry1.retry_after is None
    assert entry1.updated_at is None
    assert entry2.retries == 0
    assert entry2.retry_after is None
    assert entry2.updated_at is None


def test_dead_letter_registered_for_model() -> None:
    assert CeleryOutboxDeadLetter in admin.site._registry
    assert isinstance(admin.site._registry[CeleryOutboxDeadLetter], CeleryOutboxDeadLetterAdmin)


def test_dead_letter_has_add_permission_returns_false() -> None:
    admin_instance = admin.site._registry[CeleryOutboxDeadLetter]

    assert admin_instance.has_add_permission(request=MagicMock()) is False


def test_dead_letter_has_change_permission_returns_false() -> None:
    admin_instance = admin.site._registry[CeleryOutboxDeadLetter]

    assert admin_instance.has_change_permission(request=MagicMock()) is False


def test_dead_letter_has_delete_permission_returns_false() -> None:
    admin_instance = admin.site._registry[CeleryOutboxDeadLetter]

    assert admin_instance.has_delete_permission(request=MagicMock()) is False


def test_dead_letter_list_display() -> None:
    admin_instance = admin.site._registry[CeleryOutboxDeadLetter]

    expected = ['id', 'task_name', 'task_id', 'retries', 'schema_version', 'created_at', 'dead_at']
    assert admin_instance.list_display == expected


def test_dead_letter_list_filter() -> None:
    admin_instance = admin.site._registry[CeleryOutboxDeadLetter]

    assert admin_instance.list_filter == ['task_name', 'failure_reason', 'dead_at', 'schema_version']


def test_dead_letter_search_fields() -> None:
    admin_instance = admin.site._registry[CeleryOutboxDeadLetter]

    assert admin_instance.search_fields == ['task_id', 'task_name', 'failure_reason']


def test_dead_letter_actions_include_retry_selected() -> None:
    admin_instance: CeleryOutboxDeadLetterAdmin = admin.site._registry[CeleryOutboxDeadLetter]  # type: ignore[assignment]

    assert 'retry_selected' in admin_instance.actions


def test_dead_letter_readonly_fields_use_display_options() -> None:
    dead_letter_admin = admin.site._registry[CeleryOutboxDeadLetter]

    assert 'display_options' in dead_letter_admin.readonly_fields
    assert 'options' not in dead_letter_admin.readonly_fields


@pytest.mark.django_db
def test_dead_letter_retry_selected_moves_to_outbox(f_user: 'User') -> None:
    dead1 = CeleryOutboxDeadLetterFactory.create(
        task_id='task-retry-1',
        task_name='app.tasks.retry_task',
        args=[1, 2],
        kwargs={'key': 'val'},
        redacted_args=['[REDACTED]', 2],
        redacted_kwargs={'key': '[REDACTED]'},
        options={'queue': 'default'},
        sentry_trace_id='trace-1',
        sentry_baggage='baggage-1',
        structlog_context='ctx-1',
    )
    dead2 = CeleryOutboxDeadLetterFactory.create(
        task_id='task-retry-2',
        task_name='app.tasks.retry_task_2',
    )

    admin_instance: CeleryOutboxDeadLetterAdmin = admin.site._registry[CeleryOutboxDeadLetter]  # type: ignore[assignment]
    queryset = CeleryOutboxDeadLetter.objects.filter(pk__in=[dead1.pk, dead2.pk])
    m_request = MagicMock()
    m_request.user = f_user

    admin_instance.retry_selected(m_request, queryset)

    assert CeleryOutboxDeadLetter.objects.count() == 0
    assert CeleryOutbox.objects.count() == 2

    outbox1 = CeleryOutbox.objects.get(task_id='task-retry-1')
    assert outbox1.task_name == 'app.tasks.retry_task'
    assert outbox1.args == [1, 2]
    assert outbox1.kwargs == {'key': 'val'}
    assert outbox1.redacted_args == ['[REDACTED]', 2]
    assert outbox1.redacted_kwargs == {'key': '[REDACTED]'}
    assert outbox1.options == {'queue': 'default'}
    assert outbox1.sentry_trace_id == 'trace-1'
    assert outbox1.sentry_baggage == 'baggage-1'
    assert outbox1.structlog_context == 'ctx-1'
    assert outbox1.retries == 0
    assert outbox1.retry_after is None
    assert outbox1.updated_at is None


@pytest.mark.django_db
def test_dead_letter_retry_selected_shows_success_message(f_user: 'User') -> None:
    CeleryOutboxDeadLetterFactory.create()

    admin_instance: CeleryOutboxDeadLetterAdmin = admin.site._registry[CeleryOutboxDeadLetter]  # type: ignore[assignment]
    queryset = CeleryOutboxDeadLetter.objects.all()
    m_request = MagicMock()
    m_request.user = f_user

    with patch.object(type(admin_instance), 'message_user') as m_message_user:
        admin_instance.retry_selected(m_request, queryset)

    m_message_user.assert_called_once_with(
        m_request,
        '1 dead-lettered message(s) moved back to outbox.',
        messages.SUCCESS,
    )


@pytest.mark.django_db
def test_dead_letter_retry_selected_preserves_schema_version(f_user: 'User') -> None:
    dead = CeleryOutboxDeadLetterFactory.create(
        task_id='task-with-version',
        task_name='app.tasks.versioned',
        schema_version=2,
    )

    admin_instance: CeleryOutboxDeadLetterAdmin = admin.site._registry[CeleryOutboxDeadLetter]  # type: ignore[assignment]
    queryset = CeleryOutboxDeadLetter.objects.filter(pk=dead.pk)
    m_request = MagicMock()
    m_request.user = f_user

    admin_instance.retry_selected(m_request, queryset)

    outbox = CeleryOutbox.objects.get(task_id='task-with-version')
    assert outbox.schema_version == 2


@pytest.mark.django_db
def test_reset_retries_creates_log_entries(f_user: 'User') -> None:
    from django.contrib.admin.models import CHANGE, LogEntry
    from django.contrib.contenttypes.models import ContentType

    entry1 = CeleryOutboxFactory.create(retries=5, retry_after=timezone.now(), updated_at=timezone.now())
    entry2 = CeleryOutboxFactory.create(retries=3, retry_after=timezone.now(), updated_at=timezone.now())

    admin_instance: CeleryOutboxAdmin = admin.site._registry[CeleryOutbox]  # type: ignore[assignment]
    queryset = CeleryOutbox.objects.filter(pk__in=[entry1.pk, entry2.pk])
    m_request = MagicMock()
    m_request.user = f_user

    admin_instance.reset_retries(m_request, queryset)

    content_type = ContentType.objects.get_for_model(CeleryOutbox)
    logs = LogEntry.objects.filter(content_type=content_type).order_by('object_id')
    assert logs.count() == 2

    log1 = logs.get(object_id=str(entry1.pk))
    assert log1.user_id == f_user.pk
    assert log1.action_flag == CHANGE
    assert log1.change_message == 'Reset retries via admin action'

    log2 = logs.get(object_id=str(entry2.pk))
    assert log2.user_id == f_user.pk
    assert log2.action_flag == CHANGE


@pytest.mark.django_db
def test_retry_selected_creates_log_entries_for_dead_letter(f_user: 'User') -> None:
    from django.contrib.admin.models import DELETION, LogEntry
    from django.contrib.contenttypes.models import ContentType

    dead1 = CeleryOutboxDeadLetterFactory.create(task_id='audit-task-1')
    dead2 = CeleryOutboxDeadLetterFactory.create(task_id='audit-task-2')
    dead1_pk = dead1.pk
    dead2_pk = dead2.pk

    admin_instance: CeleryOutboxDeadLetterAdmin = admin.site._registry[CeleryOutboxDeadLetter]  # type: ignore[assignment]
    queryset = CeleryOutboxDeadLetter.objects.filter(pk__in=[dead1_pk, dead2_pk])
    m_request = MagicMock()
    m_request.user = f_user

    admin_instance.retry_selected(m_request, queryset)

    content_type = ContentType.objects.get_for_model(CeleryOutboxDeadLetter)
    logs = LogEntry.objects.filter(content_type=content_type).order_by('object_id')
    assert logs.count() == 2

    log1 = logs.get(object_id=str(dead1_pk))
    assert log1.user_id == f_user.pk
    assert log1.action_flag == DELETION
    assert log1.change_message == 'Retried via admin action (moved back to outbox)'

    log2 = logs.get(object_id=str(dead2_pk))
    assert log2.user_id == f_user.pk
    assert log2.action_flag == DELETION


@pytest.mark.django_db
def test_display_args_prefers_redacted_payload() -> None:
    admin_instance: CeleryOutboxAdmin = admin.site._registry[CeleryOutbox]  # type: ignore[assignment]
    entry = CeleryOutboxFactory.build(args=[1], redacted_args=['[REDACTED]'])

    assert admin_instance.display_args(entry) == ['[REDACTED]']


@pytest.mark.django_db
def test_dead_letter_display_kwargs_prefers_redacted_payload() -> None:
    admin_instance: CeleryOutboxDeadLetterAdmin = admin.site._registry[CeleryOutboxDeadLetter]  # type: ignore[assignment]
    entry = CeleryOutboxDeadLetterFactory.build(kwargs={'email': 'user@example.com'}, redacted_kwargs={'email': '[REDACTED]'})

    assert admin_instance.display_kwargs(entry) == {'email': '[REDACTED]'}
