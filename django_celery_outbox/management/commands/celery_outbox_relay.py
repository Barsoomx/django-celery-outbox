import importlib
from typing import Any

from celery import Celery
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from django_celery_outbox.relay import Relay


class Command(BaseCommand):
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
        )
        parser.add_argument(
            '--idle-time',
            type=float,
            default=1.0,
        )
        parser.add_argument(
            '--backoff-time',
            type=int,
            default=120,
        )
        parser.add_argument(
            '--max-retries',
            type=int,
            default=5,
        )
        parser.add_argument(
            '--liveness-file',
            type=str,
            default=None,
        )

    def handle(self, *args: Any, **options: Any) -> None:
        app = self._get_celery_app()
        relay = Relay(
            app=app,
            batch_size=options['batch_size'],
            idle_time=options['idle_time'],
            backoff_time=options['backoff_time'],
            max_retries=options['max_retries'],
            liveness_file=options['liveness_file'],
        )
        relay.start()

    @staticmethod
    def _get_celery_app() -> Celery:
        app_path = getattr(settings, 'CELERY_OUTBOX_APP', None)
        if not app_path:
            raise ValueError('CELERY_OUTBOX_APP setting is required. Set it to dotted path of your Celery app instance, e.g. "myproject.celery.app"')

        try:
            module_path, attr_name = app_path.rsplit('.', 1)
        except ValueError:
            raise ValueError(f'CELERY_OUTBOX_APP must be a dotted path (e.g. "myproject.celery.app"), got: "{app_path}"')

        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
