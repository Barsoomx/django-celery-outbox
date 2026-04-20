from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_celery_outbox._settings import load_dlq_retention_setting
from django_celery_outbox.purge import PurgeResult, parse_duration, purge_dead_letter


class Command(BaseCommand):
    help = 'Purge old dead letter records from celery_outbox_dead_letter table'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            '--older-than-dead',
            type=str,
            default=None,
            help='Delete records where dead_at is older than specified period (e.g., 30d, 2w)',
        )
        parser.add_argument(
            '--older-than-created',
            type=str,
            default=None,
            help='Delete records where created_at is older than specified period (e.g., 90d)',
        )
        parser.add_argument(
            '--task-name',
            type=str,
            default=None,
            help='Glob pattern for filtering by task name (e.g., myapp.tasks.*)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )

    def handle(self, *args: Any, **options: Any) -> None:
        cli_has_retention = bool(options.get('older_than_dead') or options.get('older_than_created'))
        retention = {} if cli_has_retention else self._load_retention()

        try:
            older_than_dead = self._get_duration('older_than_dead', options, cli_has_retention, retention)
            older_than_created = self._get_duration('older_than_created', options, cli_has_retention, retention)
        except (TypeError, ValueError) as e:
            raise CommandError(str(e)) from e

        task_name_pattern = self._get_task_name_pattern(options, cli_has_retention, retention)
        dry_run = options['dry_run']

        if older_than_dead is None and older_than_created is None:
            raise CommandError('No retention policy specified. Use --older-than-dead or --older-than-created, or set CELERY_OUTBOX_DLQ_RETENTION')

        result = purge_dead_letter(
            older_than_dead=older_than_dead,
            older_than_created=older_than_created,
            task_name_pattern=task_name_pattern,
            dry_run=dry_run,
        )

        self._output_result(result, dry_run)

    def _load_retention(self) -> dict[str, timedelta | str | None]:
        try:
            return load_dlq_retention_setting() or {}
        except (TypeError, ValueError) as e:
            raise CommandError(str(e)) from e

    def _get_duration(
        self,
        key: str,
        options: dict[str, Any],
        cli_has_retention: bool,
        retention: dict[str, timedelta | str | None],
    ) -> timedelta | None:
        cli_value = options.get(key)
        if cli_value:
            return parse_duration(cli_value)

        if cli_has_retention:
            return None

        return retention.get(key)  # type: ignore[return-value]

    def _get_task_name_pattern(
        self,
        options: dict[str, Any],
        cli_has_retention: bool,
        retention: dict[str, timedelta | str | None],
    ) -> str | None:
        cli_value = options.get('task_name')
        if cli_value:
            return cli_value

        if cli_has_retention:
            return None

        return retention.get('task_name_pattern')  # type: ignore[return-value]

    def _output_result(self, result: PurgeResult, dry_run: bool) -> None:
        if result.deleted_count == 0:
            self.stdout.write('No dead letter records match the specified criteria.')

            return

        prefix = 'Would delete' if dry_run else 'Deleted'
        self.stdout.write(f'{prefix} {result.deleted_count} dead letter records:')
        for task_name, count in sorted(result.task_names.items()):
            self.stdout.write(f'  {task_name}: {count}')
