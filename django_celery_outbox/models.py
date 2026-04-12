from django.db import models


class CeleryOutbox(models.Model):
    objects = models.Manager()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True)
    retries = models.SmallIntegerField(default=0)
    retry_after = models.DateTimeField(null=True, db_index=True)

    task_id = models.CharField(max_length=255, db_index=True)
    task_name = models.CharField(max_length=255, db_index=True)
    args = models.JSONField(default=list)
    kwargs = models.JSONField(default=dict)
    redacted_args = models.JSONField(null=True, blank=True)
    redacted_kwargs = models.JSONField(null=True, blank=True)
    options = models.JSONField(default=dict)

    sentry_trace_id = models.CharField(max_length=512, null=True, blank=True)
    sentry_baggage = models.CharField(max_length=2048, null=True, blank=True)
    structlog_context = models.TextField(null=True, blank=True)
    schema_version = models.SmallIntegerField(default=1)

    class Meta:
        db_table = 'celery_outbox'
        verbose_name = 'CeleryOutbox'
        verbose_name_plural = 'CeleryOutbox'
        indexes = [
            models.Index(
                fields=['id'],
                condition=models.Q(updated_at__isnull=True),
                name='celery_outbox_pending_idx',
            ),
        ]

    def __str__(self) -> str:
        return f'<CeleryOutbox id={self.id} task_name={self.task_name} task_id={self.task_id} retries={self.retries}>'

    @property
    def inspection_args(self) -> list:
        return self.redacted_args if self.redacted_args is not None else self.args

    @property
    def inspection_kwargs(self) -> dict:
        return self.redacted_kwargs if self.redacted_kwargs is not None else self.kwargs


class CeleryOutboxDeadLetter(models.Model):
    objects = models.Manager()

    created_at = models.DateTimeField()
    dead_at = models.DateTimeField(auto_now_add=True)
    retries = models.SmallIntegerField(default=0)

    task_id = models.CharField(max_length=255, db_index=True)
    task_name = models.CharField(max_length=255, db_index=True)
    args = models.JSONField(default=list)
    kwargs = models.JSONField(default=dict)
    redacted_args = models.JSONField(null=True, blank=True)
    redacted_kwargs = models.JSONField(null=True, blank=True)
    options = models.JSONField(default=dict)

    sentry_trace_id = models.CharField(max_length=512, null=True, blank=True)
    sentry_baggage = models.CharField(max_length=2048, null=True, blank=True)
    structlog_context = models.TextField(null=True, blank=True)

    failure_reason = models.TextField(null=True, blank=True)
    schema_version = models.SmallIntegerField(default=1)

    class Meta:
        db_table = 'celery_outbox_dead_letter'
        verbose_name = 'CeleryOutboxDeadLetter'
        verbose_name_plural = 'CeleryOutboxDeadLetter'

    @property
    def inspection_args(self) -> list:
        return self.redacted_args if self.redacted_args is not None else self.args

    @property
    def inspection_kwargs(self) -> dict:
        return self.redacted_kwargs if self.redacted_kwargs is not None else self.kwargs
