from django.apps import AppConfig


class DjangoCeleryOutboxConfig(AppConfig):
    name = 'django_celery_outbox'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self) -> None:
        from django_celery_outbox import checks  # noqa: F401
