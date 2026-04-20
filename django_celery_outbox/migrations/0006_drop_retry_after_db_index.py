from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('django_celery_outbox', '0005_widen_sentry_baggage'),
    ]

    operations = [
        migrations.AlterField(
            model_name='celeryoutbox',
            name='retry_after',
            field=models.DateTimeField(null=True),
        ),
    ]
