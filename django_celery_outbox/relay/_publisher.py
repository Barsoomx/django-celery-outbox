import json
from dataclasses import dataclass
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
    def __init__(self, app: Celery, *, send_timeout: float) -> None:
        self._app = app
        self._send_timeout = send_timeout

    def _apply_sentry_headers(self, headers: dict[str, Any], msg: CeleryOutbox) -> dict[str, Any]:
        merged = dict(headers)
        if msg.sentry_trace_id:
            merged['sentry-trace'] = msg.sentry_trace_id
        if msg.sentry_baggage:
            merged['baggage'] = msg.sentry_baggage
        return merged

    def prepare_publish_call(self, msg: CeleryOutbox) -> 'PreparedPublishCall':
        options = deserialize_options(msg.options, self._app, msg.schema_version)
        headers = dict(options.pop('headers', {}) or {})
        options.pop('timeout', None)
        headers = self._apply_sentry_headers(headers, msg)

        return PreparedPublishCall(
            task_name=msg.task_name,
            task_id=msg.task_id,
            args=msg.args,
            kwargs=msg.kwargs,
            options=options,
            headers=headers,
            structlog_context=parse_structlog_context(msg.structlog_context),
        )

    def publish_prepared(self, call: 'PreparedPublishCall') -> None:
        with structlog.contextvars.bound_contextvars(**call.structlog_context):
            Celery.send_task(
                self._app,
                name=call.task_name,
                args=call.args,
                kwargs=call.kwargs,
                task_id=call.task_id,
                headers=call.headers,
                timeout=self._send_timeout,
                **call.options,
            )

    def publish(self, msg: CeleryOutbox) -> None:
        self.publish_prepared(self.prepare_publish_call(msg))


@dataclass(frozen=True)
class PreparedPublishCall:
    task_name: str
    task_id: str
    args: list[Any]
    kwargs: dict[str, Any]
    options: dict[str, Any]
    headers: dict[str, Any]
    structlog_context: dict[str, Any]
