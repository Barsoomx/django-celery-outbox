from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='CeleryOutbox',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(null=True)),
                ('retries', models.SmallIntegerField(default=0)),
                ('retry_after', models.DateTimeField(db_index=True, null=True)),
                ('task_id', models.CharField(db_index=True, max_length=255)),
                ('task_name', models.CharField(db_index=True, max_length=255)),
                ('args', models.JSONField(default=list)),
                ('kwargs', models.JSONField(default=dict)),
                ('options', models.JSONField(default=dict)),
                ('sentry_trace_id', models.CharField(blank=True, max_length=512, null=True)),
                ('sentry_baggage', models.CharField(blank=True, max_length=2048, null=True)),
                ('structlog_context', models.TextField(blank=True, null=True)),
            ],
            options={
                'db_table': 'celery_outbox',
                'verbose_name': 'CeleryOutbox',
                'verbose_name_plural': 'CeleryOutbox',
            },
        ),
        migrations.CreateModel(
            name='CeleryOutboxDeadLetter',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField()),
                ('dead_at', models.DateTimeField(auto_now_add=True)),
                ('retries', models.SmallIntegerField(default=0)),
                ('task_id', models.CharField(db_index=True, max_length=255)),
                ('task_name', models.CharField(db_index=True, max_length=255)),
                ('args', models.JSONField(default=list)),
                ('kwargs', models.JSONField(default=dict)),
                ('options', models.JSONField(default=dict)),
                ('sentry_trace_id', models.CharField(blank=True, max_length=512, null=True)),
                ('sentry_baggage', models.CharField(blank=True, max_length=2048, null=True)),
                ('structlog_context', models.TextField(blank=True, null=True)),
                ('failure_reason', models.TextField(blank=True, null=True)),
            ],
            options={
                'db_table': 'celery_outbox_dead_letter',
                'verbose_name': 'CeleryOutboxDeadLetter',
                'verbose_name_plural': 'CeleryOutboxDeadLetter',
            },
        ),
        migrations.AddIndex(
            model_name='celeryoutbox',
            index=models.Index(
                condition=models.Q(('updated_at__isnull', True)),
                fields=['id'],
                name='celery_outbox_pending_idx',
            ),
        ),
    ]
