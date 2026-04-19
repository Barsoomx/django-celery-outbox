from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from django_celery_outbox.replay import replay_dead_letters


class Command(BaseCommand):
    help = 'Replay dead letter records back into the outbox'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument('dead_letter_ids', nargs='+', type=int)
        parser.add_argument('--limit', type=int, default=None)

    def handle(self, *args: Any, **options: Any) -> None:
        replayed = replay_dead_letters(options['dead_letter_ids'], limit=options['limit'])
        self.stdout.write(f'Replayed {replayed} dead letter record(s).')
