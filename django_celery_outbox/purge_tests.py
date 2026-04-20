from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from django_celery_outbox.factories import CeleryOutboxDeadLetterFactory
from django_celery_outbox.models import CeleryOutboxDeadLetter
from django_celery_outbox.purge import PurgeResult, _chunk_ordering, parse_duration, purge_dead_letter


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


class TestChunkOrdering:
    def test_prefers_dead_at_when_dead_retention_present(self) -> None:
        assert _chunk_ordering(
            older_than_dead=timedelta(days=30),
            older_than_created=None,
        ) == ('dead_at', 'pk')

    def test_uses_created_at_when_only_created_retention_present(self) -> None:
        assert _chunk_ordering(
            older_than_dead=None,
            older_than_created=timedelta(days=90),
        ) == ('created_at', 'pk')

    def test_prefers_dead_at_when_both_retentions_present(self) -> None:
        assert _chunk_ordering(
            older_than_dead=timedelta(days=30),
            older_than_created=timedelta(days=90),
        ) == ('dead_at', 'pk')

    def test_falls_back_to_primary_key_when_no_retention_dimension_is_selected(self) -> None:
        assert _chunk_ordering(
            older_than_dead=None,
            older_than_created=None,
        ) == ('pk',)


class TestPurgeDeadLetterValidation:
    def test_raises_when_no_criteria_provided(self) -> None:
        with pytest.raises(ValueError, match='At least one of older_than_dead or older_than_created'):
            purge_dead_letter()

    def test_raises_when_only_pattern_provided(self) -> None:
        with pytest.raises(ValueError, match='At least one of older_than_dead or older_than_created'):
            purge_dead_letter(task_name_pattern='myapp.*')


