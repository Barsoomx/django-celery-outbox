from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_celery_outbox._settings import load_stale_timeout_seconds_setting
from django_celery_outbox.stats import get_queue_stats


class Command(BaseCommand):
    help = 'Display outbox queue statistics'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            '--format',
            choices=['text', 'json'],
            default='text',
        )
        parser.add_argument(
            '--top',
            type=int,
            default=0,
        )
        parser.add_argument(
            '--stale-timeout-seconds',
            type=int,
            default=None,
        )

    def handle(self, *args: Any, **options: Any) -> None:
        stale_timeout_seconds = options['stale_timeout_seconds']
        if stale_timeout_seconds is None:
            try:
                stale_timeout_seconds = load_stale_timeout_seconds_setting()
            except ValueError as exc:
                message = f'Invalid CELERY_OUTBOX_STALE_TIMEOUT_SECONDS: {exc} Use --stale-timeout-seconds to override it.'
                raise CommandError(message) from exc
        if stale_timeout_seconds <= 0:
            raise CommandError('stale-timeout-seconds must be > 0')

        stats = get_queue_stats(
            top_n=options['top'],
            stale_timeout=timedelta(seconds=stale_timeout_seconds),
        )

        if options['format'] == 'json':
            self.stdout.write(stats.to_json())
        else:
            self.stdout.write(stats.to_text())
