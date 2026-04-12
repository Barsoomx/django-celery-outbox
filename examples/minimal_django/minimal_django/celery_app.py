import os

from django_celery_outbox import OutboxCelery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'minimal_django.settings')

app = OutboxCelery('minimal_django')
app.config_from_object('minimal_django.celeryconfig')
app.autodiscover_tasks()
