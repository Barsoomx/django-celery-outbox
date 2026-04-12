from typing import Any

from django.core.management.base import BaseCommand, CommandParser

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
            default=10,
        )

    def handle(self, *args: Any, **options: Any) -> None:
        stats = get_queue_stats(top_n=options['top'])

        if options['format'] == 'json':
            self.stdout.write(stats.to_json())
        else:
            self.stdout.write(stats.to_text())
