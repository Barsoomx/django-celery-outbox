from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from celery import Celery
from celery.canvas import Signature

_logger = structlog.getLogger(__name__)

_TRANSIENT_KEYS = frozenset(
    {
        'producer',
        'connection',
        'publisher',
        'task_type',
        'router',
        'app',
        'body',
        'content_type',
        'content_encoding',
        'serializer',
        'headers',
        'exchange_type',
        'delivery_mode',
        'compression',
        'reply_to',
        'correlation_id',
        'declare',
        'retry_policy',
    }
)


def _signature_to_dict(sig: Any) -> dict | None:
    if sig is None:
        return None

    if isinstance(sig, Signature):
        return dict(sig)

    if isinstance(sig, dict):
        return sig

    return None


def _signatures_to_list(sigs: Any) -> list[dict] | None:
    if sigs is None:
        return None

    if isinstance(sigs, list | tuple):
        result = []
        dropped = 0
        for s in sigs:
            d = _signature_to_dict(s)
            if d is not None:
                result.append(d)
            else:
                dropped += 1

        if dropped:
            _logger.warning(
                'celery_outbox_signatures_dropped',
                dropped=dropped,
                total=len(sigs),
            )

        return result or None

    d = _signature_to_dict(sigs)
    if d is not None:
        return [d]

    return None


def _kombu_obj_to_str(obj: Any) -> str | None:
    if obj is None:
        return None

    if isinstance(obj, str):
        return obj

    if hasattr(obj, 'name'):
        return obj.name

    return str(obj)


_SPECIAL_KEYS = frozenset(
    {
        'countdown',
        'eta',
        'expires',
        'link',
        'link_error',
        'chain',
        'chord',
        'queue',
        'exchange',
        'routing_key',
    }
)


def _serialize_eta(
    result: dict[str, Any],
    countdown: float | None,
    eta: datetime | None,
) -> None:
    if countdown is not None:
        eta_dt = datetime.now(timezone.utc) + timedelta(seconds=countdown)
        result['eta'] = eta_dt.isoformat()
    elif eta is not None:
        result['eta'] = eta.isoformat() if isinstance(eta, datetime) else str(eta)


def _serialize_expires(result: dict[str, Any], expires: Any) -> None:
    if isinstance(expires, datetime):
        result['expires'] = expires.isoformat()
    elif isinstance(expires, int | float):
        result['expires'] = expires
    elif expires is not None:
        result['expires'] = str(expires)


def _serialize_signatures(result: dict[str, Any], options: dict[str, Any]) -> None:
    for key in ('link', 'link_error', 'chain'):
        if key in options:
            serialized = _signatures_to_list(options[key])
            if serialized is not None:
                result[key] = serialized

    if 'chord' in options:
        d = _signature_to_dict(options['chord'])
        if d is not None:
            result['chord'] = d


def _serialize_kombu_keys(result: dict[str, Any], options: dict[str, Any]) -> None:
    for key in ('queue', 'exchange', 'routing_key'):
        if key in options:
            val = _kombu_obj_to_str(options[key])
            if val is not None:
                result[key] = val


def serialize_options(
    options: dict[str, Any],
    countdown: float | None = None,
    eta: datetime | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}

    _serialize_eta(result, countdown, eta)

    if 'expires' in options:
        _serialize_expires(result, options['expires'])

    _serialize_signatures(result, options)
    _serialize_kombu_keys(result, options)

    for key, val in options.items():
        if key in result or key in _TRANSIENT_KEYS or key in _SPECIAL_KEYS or val is None:
            continue

        result[key] = val

    return result


def _deserialize_signatures(result: dict[str, Any], app: Celery) -> None:
    for key in ('link', 'link_error', 'chain'):
        if key in result:
            val = result[key]
            if isinstance(val, list):
                result[key] = [Signature.from_dict(d, app=app) for d in val]

    if 'chord' in result:
        val = result['chord']
        if isinstance(val, dict):
            result['chord'] = Signature.from_dict(val, app=app)


def deserialize_options(options: dict[str, Any], app: Celery) -> dict[str, Any]:
    result = dict(options)

    if 'eta' in result:
        result['eta'] = datetime.fromisoformat(result['eta'])

    if 'expires' in result:
        expires = result['expires']
        if isinstance(expires, str):
            result['expires'] = datetime.fromisoformat(expires)

    _deserialize_signatures(result, app)

    return result
