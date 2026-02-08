import json
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
import structlog.contextvars
from django.test import override_settings

from django_celery_outbox.structlog_utils import (
    _filter_context,
    _get_current_context,
    get_structlog_context_json,
)


@pytest.fixture(autouse=True)
def _clear_contextvars() -> Generator[None]:
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


def test_get_current_context_returns_dict_from_contextvars() -> None:
    structlog.contextvars.bind_contextvars(request_id='abc', user_id=42)

    result = _get_current_context()

    assert result == {'request_id': 'abc', 'user_id': 42}


def test_get_current_context_returns_empty_dict_on_exception() -> None:
    with patch(
        'structlog.contextvars.get_contextvars',
        side_effect=AttributeError('boom'),
    ):
        result = _get_current_context()

    assert result == {}


def test_filter_context_with_keys_filters_only_specified() -> None:
    ctx = {'a': 1, 'b': 2, 'c': 3}

    result = _filter_context(ctx, ['a', 'c'])

    assert result == {'a': 1, 'c': 3}


def test_filter_context_keys_none_returns_full_dict() -> None:
    ctx = {'a': 1, 'b': 2}

    result = _filter_context(ctx, None)

    assert result == {'a': 1, 'b': 2}


def test_filter_context_empty_keys_returns_full_dict() -> None:
    ctx = {'a': 1, 'b': 2}

    result = _filter_context(ctx, [])

    assert result == {'a': 1, 'b': 2}


def test_get_structlog_context_json_with_context_returns_json() -> None:
    structlog.contextvars.bind_contextvars(request_id='abc')

    result = get_structlog_context_json()

    assert result is not None
    parsed = json.loads(result)
    assert parsed == {'request_id': 'abc'}


def test_get_structlog_context_json_without_context_returns_none() -> None:
    result = get_structlog_context_json()

    assert result is None


@override_settings(CELERY_OUTBOX_STRUCTLOG_ENABLED=False)
def test_get_structlog_context_json_disabled_returns_none() -> None:
    structlog.contextvars.bind_contextvars(request_id='abc')

    result = get_structlog_context_json()

    assert result is None


@override_settings(CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS=['key1'])
def test_get_structlog_context_json_context_keys_filters() -> None:
    structlog.contextvars.bind_contextvars(key1='val1', key2='val2')

    result = get_structlog_context_json()

    assert result is not None
    parsed = json.loads(result)
    assert parsed == {'key1': 'val1'}


def test_get_structlog_context_json_non_serializable_fallback_to_str() -> None:
    class Unserializable:
        def __str__(self) -> str:
            return 'unserializable_repr'

    structlog.contextvars.bind_contextvars(obj=Unserializable())

    result = get_structlog_context_json()

    assert result is not None
    parsed = json.loads(result)
    assert parsed == {'obj': 'unserializable_repr'}


def test_get_structlog_context_json_both_dumps_fail_returns_none() -> None:
    structlog.contextvars.bind_contextvars(key='value')

    with patch('django_celery_outbox.structlog_utils.json.dumps', side_effect=ValueError('fail')):
        result = get_structlog_context_json()

    assert result is None


def test_get_current_context_returns_empty_when_contextvars_returns_none() -> None:
    with patch(
        'structlog.contextvars.get_contextvars',
        return_value=None,
    ):
        result = _get_current_context()

    assert result == {}


def test_get_structlog_context_json_first_dumps_fails_fallback_succeeds() -> None:
    structlog.contextvars.bind_contextvars(key='value')

    call_count = 0
    original_dumps = json.dumps

    def _side_effect(*args: Any, **kwargs: Any) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TypeError('not serializable')

        return original_dumps(*args, **kwargs)

    with patch('django_celery_outbox.structlog_utils.json.dumps', side_effect=_side_effect):
        result = get_structlog_context_json()

    assert result is not None
    parsed = json.loads(result)
    assert parsed == {'key': 'value'}


def test_filter_context_keys_not_in_ctx_returns_empty() -> None:
    ctx = {'a': 1, 'b': 2}

    result = _filter_context(ctx, ['x', 'y', 'z'])

    assert result == {}
