from datetime import timedelta

from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, DELETION, LogEntry
from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse

from django_celery_outbox._settings import load_stale_timeout_seconds_setting
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter
from django_celery_outbox.replay import replay_dead_letters
from django_celery_outbox.stats import get_queue_stats


def _get_log_entry_user_id(request: HttpRequest) -> int:
    if isinstance(request.user, AnonymousUser) or request.user.pk is None:
        raise ValueError('Admin actions require an authenticated user')

    return request.user.pk


@admin.register(CeleryOutbox)
class CeleryOutboxAdmin(admin.ModelAdmin):
    change_list_template = 'admin/django_celery_outbox/celeryoutbox/change_list.html'
    list_display = [
        'id',
        'task_name',
        'task_id',
        'retries',
        'schema_version',
        'created_at',
        'updated_at',
    ]
    list_filter = ['task_name', 'retries', 'schema_version']
    search_fields = ['task_id', 'task_name']
    readonly_fields = [
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
    actions = ['reset_retries']

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False

    @admin.display(description='args')
    def display_args(self, obj: CeleryOutbox) -> list:
        return obj.inspection_args

    @admin.display(description='kwargs')
    def display_kwargs(self, obj: CeleryOutbox) -> dict:
        return obj.inspection_kwargs

    @admin.display(description='options')
    def display_options(self, obj: CeleryOutbox) -> dict:
        return obj.inspection_options

    def changelist_view(self, request: HttpRequest, extra_context: dict | None = None) -> HttpResponse:
        extra_context = extra_context or {}
        stale_timeout = timedelta(seconds=load_stale_timeout_seconds_setting())
        stats = get_queue_stats(top_n=0, stale_timeout=stale_timeout)
        extra_context['live_backlog'] = stats.queue_depth
        extra_context['never_attempted'] = CeleryOutbox.objects.filter(updated_at__isnull=True).count()
        extra_context['failed_count'] = CeleryOutbox.objects.filter(retries__gt=0).count()
        extra_context['total_count'] = CeleryOutbox.objects.count()
        extra_context['oldest_pending'] = timedelta(seconds=stats.oldest_pending_seconds) if stats.oldest_pending_seconds is not None else None

        return super().changelist_view(request, extra_context=extra_context)

    @admin.action(description='Reset retries for selected messages')
    def reset_retries(self, request: HttpRequest, queryset: QuerySet[CeleryOutbox]) -> None:
        content_type = ContentType.objects.get_for_model(CeleryOutbox)
        entries = list(queryset.values_list('pk', 'task_id'))
        user_id = _get_log_entry_user_id(request)

        with transaction.atomic():
            count = queryset.update(retries=0, retry_after=None, updated_at=None)

            for pk, task_id in entries:
                LogEntry.objects.create(
                    user_id=user_id,
                    content_type_id=content_type.pk,
                    object_id=str(pk),
                    object_repr=f'CeleryOutbox {task_id}',
                    action_flag=CHANGE,
                    change_message='Reset retries via admin action',
                )

        self.message_user(
            request,
            f'{count} message(s) had retries reset.',
            messages.SUCCESS,
        )


@admin.register(CeleryOutboxDeadLetter)
class CeleryOutboxDeadLetterAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'task_name',
        'task_id',
        'retries',
        'schema_version',
        'created_at',
        'dead_at',
    ]
    list_filter = ['task_name', 'failure_reason', 'dead_at', 'schema_version']
    search_fields = ['task_id', 'task_name', 'failure_reason']
    readonly_fields = [
        'id',
        'task_name',
        'task_id',
        'display_args',
        'display_kwargs',
        'display_options',
        'retries',
        'schema_version',
        'created_at',
        'dead_at',
        'sentry_trace_id',
        'sentry_baggage',
        'structlog_context',
        'failure_reason',
    ]
    actions = ['retry_selected']

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False

    @admin.display(description='args')
    def display_args(self, obj: CeleryOutboxDeadLetter) -> list:
        return obj.inspection_args

    @admin.display(description='kwargs')
    def display_kwargs(self, obj: CeleryOutboxDeadLetter) -> dict:
        return obj.inspection_kwargs

    @admin.display(description='options')
    def display_options(self, obj: CeleryOutboxDeadLetter) -> dict:
        return obj.inspection_options

    @admin.action(description='Retry selected dead-lettered messages')
    def retry_selected(self, request: HttpRequest, queryset: QuerySet[CeleryOutboxDeadLetter]) -> None:
        content_type = ContentType.objects.get_for_model(CeleryOutboxDeadLetter)
        dead_letter_entries = list(queryset.values_list('pk', 'task_id'))
        dead_letter_ids = [pk for pk, _task_id in dead_letter_entries]
        user_id = _get_log_entry_user_id(request)
        with transaction.atomic():
            count = replay_dead_letters(dead_letter_ids)
            remaining_ids = set(CeleryOutboxDeadLetter.objects.filter(pk__in=dead_letter_ids).values_list('pk', flat=True))

            for pk, task_id in dead_letter_entries:
                if pk in remaining_ids:
                    continue
                LogEntry.objects.create(
                    user_id=user_id,
                    content_type_id=content_type.pk,
                    object_id=str(pk),
                    object_repr=f'CeleryOutboxDeadLetter {task_id}',
                    action_flag=DELETION,
                    change_message='Retried via admin action (moved back to outbox)',
                )

        self.message_user(
            request,
            f'{count} dead-lettered message(s) moved back to outbox.',
            messages.SUCCESS,
        )
