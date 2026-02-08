from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from celery import Celery
from celery.canvas import Signature

from django_celery_outbox.serialization import (
    _kombu_obj_to_str,
    _signature_to_dict,
    _signatures_to_list,
    deserialize_options,
    serialize_options,
)


class KombuObj:
    def __init__(self, name: str) -> None:
        self.name = name


class ObjWithoutName:
    def __str__(self) -> str:
        return 'obj_str_repr'


@pytest.fixture()
def f_app() -> Celery:
    return Celery('test')


@pytest.fixture()
def f_signature(f_app: Celery) -> Signature:
    return Signature('my_task', args=(1, 2), app=f_app)


def test_signature_to_dict_none_returns_none() -> None:
    assert _signature_to_dict(None) is None


def test_signature_to_dict_signature_returns_dict(f_signature: Signature) -> None:
    result = _signature_to_dict(f_signature)

    assert isinstance(result, dict)
    assert result == dict(f_signature)


def test_signature_to_dict_dict_returns_same_dict() -> None:
    d = {'task': 'my_task', 'args': [1, 2]}

    result = _signature_to_dict(d)

    assert result is d


def test_signature_to_dict_other_type_returns_none() -> None:
    assert _signature_to_dict(42) is None


def test_signature_to_dict_string_returns_none() -> None:
    assert _signature_to_dict('some_string') is None


def test_signatures_to_list_none_returns_none() -> None:
    assert _signatures_to_list(None) is None


def test_signatures_to_list_list_of_signatures(f_app: Celery) -> None:
    sig1 = Signature('task_a', app=f_app)
    sig2 = Signature('task_b', app=f_app)

    result = _signatures_to_list([sig1, sig2])

    assert result == [dict(sig1), dict(sig2)]


def test_signatures_to_list_tuple_of_signatures(f_app: Celery) -> None:
    sig1 = Signature('task_a', app=f_app)
    sig2 = Signature('task_b', app=f_app)

    result = _signatures_to_list((sig1, sig2))

    assert result == [dict(sig1), dict(sig2)]


def test_signatures_to_list_list_of_dicts() -> None:
    d1 = {'task': 'task_a'}
    d2 = {'task': 'task_b'}

    result = _signatures_to_list([d1, d2])

    assert result == [d1, d2]


def test_signatures_to_list_empty_after_filtering_returns_none() -> None:
    result = _signatures_to_list([42, 'bad'])

    assert result is None


def test_signatures_to_list_single_signature(f_signature: Signature) -> None:
    result = _signatures_to_list(f_signature)

    assert result == [dict(f_signature)]


def test_signatures_to_list_single_dict() -> None:
    d = {'task': 'task_a'}

    result = _signatures_to_list(d)

    assert result == [d]


def test_signatures_to_list_other_type_returns_none() -> None:
    assert _signatures_to_list(42) is None


def test_signatures_to_list_mixed_list_filters_invalid(f_app: Celery) -> None:
    sig = Signature('task_a', app=f_app)

    result = _signatures_to_list([sig, 42, None])

    assert result == [dict(sig)]


def test_kombu_obj_to_str_none_returns_none() -> None:
    assert _kombu_obj_to_str(None) is None


def test_kombu_obj_to_str_string_returns_string() -> None:
    assert _kombu_obj_to_str('my_queue') == 'my_queue'


def test_kombu_obj_to_str_object_with_name_attr() -> None:
    obj = KombuObj('celery_queue')

    assert _kombu_obj_to_str(obj) == 'celery_queue'


def test_kombu_obj_to_str_other_object_returns_str() -> None:
    obj = ObjWithoutName()

    assert _kombu_obj_to_str(obj) == 'obj_str_repr'


def test_serialize_options_countdown_computes_eta() -> None:
    before = datetime.now(timezone.utc)

    result = serialize_options({}, countdown=60)

    after = datetime.now(timezone.utc)
    eta = datetime.fromisoformat(result['eta'])
    assert before + timedelta(seconds=60) <= eta <= after + timedelta(seconds=60)


def test_serialize_options_eta_datetime_to_isoformat() -> None:
    eta = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    result = serialize_options({}, eta=eta)

    assert result['eta'] == eta.isoformat()


def test_serialize_options_eta_non_datetime_to_str() -> None:
    result = serialize_options({}, eta='2025-01-15T12:00:00')  # type: ignore[arg-type]

    assert result['eta'] == '2025-01-15T12:00:00'


def test_serialize_options_countdown_takes_precedence_over_eta() -> None:
    eta = datetime(2099, 1, 1, tzinfo=timezone.utc)

    result = serialize_options({}, countdown=10, eta=eta)

    parsed_eta = datetime.fromisoformat(result['eta'])
    assert parsed_eta.year != 2099


def test_serialize_options_expires_datetime_to_isoformat() -> None:
    expires = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

    result = serialize_options({'expires': expires})

    assert result['expires'] == expires.isoformat()


