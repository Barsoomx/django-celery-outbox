from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('django_celery_outbox', '0003_redacted_payload_fields'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='celeryoutbox',
            index=models.Index(fields=['retry_after', 'id'], name='celery_outbox_retry_idx'),
        ),
        migrations.AddIndex(
            model_name='celeryoutbox',
            index=models.Index(
                fields=['updated_at', 'id'],
                condition=models.Q(retry_after__isnull=True),
                name='celery_outbox_stale_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='celeryoutboxdeadletter',
            index=models.Index(fields=['dead_at'], name='celery_outbox_dlq_dead_at_idx'),
        ),
        migrations.AddIndex(
            model_name='celeryoutboxdeadletter',
            index=models.Index(fields=['created_at'], name='celery_outbox_dlq_created_idx'),
        ),
    ]
