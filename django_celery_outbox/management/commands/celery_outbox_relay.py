from typing import Any

from celery import Celery
from django.core.management.base import BaseCommand, CommandParser

from django_celery_outbox._settings import load_celery_app_setting
from django_celery_outbox.relay import Relay, RelayConfig


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
            '--stale-timeout-seconds',
            type=int,
            default=300,
        )
        parser.add_argument(
            '--send-timeout',
            type=float,
            default=10.0,
        )
        parser.add_argument(
            '--shutdown-timeout',
            type=float,
            default=30.0,
        )
        parser.add_argument(
            '--broker-outage-cooldown',
            type=float,
            default=30.0,
        )
        parser.add_argument(
            '--max-backoff',
            type=float,
            default=3600.0,
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
            config=RelayConfig.from_options(options),
        )
        relay.start()

    @staticmethod
    def _get_celery_app() -> Celery:
        return load_celery_app_setting()