def test_serialize_options_expires_int_stays_int() -> None:
    result = serialize_options({'expires': 300})

    assert result['expires'] == 300


def test_serialize_options_expires_float_stays_float() -> None:
    result = serialize_options({'expires': 30.5})

    assert result['expires'] == 30.5


def test_serialize_options_expires_string_stays_string() -> None:
    result = serialize_options({'expires': 'custom_value'})

    assert result['expires'] == 'custom_value'


def test_serialize_options_expires_none_skipped() -> None:
    result = serialize_options({'expires': None})

    assert 'expires' not in result


def test_serialize_options_link_with_signature(f_app: Celery) -> None:
    sig = Signature('callback', app=f_app)

    result = serialize_options({'link': sig})

    assert result['link'] == [dict(sig)]


def test_serialize_options_link_with_dict() -> None:
    d = {'task': 'callback'}

    result = serialize_options({'link': d})

    assert result['link'] == [d]


def test_serialize_options_link_with_list_of_signatures(f_app: Celery) -> None:
    sig1 = Signature('cb1', app=f_app)
    sig2 = Signature('cb2', app=f_app)

    result = serialize_options({'link': [sig1, sig2]})

    assert result['link'] == [dict(sig1), dict(sig2)]


def test_serialize_options_link_error_with_signature(f_app: Celery) -> None:
    sig = Signature('errback', app=f_app)

    result = serialize_options({'link_error': sig})

    assert result['link_error'] == [dict(sig)]


def test_serialize_options_chain_with_list_of_signatures(f_app: Celery) -> None:
    sig1 = Signature('step1', app=f_app)
    sig2 = Signature('step2', app=f_app)

    result = serialize_options({'chain': [sig1, sig2]})

    assert result['chain'] == [dict(sig1), dict(sig2)]


def test_serialize_options_chord_with_signature(f_app: Celery) -> None:
    sig = Signature('chord_callback', app=f_app)

    result = serialize_options({'chord': sig})

    assert result['chord'] == dict(sig)


def test_serialize_options_chord_with_dict() -> None:
    d = {'task': 'chord_callback'}

    result = serialize_options({'chord': d})

    assert result['chord'] == d


def test_serialize_options_queue_with_string() -> None:
    result = serialize_options({'queue': 'default'})

    assert result['queue'] == 'default'


def test_serialize_options_queue_with_kombu_obj() -> None:
    obj = KombuObj('my_queue')

    result = serialize_options({'queue': obj})

    assert result['queue'] == 'my_queue'


def test_serialize_options_exchange_with_string() -> None:
    result = serialize_options({'exchange': 'my_exchange'})

    assert result['exchange'] == 'my_exchange'


def test_serialize_options_exchange_with_kombu_obj() -> None:
    obj = KombuObj('my_exchange')

    result = serialize_options({'exchange': obj})

    assert result['exchange'] == 'my_exchange'


def test_serialize_options_transient_keys_filtered() -> None:
    options = {
        'producer': MagicMock(),
        'connection': MagicMock(),
        'publisher': MagicMock(),
        'task_type': 'some_type',
        'router': MagicMock(),
        'app': MagicMock(),
        'body': b'body',
        'content_type': 'application/json',
        'content_encoding': 'utf-8',
        'serializer': 'json',
        'headers': {},
        'exchange_type': 'direct',
        'delivery_mode': 2,
        'compression': None,
        'reply_to': 'queue',
        'correlation_id': 'abc',
        'declare': [],
        'retry_policy': {},
        'priority': 5,
    }

    result = serialize_options(options)

    assert 'producer' not in result
    assert 'connection' not in result
    assert 'publisher' not in result
    assert 'task_type' not in result
    assert 'router' not in result
    assert 'app' not in result
    assert 'body' not in result
    assert 'content_type' not in result
    assert 'content_encoding' not in result
    assert 'serializer' not in result
    assert 'headers' not in result
    assert 'exchange_type' not in result
    assert 'delivery_mode' not in result
    assert 'compression' not in result
    assert 'reply_to' not in result
    assert 'correlation_id' not in result
    assert 'declare' not in result
    assert 'retry_policy' not in result
    assert result['priority'] == 5


def test_serialize_options_none_values_skipped() -> None:
    result = serialize_options({'routing_key': None, 'priority': None})

    assert 'routing_key' not in result
    assert 'priority' not in result


def test_serialize_options_regular_keys_passed_through() -> None:
    result = serialize_options(
        {
            'priority': 5,
            'routing_key': 'my.key',
            'max_retries': 3,
        }
    )

    assert result['priority'] == 5
    assert result['routing_key'] == 'my.key'
    assert result['max_retries'] == 3


def test_serialize_options_empty_options() -> None:
    result = serialize_options({})

    assert result == {}