@pytest.mark.django_db
class TestPurgeDeadLetterOlderThanDead:
    def test_deletes_records_older_than_specified_dead_at(self) -> None:
        now = timezone.now()
        with patch('django.utils.timezone.now', return_value=now):
            old_record = CeleryOutboxDeadLetterFactory.create(task_name='myapp.old_task')
        CeleryOutboxDeadLetter.objects.filter(pk=old_record.pk).update(dead_at=now - timedelta(days=31))
        with patch('django.utils.timezone.now', return_value=now):
            new_record = CeleryOutboxDeadLetterFactory.create(task_name='myapp.new_task')

        result = purge_dead_letter(older_than_dead=timedelta(days=30))

        assert result.deleted_count == 1
        assert result.task_names == {'myapp.old_task': 1}
        assert not CeleryOutboxDeadLetter.objects.filter(pk=old_record.pk).exists()
        assert CeleryOutboxDeadLetter.objects.filter(pk=new_record.pk).exists()

    def test_returns_empty_result_when_no_matches(self) -> None:
        now = timezone.now()
        with patch('django.utils.timezone.now', return_value=now):
            CeleryOutboxDeadLetterFactory.create()

        result = purge_dead_letter(older_than_dead=timedelta(days=30))

        assert result.deleted_count == 0
        assert result.task_names == {}

    def test_aggregates_counts_by_task_name(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            r1 = CeleryOutboxDeadLetterFactory.create(task_name='myapp.task_a')
            r2 = CeleryOutboxDeadLetterFactory.create(task_name='myapp.task_a')
            r3 = CeleryOutboxDeadLetterFactory.create(task_name='myapp.task_b')
        CeleryOutboxDeadLetter.objects.filter(pk__in=[r1.pk, r2.pk, r3.pk]).update(dead_at=old_time)

        result = purge_dead_letter(older_than_dead=timedelta(days=30))

        assert result.deleted_count == 3
        assert result.task_names == {'myapp.task_a': 2, 'myapp.task_b': 1}


@pytest.mark.django_db
class TestPurgeDeadLetterOlderThanCreated:
    def test_deletes_records_older_than_specified_created_at(self) -> None:
        now = timezone.now()
        old_record = CeleryOutboxDeadLetterFactory.create(
            task_name='myapp.old_task',
            created_at=now - timedelta(days=91),
        )
        new_record = CeleryOutboxDeadLetterFactory.create(
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
            both_old = CeleryOutboxDeadLetterFactory.create(
                task_name='myapp.both_old',
                created_at=old_created,
            )
            only_dead_old = CeleryOutboxDeadLetterFactory.create(
                task_name='myapp.only_dead_old',
                created_at=new_created,
            )
            only_created_old = CeleryOutboxDeadLetterFactory.create(
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


@pytest.mark.django_db
class TestPurgeDeadLetterTaskNamePattern:
    def test_filters_by_exact_task_name(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            match = CeleryOutboxDeadLetterFactory.create(task_name='myapp.tasks.send_email')
            no_match = CeleryOutboxDeadLetterFactory.create(task_name='myapp.tasks.process_payment')
        CeleryOutboxDeadLetter.objects.filter(pk__in=[match.pk, no_match.pk]).update(dead_at=old_time)

        result = purge_dead_letter(
            older_than_dead=timedelta(days=30),
            task_name_pattern='myapp.tasks.send_email',
        )

        assert result.deleted_count == 1
        assert result.task_names == {'myapp.tasks.send_email': 1}
        assert not CeleryOutboxDeadLetter.objects.filter(pk=match.pk).exists()
        assert CeleryOutboxDeadLetter.objects.filter(pk=no_match.pk).exists()

    def test_filters_by_wildcard_pattern(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            match1 = CeleryOutboxDeadLetterFactory.create(task_name='myapp.tasks.send_email')
            match2 = CeleryOutboxDeadLetterFactory.create(task_name='myapp.tasks.send_sms')
            no_match = CeleryOutboxDeadLetterFactory.create(task_name='other.tasks.process')
        CeleryOutboxDeadLetter.objects.filter(pk__in=[match1.pk, match2.pk, no_match.pk]).update(dead_at=old_time)

        result = purge_dead_letter(
            older_than_dead=timedelta(days=30),
            task_name_pattern='myapp.tasks.send_*',
        )

        assert result.deleted_count == 2
        assert result.task_names == {'myapp.tasks.send_email': 1, 'myapp.tasks.send_sms': 1}
        assert CeleryOutboxDeadLetter.objects.filter(pk=no_match.pk).exists()

    def test_filters_by_prefix_pattern(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            match1 = CeleryOutboxDeadLetterFactory.create(task_name='myapp.tasks.a')
            match2 = CeleryOutboxDeadLetterFactory.create(task_name='myapp.other.b')
            no_match = CeleryOutboxDeadLetterFactory.create(task_name='other.tasks.c')
        CeleryOutboxDeadLetter.objects.filter(pk__in=[match1.pk, match2.pk, no_match.pk]).update(dead_at=old_time)

        result = purge_dead_letter(
            older_than_dead=timedelta(days=30),
            task_name_pattern='myapp.*',
        )

        assert result.deleted_count == 2
        assert CeleryOutboxDeadLetter.objects.filter(pk=no_match.pk).exists()

    def test_filters_by_leading_wildcard_pattern(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            match = CeleryOutboxDeadLetterFactory.create(task_name='app.tasks.send_email')
            no_match = CeleryOutboxDeadLetterFactory.create(task_name='app.other.process')
        CeleryOutboxDeadLetter.objects.filter(pk__in=[match.pk, no_match.pk]).update(dead_at=old_time)

        result = purge_dead_letter(
            older_than_dead=timedelta(days=30),
            task_name_pattern='*.tasks.*',
        )

        assert result.deleted_count == 1
        assert result.task_names == {'app.tasks.send_email': 1}
        assert CeleryOutboxDeadLetter.objects.filter(pk=no_match.pk).exists()


@pytest.mark.django_db
class TestPurgeDeadLetterDryRun:
    def test_dry_run_returns_count_without_deleting(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            record = CeleryOutboxDeadLetterFactory.create(task_name='myapp.task')
        CeleryOutboxDeadLetter.objects.filter(pk=record.pk).update(dead_at=old_time)

        result = purge_dead_letter(older_than_dead=timedelta(days=30), dry_run=True)

        assert result.deleted_count == 1
        assert result.task_names == {'myapp.task': 1}
        assert CeleryOutboxDeadLetter.objects.filter(pk=record.pk).exists()

    def test_dry_run_false_deletes_records(self) -> None:
        now = timezone.now()
        old_time = now - timedelta(days=31)
        with patch('django.utils.timezone.now', return_value=now):
            record = CeleryOutboxDeadLetterFactory.create(task_name='myapp.task')
        CeleryOutboxDeadLetter.objects.filter(pk=record.pk).update(dead_at=old_time)

        result = purge_dead_letter(older_than_dead=timedelta(days=30), dry_run=False)

        assert result.deleted_count == 1
        assert not CeleryOutboxDeadLetter.objects.filter(pk=record.pk).exists()


@pytest.mark.django_db
def test_purge_dead_letter_deletes_in_deterministic_chunks() -> None:
    now = timezone.now()
    old_time = now - timedelta(days=31)
    with patch('django.utils.timezone.now', return_value=now):
        records = CeleryOutboxDeadLetterFactory.create_batch(3, task_name='myapp.task')
    CeleryOutboxDeadLetter.objects.filter(pk__in=[row.pk for row in records]).update(dead_at=old_time)

    with patch('django_celery_outbox.purge._DELETE_CHUNK_SIZE', 2):
        with CaptureQueriesContext(connection) as ctx:
            result = purge_dead_letter(older_than_dead=timedelta(days=30), dry_run=False)

    delete_queries = [query['sql'] for query in ctx.captured_queries if query['sql'].lstrip().upper().startswith('DELETE')]
    assert result.deleted_count == 3
    assert len(delete_queries) == 2
    assert CeleryOutboxDeadLetter.objects.count() == 0


@pytest.mark.django_db
def test_purge_dead_letter_dry_run_unchanged() -> None:
    now = timezone.now()
    old_time = now - timedelta(days=31)
    with patch('django.utils.timezone.now', return_value=now):
        record = CeleryOutboxDeadLetterFactory.create(task_name='myapp.task')
    CeleryOutboxDeadLetter.objects.filter(pk=record.pk).update(dead_at=old_time)

    with patch('django_celery_outbox.purge._DELETE_CHUNK_SIZE', 2):
        result = purge_dead_letter(older_than_dead=timedelta(days=30), dry_run=True)

    assert result.deleted_count == 1
    assert CeleryOutboxDeadLetter.objects.filter(pk=record.pk).exists()
