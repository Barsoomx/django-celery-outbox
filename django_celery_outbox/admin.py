from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, DELETION, LogEntry
from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter


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
        'options',
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

    def changelist_view(self, request: HttpRequest, extra_context: dict | None = None) -> HttpResponse:
        extra_context = extra_context or {}
        pending_qs = CeleryOutbox.objects.filter(updated_at__isnull=True)
        extra_context['pending_count'] = pending_qs.count()
        extra_context['failed_count'] = CeleryOutbox.objects.filter(retries__gt=0).count()
        extra_context['total_count'] = CeleryOutbox.objects.count()
        oldest = pending_qs.order_by('created_at').values_list('created_at', flat=True).first()
        if oldest:
            extra_context['oldest_pending'] = timezone.now() - oldest
        else:
            extra_context['oldest_pending'] = None

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
        'options',
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

    @admin.action(description='Retry selected dead-lettered messages')
    def retry_selected(self, request: HttpRequest, queryset: QuerySet[CeleryOutboxDeadLetter]) -> None:
        content_type = ContentType.objects.get_for_model(CeleryOutboxDeadLetter)
        dead_letter_entries = list(queryset.values_list('pk', 'task_id'))
        user_id = _get_log_entry_user_id(request)
        with transaction.atomic():
            outbox_messages = [
                CeleryOutbox(
                    task_id=dl.task_id,
                    task_name=dl.task_name,
                    args=dl.args,
                    kwargs=dl.kwargs,
                    redacted_args=dl.redacted_args,
                    redacted_kwargs=dl.redacted_kwargs,
                    options=dl.options,
                    schema_version=dl.schema_version,
                    sentry_trace_id=dl.sentry_trace_id,
                    sentry_baggage=dl.sentry_baggage,
                    structlog_context=dl.structlog_context,
                )
                for dl in queryset
            ]
            CeleryOutbox.objects.bulk_create(outbox_messages)
            count = len(outbox_messages)
            queryset.delete()

            for pk, task_id in dead_letter_entries:
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
