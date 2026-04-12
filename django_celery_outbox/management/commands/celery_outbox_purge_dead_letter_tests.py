from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from django_celery_outbox.purge import PurgeResult


class TestPurgeDeadLetterCommand:
    def test_requires_at_least_one_older_than_flag(self) -> None:
        with pytest.raises(CommandError, match='No retention policy specified'):
            call_command('celery_outbox_purge_dead_letter')

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_passes_older_than_dead_to_purge(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})
        call_command('celery_outbox_purge_dead_letter', older_than_dead='30d')
        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=30),
            older_than_created=None,
            task_name_pattern=None,
            dry_run=False,
        )

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_passes_older_than_created_to_purge(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})
        call_command('celery_outbox_purge_dead_letter', older_than_created='90d')
        m_purge.assert_called_once_with(
            older_than_dead=None,
            older_than_created=timedelta(days=90),
            task_name_pattern=None,
            dry_run=False,
        )

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_passes_both_filters_to_purge(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})
        call_command('celery_outbox_purge_dead_letter', older_than_dead='7d', older_than_created='30d')
        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=7),
            older_than_created=timedelta(days=30),
            task_name_pattern=None,
            dry_run=False,
        )

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_passes_task_name_pattern_to_purge(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})
        call_command('celery_outbox_purge_dead_letter', older_than_dead='30d', task_name='myapp.tasks.*')
        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=30),
            older_than_created=None,
            task_name_pattern='myapp.tasks.*',
            dry_run=False,
        )

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_passes_dry_run_flag(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})
        call_command('celery_outbox_purge_dead_letter', older_than_dead='30d', dry_run=True)
        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=30),
            older_than_created=None,
            task_name_pattern=None,
            dry_run=True,
        )

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_outputs_deleted_count(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=142, task_names={'myapp.task1': 100, 'myapp.task2': 42})
        out = StringIO()
        call_command('celery_outbox_purge_dead_letter', older_than_dead='30d', stdout=out)
        output = out.getvalue()
        assert 'Deleted 142 dead letter records' in output
        assert 'myapp.task1: 100' in output
        assert 'myapp.task2: 42' in output

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_outputs_dry_run_message(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=10, task_names={'myapp.task': 10})
        out = StringIO()
        call_command('celery_outbox_purge_dead_letter', older_than_dead='30d', dry_run=True, stdout=out)
        output = out.getvalue()
        assert 'Would delete 10 dead letter records' in output

    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_outputs_no_matches_message(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})
        out = StringIO()
        call_command('celery_outbox_purge_dead_letter', older_than_dead='30d', stdout=out)
        output = out.getvalue()
        assert 'No dead letter records match the specified criteria' in output


class TestPurgeDeadLetterCommandSettings:
    @override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '30d'})
    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_uses_settings_when_no_flags(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})
        call_command('celery_outbox_purge_dead_letter')
        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=30),
            older_than_created=None,
            task_name_pattern=None,
            dry_run=False,
        )

    @override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '7d', 'older_than_created': '90d', 'task_name': 'myapp.*'})
    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_uses_all_settings_fields(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})
        call_command('celery_outbox_purge_dead_letter')
        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=7),
            older_than_created=timedelta(days=90),
            task_name_pattern='myapp.*',
            dry_run=False,
        )

    @override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '7d'})
    @patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
    def test_cli_flags_override_settings(self, m_purge: MagicMock) -> None:
        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})
        call_command('celery_outbox_purge_dead_letter', older_than_dead='30d')
        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=30),
            older_than_created=None,
            task_name_pattern=None,
            dry_run=False,
        )
