from datetime import timedelta

import pytest

from django_celery_outbox.purge import parse_duration, PurgeResult


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
