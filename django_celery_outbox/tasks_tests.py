from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from django_celery_outbox.purge import PurgeResult


class TestPurgeDeadLetterTask:
    @override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '30d'})
    @patch('django_celery_outbox.tasks.purge_dead_letter')
    def test_calls_purge_with_settings(self, m_purge: MagicMock) -> None:
        from django_celery_outbox.tasks import purge_dead_letter_task

        m_purge.return_value = PurgeResult(deleted_count=5, task_names={'app.task': 5})

        result = purge_dead_letter_task()

        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=30),
            older_than_created=None,
            task_name_pattern=None,
            dry_run=False,
        )
        assert result == {'deleted_count': 5, 'task_names': {'app.task': 5}}

    @override_settings(CELERY_OUTBOX_DLQ_RETENTION={
        'older_than_dead': '7d',
        'older_than_created': '90d',
        'task_name': 'myapp.*',
    })
    @patch('django_celery_outbox.tasks.purge_dead_letter')
    def test_uses_all_settings_fields(self, m_purge: MagicMock) -> None:
        from django_celery_outbox.tasks import purge_dead_letter_task

        m_purge.return_value = PurgeResult(deleted_count=0, task_names={})

        purge_dead_letter_task()

        m_purge.assert_called_once_with(
            older_than_dead=timedelta(days=7),
            older_than_created=timedelta(days=90),
            task_name_pattern='myapp.*',
            dry_run=False,
        )

    def test_raises_when_no_settings(self) -> None:
        from django_celery_outbox.tasks import purge_dead_letter_task

        with pytest.raises(ValueError, match='CELERY_OUTBOX_DLQ_RETENTION setting is required'):
            purge_dead_letter_task()

    @override_settings(CELERY_OUTBOX_DLQ_RETENTION={})
    def test_raises_when_settings_empty(self) -> None:
        from django_celery_outbox.tasks import purge_dead_letter_task

        with pytest.raises(ValueError, match='CELERY_OUTBOX_DLQ_RETENTION must specify'):
            purge_dead_letter_task()
