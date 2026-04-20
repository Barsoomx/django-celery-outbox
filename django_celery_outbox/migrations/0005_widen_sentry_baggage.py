from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('django_celery_outbox', '0004_queue_selector_indexes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='celeryoutbox',
            name='sentry_baggage',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='celeryoutboxdeadletter',
            name='sentry_baggage',
            field=models.TextField(blank=True, null=True),
        ),
    ]
