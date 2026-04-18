import json
from typing import Any

import structlog
from celery import Celery

from django_celery_outbox.models import CeleryOutbox
from django_celery_outbox.serialization import deserialize_options


def parse_structlog_context(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}

    return parsed if isinstance(parsed, dict) else {}


class RelayPublisher:
    def __init__(self, app: Celery) -> None:
        self._app = app

    def publish(self, msg: CeleryOutbox) -> None:
        options = deserialize_options(msg.options, self._app, msg.schema_version)

        headers = options.pop('headers', {}) or {}
        if msg.sentry_trace_id:
            headers['sentry-trace'] = msg.sentry_trace_id
        if msg.sentry_baggage:
            headers['baggage'] = msg.sentry_baggage

        eta = options.pop('eta', None)
        ctx = parse_structlog_context(msg.structlog_context)

        with structlog.contextvars.bound_contextvars(**ctx):
            Celery.send_task(
                self._app,
                name=msg.task_name,
                args=msg.args,
                kwargs=msg.kwargs,
                task_id=msg.task_id,
                eta=eta,
                headers=headers,
                **options,
            )
