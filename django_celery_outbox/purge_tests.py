from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from django_celery_outbox.factories import CeleryOutboxDeadLetterFactory
from django_celery_outbox.models import CeleryOutboxDeadLetter
from django_celery_outbox.purge import PurgeResult, parse_duration, purge_dead_letter


class TestParseDuration:
    def test_parses_seconds(self) -> None:
        result = parse_duration('90s')

        assert result == timedelta(seconds=90)

    def test_parses_minutes(self) -> None:
        result = parse_duration('30m')

        assert result == timedelta(minutes=30)

    def test_parses_hours(self) -> None:
        result = parse_duration('6h')

        assert result == timedelta(hours=6)

    def test_parses_days(self) -> None:
        result = parse_duration('30d')

        assert result == timedelta(days=30)

    def test_parses_weeks(self) -> None:
        result = parse_duration('2w')

        assert result == timedelta(weeks=2)

    def test_raises_on_invalid_unit(self) -> None:
        with pytest.raises(ValueError, match='Invalid duration format'):
            parse_duration('30x')

    def test_raises_on_empty_string(self) -> None:
        with pytest.raises(ValueError, match='Invalid duration format'):
            parse_duration('')

    def test_raises_on_missing_number(self) -> None:
        with pytest.raises(ValueError, match='Invalid duration format'):
            parse_duration('d')

    def test_raises_on_missing_unit(self) -> None:
        with pytest.raises(ValueError, match='Invalid duration format'):
            parse_duration('30')


class TestPurgeResult:
    def test_stores_deleted_count_and_task_names(self) -> None:
        result = PurgeResult(
            deleted_count=10,
            task_names={'myapp.task1': 5, 'myapp.task2': 5},
        )

        assert result.deleted_count == 10
        assert result.task_names == {'myapp.task1': 5, 'myapp.task2': 5}

    def test_empty_result(self) -> None:
        result = PurgeResult(deleted_count=0, task_names={})

        assert result.deleted_count == 0
        assert result.task_names == {}


@pytest.mark.django_db
class TestPurgeDeadLetterOlderThanDead:
    def test_deletes_records_older_than_specified_dead_at(self) -> None:
        now = timezone.now()
        with patch('django.utils.timezone.now', return_value=now):
            old_record = CeleryOutboxDeadLetterFactory(task_name='myapp.old_task')
        CeleryOutboxDeadLetter.objects.filter(pk=old_record.pk).update(  # type: ignore[attr-defined]
            dead_at=now - timedelta(days=31)
        )
        with patch('django.utils.timezone.now', return_value=now):
            new_record = CeleryOutboxDeadLetterFactory(task_name='myapp.new_task')

        result = purge_dead_letter(older_than_dead=timedelta(days=30))

        assert result.deleted_count == 1
        assert result.task_names == {'myapp.old_task': 1}
        assert not CeleryOutboxDeadLetter.objects.filter(pk=old_record.pk).exists()  # type: ignore[attr-defined]
        assert CeleryOutboxDeadLetter.objects.filter(pk=new_record.pk).exists()  # type: ignore[attr-defined]

    def test_returns_empty_result_when_no_matches(self) -> None:
        now = timezone.now()
        with patch('django.utils.timezone.now', return_value=now):
            CeleryOutboxDeadLetterFactory()

        result = purge_dead_letter(older_than_dead=timedelta(days=30))

        assert result.deleted_count == 0
        assert result.task_names == {}

    def test_aggregates_counts_by_task_name(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            r1 = CeleryOutboxDeadLetterFactory(task_name='myapp.task_a')
            r2 = CeleryOutboxDeadLetterFactory(task_name='myapp.task_a')
            r3 = CeleryOutboxDeadLetterFactory(task_name='myapp.task_b')
        CeleryOutboxDeadLetter.objects.filter(pk__in=[r1.pk, r2.pk, r3.pk]).update(  # type: ignore[attr-defined]
            dead_at=old_time
        )

        result = purge_dead_letter(older_than_dead=timedelta(days=30))

        assert result.deleted_count == 3
        assert result.task_names == {'myapp.task_a': 2, 'myapp.task_b': 1}


@pytest.mark.django_db
class TestPurgeDeadLetterOlderThanCreated:
    def test_deletes_records_older_than_specified_created_at(self) -> None:
        now = timezone.now()
        old_record = CeleryOutboxDeadLetterFactory(
            task_name='myapp.old_task',
            created_at=now - timedelta(days=91),
        )
        new_record = CeleryOutboxDeadLetterFactory(
            task_name='myapp.new_task',
            created_at=now - timedelta(days=10),
        )

        result = purge_dead_letter(older_than_created=timedelta(days=90))

        assert result.deleted_count == 1
        assert result.task_names == {'myapp.old_task': 1}
        assert not CeleryOutboxDeadLetter.objects.filter(pk=old_record.pk).exists()
        assert CeleryOutboxDeadLetter.objects.filter(pk=new_record.pk).exists()

    def test_combines_with_older_than_dead_using_and_logic(self) -> None:
        now = timezone.now()
        old_dead = now - timedelta(days=31)
        old_created = now - timedelta(days=91)
        new_created = now - timedelta(days=10)

        with patch('django.utils.timezone.now', return_value=now):
            both_old = CeleryOutboxDeadLetterFactory(
                task_name='myapp.both_old',
                created_at=old_created,
            )
            only_dead_old = CeleryOutboxDeadLetterFactory(
                task_name='myapp.only_dead_old',
                created_at=new_created,
            )
            only_created_old = CeleryOutboxDeadLetterFactory(
                task_name='myapp.only_created_old',
                created_at=old_created,
            )
        CeleryOutboxDeadLetter.objects.filter(pk=both_old.pk).update(dead_at=old_dead)
        CeleryOutboxDeadLetter.objects.filter(pk=only_dead_old.pk).update(dead_at=old_dead)

        result = purge_dead_letter(
            older_than_dead=timedelta(days=30),
            older_than_created=timedelta(days=90),
        )

        assert result.deleted_count == 1
        assert result.task_names == {'myapp.both_old': 1}
        assert not CeleryOutboxDeadLetter.objects.filter(pk=both_old.pk).exists()
        assert CeleryOutboxDeadLetter.objects.filter(pk=only_dead_old.pk).exists()
        assert CeleryOutboxDeadLetter.objects.filter(pk=only_created_old.pk).exists()
