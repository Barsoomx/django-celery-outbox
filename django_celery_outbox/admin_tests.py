from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib import admin, messages
from django.utils import timezone

from django_celery_outbox.admin import CeleryOutboxAdmin, CeleryOutboxDeadLetterAdmin
from django_celery_outbox.factories import CeleryOutboxDeadLetterFactory, CeleryOutboxFactory
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter


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

    expected = ['id', 'task_name', 'task_id', 'retries', 'created_at', 'updated_at']
    assert admin_instance.list_display == expected


def test_list_filter() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    assert admin_instance.list_filter == ['task_name', 'retries']


def test_search_fields() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    assert admin_instance.search_fields == ['task_id', 'task_name']


def test_readonly_fields() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]

    expected = [
        'id',
        'task_name',
        'task_id',
        'args',
        'kwargs',
        'options',
        'retries',
        'created_at',
        'updated_at',
        'retry_after',
        'sentry_trace_id',
        'sentry_baggage',
        'structlog_context',
    ]
    assert admin_instance.readonly_fields == expected


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
def test_reset_retries_action() -> None:
    entry1 = CeleryOutboxFactory.create(retries=5, retry_after=timezone.now(), updated_at=timezone.now())
    entry2 = CeleryOutboxFactory.create(retries=3, retry_after=timezone.now(), updated_at=timezone.now())

    admin_instance: CeleryOutboxAdmin = admin.site._registry[CeleryOutbox]  # type: ignore[assignment]
    queryset = CeleryOutbox.objects.filter(pk__in=[entry1.pk, entry2.pk])
    m_request = MagicMock()

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

    expected = ['id', 'task_name', 'task_id', 'retries', 'created_at', 'dead_at']
    assert admin_instance.list_display == expected


def test_dead_letter_actions_include_retry_selected() -> None:
    admin_instance: CeleryOutboxDeadLetterAdmin = admin.site._registry[CeleryOutboxDeadLetter]  # type: ignore[assignment]

    assert 'retry_selected' in admin_instance.actions


@pytest.mark.django_db
def test_dead_letter_retry_selected_moves_to_outbox() -> None:
    dead1 = CeleryOutboxDeadLetterFactory.create(
        task_id='task-retry-1',
        task_name='app.tasks.retry_task',
        args=[1, 2],
        kwargs={'key': 'val'},
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

    admin_instance.retry_selected(m_request, queryset)

    assert CeleryOutboxDeadLetter.objects.count() == 0
    assert CeleryOutbox.objects.count() == 2

    outbox1 = CeleryOutbox.objects.get(task_id='task-retry-1')
    assert outbox1.task_name == 'app.tasks.retry_task'
    assert outbox1.args == [1, 2]
    assert outbox1.kwargs == {'key': 'val'}
    assert outbox1.options == {'queue': 'default'}
    assert outbox1.sentry_trace_id == 'trace-1'
    assert outbox1.sentry_baggage == 'baggage-1'
    assert outbox1.structlog_context == 'ctx-1'
    assert outbox1.retries == 0
    assert outbox1.retry_after is None
    assert outbox1.updated_at is None


@pytest.mark.django_db
def test_dead_letter_retry_selected_shows_success_message() -> None:
    CeleryOutboxDeadLetterFactory.create()

    admin_instance: CeleryOutboxDeadLetterAdmin = admin.site._registry[CeleryOutboxDeadLetter]  # type: ignore[assignment]
    queryset = CeleryOutboxDeadLetter.objects.all()
    m_request = MagicMock()

    with patch.object(type(admin_instance), 'message_user') as m_message_user:
        admin_instance.retry_selected(m_request, queryset)

    m_message_user.assert_called_once_with(
        m_request,
        '1 dead-lettered message(s) moved back to outbox.',
        messages.SUCCESS,
    )
