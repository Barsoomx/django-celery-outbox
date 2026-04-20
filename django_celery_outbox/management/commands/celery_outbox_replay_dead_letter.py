from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_celery_outbox.replay import replay_dead_letters


class Command(BaseCommand):
    help = 'Replay dead letter records back into the outbox'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument('dead_letter_ids', nargs='+', type=int)
        parser.add_argument('--limit', type=int, default=None)

    def handle(self, *args: Any, **options: Any) -> None:
        limit = options['limit']
        if limit is not None and limit <= 0:
            raise CommandError('--limit must be greater than 0')

        replayed = replay_dead_letters(options['dead_letter_ids'], limit=limit)
        self.stdout.write(f'Replayed {replayed} dead letter record(s).')
