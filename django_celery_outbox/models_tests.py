import pytest

from django_celery_outbox.models import CeleryOutbox


@pytest.mark.django_db
def test_default_values() -> None:
    outbox = CeleryOutbox.objects.create(
        task_id='test-task-id',
        task_name='my_app.tasks.do_stuff',
    )

    assert outbox.args == []
    assert outbox.kwargs == {}
    assert outbox.options == {}
    assert outbox.retries == 0


@pytest.mark.django_db
def test_str_format() -> None:
    outbox = CeleryOutbox.objects.create(
        task_id='test-task-id',
        task_name='my_app.tasks.do_stuff',
        retries=3,
    )

    result = str(outbox)

    assert f'id={outbox.id}' in result
    assert 'task_name=my_app.tasks.do_stuff' in result
    assert 'task_id=test-task-id' in result
    assert 'retries=3' in result


def test_verbose_name() -> None:
    assert CeleryOutbox._meta.verbose_name == 'CeleryOutbox'


def test_pending_index_exists() -> None:
    index_names = [idx.name for idx in CeleryOutbox._meta.indexes]

    assert 'celery_outbox_pending_idx' in index_names


@pytest.mark.django_db
def test_created_at_auto_set() -> None:
    outbox = CeleryOutbox.objects.create(
        task_id='test-created',
        task_name='my_app.tasks.created',
    )

    assert outbox.created_at is not None


@pytest.mark.django_db
def test_updated_at_default_none() -> None:
    outbox = CeleryOutbox.objects.create(
        task_id='test-updated',
        task_name='my_app.tasks.updated',
    )

    assert outbox.updated_at is None


def test_verbose_name_plural() -> None:
    assert CeleryOutbox._meta.verbose_name_plural == 'CeleryOutbox'


def test_db_table() -> None:
    assert CeleryOutbox._meta.db_table == 'celery_outbox'
