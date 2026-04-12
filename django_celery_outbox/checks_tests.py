from unittest.mock import MagicMock, patch

from django_celery_outbox.checks import check_database_supports_skip_locked


def test_check_returns_error_when_skip_locked_not_supported() -> None:
    m_connection = MagicMock()
    m_connection.features.has_select_for_update_skip_locked = False
    m_connection.vendor = 'sqlite'

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.CeleryOutbox') as m_model:
            m_model.objects.db = 'default'
            errors = check_database_supports_skip_locked(None)

    assert len(errors) == 1
    assert errors[0].id == 'celery_outbox.E001'
    assert 'SELECT FOR UPDATE SKIP LOCKED' in errors[0].msg


def test_check_passes_when_skip_locked_supported() -> None:
    m_connection = MagicMock()
    m_connection.features.has_select_for_update_skip_locked = True

    with patch('django_celery_outbox.checks.connections', {'default': m_connection}):
        with patch('django_celery_outbox.checks.CeleryOutbox') as m_model:
            m_model.objects.db = 'default'
            errors = check_database_supports_skip_locked(None)

    assert errors == []