def test_serialize_options_link_none_not_included() -> None:
    result = serialize_options({'link': None})

    assert 'link' not in result


def test_serialize_options_link_error_none_not_included() -> None:
    result = serialize_options({'link_error': None})

    assert 'link_error' not in result


def test_serialize_options_chain_none_not_included() -> None:
    result = serialize_options({'chain': None})

    assert 'chain' not in result


def test_serialize_options_chord_none_not_included() -> None:
    result = serialize_options({'chord': None})

    assert 'chord' not in result


def test_serialize_options_queue_none_not_included() -> None:
    result = serialize_options({'queue': None})

    assert 'queue' not in result


def test_serialize_options_exchange_none_not_included() -> None:
    result = serialize_options({'exchange': None})

    assert 'exchange' not in result


def test_deserialize_options_eta_string_to_datetime(f_app: Celery) -> None:
    eta = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    options = {'eta': eta.isoformat()}

    result = deserialize_options(options, f_app)

    assert result['eta'] == eta


def test_deserialize_options_expires_string_to_datetime(f_app: Celery) -> None:
    expires = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    options = {'expires': expires.isoformat()}

    result = deserialize_options(options, f_app)

    assert result['expires'] == expires


def test_deserialize_options_expires_int_stays_int(f_app: Celery) -> None:
    options = {'expires': 300}

    result = deserialize_options(options, f_app)

    assert result['expires'] == 300


def test_deserialize_options_link_list_of_dicts_to_signatures(f_app: Celery) -> None:
    sig = Signature('callback', app=f_app)
    options = {'link': [dict(sig)]}

    result = deserialize_options(options, f_app)

    assert len(result['link']) == 1
    assert isinstance(result['link'][0], Signature)
    assert result['link'][0]['task'] == 'callback'


def test_deserialize_options_link_error_list_of_dicts_to_signatures(f_app: Celery) -> None:
    sig = Signature('errback', app=f_app)
    options = {'link_error': [dict(sig)]}

    result = deserialize_options(options, f_app)

    assert len(result['link_error']) == 1
    assert isinstance(result['link_error'][0], Signature)
    assert result['link_error'][0]['task'] == 'errback'


def test_deserialize_options_chain_list_to_signatures(f_app: Celery) -> None:
    sig1 = Signature('step1', app=f_app)
    sig2 = Signature('step2', app=f_app)
    options = {'chain': [dict(sig1), dict(sig2)]}

    result = deserialize_options(options, f_app)

    assert len(result['chain']) == 2
    assert all(isinstance(s, Signature) for s in result['chain'])
    assert result['chain'][0]['task'] == 'step1'
    assert result['chain'][1]['task'] == 'step2'


def test_deserialize_options_chord_dict_to_signature(f_app: Celery) -> None:
    sig = Signature('chord_cb', app=f_app)
    options = {'chord': dict(sig)}

    result = deserialize_options(options, f_app)

    assert isinstance(result['chord'], Signature)
    assert result['chord']['task'] == 'chord_cb'


def test_deserialize_options_regular_keys_passed_through(f_app: Celery) -> None:
    options = {'priority': 5, 'routing_key': 'my.key'}

    result = deserialize_options(options, f_app)

    assert result['priority'] == 5
    assert result['routing_key'] == 'my.key'


def test_deserialize_options_does_not_mutate_original(f_app: Celery) -> None:
    options = {'priority': 5, 'eta': '2025-01-15T12:00:00+00:00'}
    original_eta = options['eta']

    deserialize_options(options, f_app)

    assert options['eta'] == original_eta


def test_deserialize_options_empty_options(f_app: Celery) -> None:
    result = deserialize_options({}, f_app)

    assert result == {}


def test_deserialize_options_link_non_list_not_converted(f_app: Celery) -> None:
    options = {'link': 'not_a_list'}

    result = deserialize_options(options, f_app)

    assert result['link'] == 'not_a_list'


def test_deserialize_options_chord_non_dict_not_converted(f_app: Celery) -> None:
    options = {'chord': 'not_a_dict'}

    result = deserialize_options(options, f_app)

    assert result['chord'] == 'not_a_dict'


def test_signatures_to_list_empty_list_returns_none() -> None:
    result = _signatures_to_list([])

    assert result is None


def test_deserialize_options_link_error_non_list_not_converted(f_app: Celery) -> None:
    options = {'link_error': 'not_a_list'}

    result = deserialize_options(options, f_app)

    assert result['link_error'] == 'not_a_list'


def test_deserialize_options_chain_non_list_not_converted(f_app: Celery) -> None:
    options = {'chain': 'not_a_list'}

    result = deserialize_options(options, f_app)

    assert result['chain'] == 'not_a_list'


def test_deserialize_options_invalid_eta_raises(f_app: Celery) -> None:
    with pytest.raises(ValueError):
        deserialize_options({'eta': 'not-a-date'}, f_app)
