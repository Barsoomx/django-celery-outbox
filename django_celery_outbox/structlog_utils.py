import json
from collections.abc import Iterable
from typing import Any

import structlog.contextvars
from django.conf import settings


def _get_current_context() -> dict[str, Any]:
    try:
        ctx = structlog.contextvars.get_contextvars()
        return dict(ctx) if ctx is not None else {}
    except AttributeError:
        return {}


def _filter_context(ctx: dict[str, Any], keys: Iterable[str] | None) -> dict[str, Any]:
    if not keys:
        return ctx

    keys_set = set(keys)
    return {k: v for k, v in ctx.items() if k in keys_set}


def get_structlog_context_json() -> str | None:
    enabled = getattr(settings, 'CELERY_OUTBOX_STRUCTLOG_ENABLED', True)
    if not enabled:
        return None

    keys = getattr(settings, 'CELERY_OUTBOX_STRUCTLOG_CONTEXT_KEYS', None)
    ctx = _filter_context(_get_current_context(), keys)
    if not ctx:
        return None

    try:
        return json.dumps(ctx, default=str, ensure_ascii=False, separators=(',', ':'))
    except (TypeError, ValueError):
        try:
            return json.dumps(
                {k: str(v) for k, v in ctx.items()},
                ensure_ascii=False,
                separators=(',', ':'),
            )
        except (TypeError, ValueError):
            return None
