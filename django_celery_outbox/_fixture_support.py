"""Package-owned support API for the shipped pytest fixtures.

The public pytest fixtures in :mod:`django_celery_outbox.fixtures` depend on the
helpers exported here. These helpers are part of the package's semver-stable
testing surface for the library itself, even though downstream users should
continue to prefer the fixtures as the primary public API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from celery import Celery

import django_celery_outbox._settings as settings_module

__all__ = [
    'FakeRelayRecorder',
    'RecordedRelayCall',
    'load_fixture_celery_app',
    'patch_fake_relay_send_task',
    'reset_fixture_state',
    'run_drain_outbox_once',
]

_SEND_TASK_POSITIONAL_PARAMETER_NAMES = (
    'name',
    'args',
    'kwargs',
    'countdown',
    'eta',
    'task_id',
    'producer',
    'connection',
    'router',
    'result_cls',
    'expires',
    'publisher',
    'link',
    'link_error',
    'add_to_parent',
    'group_id',
    'group_index',
    'retries',
    'chord',
    'reply_to',
    'time_limit',
    'soft_time_limit',
    'root_id',
    'parent_id',
    'route_name',
    'shadow',
    'chain',
    'task_type',
    'replaced_task_nesting',
)


@dataclass(slots=True)
class RecordedRelayCall:
    name: str
    args: list[Any]
    kwargs: dict[str, Any]
    task_id: str
    headers: dict[str, Any]
    options: dict[str, Any]


@dataclass(slots=True)
class FakeRelayRecorder:
    calls: list[RecordedRelayCall] = field(default_factory=list)


def _normalize_send_task_call(
    call_args: tuple[Any, ...],
    call_kwargs: dict[str, Any],
) -> dict[str, Any]:
    max_positional_arguments = len(_SEND_TASK_POSITIONAL_PARAMETER_NAMES)
    if len(call_args) > max_positional_arguments:
        raise TypeError(
            f'send_task() takes at most {max_positional_arguments} positional arguments after app, but {len(call_args)} were given',
        )

    normalized = dict(call_kwargs)
    for parameter_name, value in zip(_SEND_TASK_POSITIONAL_PARAMETER_NAMES, call_args, strict=False):
        if parameter_name in normalized:
            raise TypeError(f"send_task() got multiple values for argument '{parameter_name}'")
        normalized[parameter_name] = value

    if 'name' not in normalized:
        raise TypeError("send_task() missing required argument: 'name'")

    return normalized


def load_fixture_celery_app() -> Celery:
    """Return the Celery app configured for the package's pytest fixtures."""
    return settings_module.load_celery_app_setting()


def reset_fixture_state() -> None:
    """Reset fixture-managed process state between tests."""
    import structlog.contextvars

    from django_celery_outbox.app import clear_redactor_cache
    from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter

    clear_redactor_cache()
    structlog.contextvars.clear_contextvars()
    CeleryOutboxDeadLetter.objects.all().delete()
    CeleryOutbox.objects.all().delete()


def patch_fake_relay_send_task(recorder: FakeRelayRecorder) -> Any:
    """Patch the relay Celery app to record publishes instead of sending them."""
    from django_celery_outbox.relay._publisher import Celery as RelayCelery

    relay_app = load_fixture_celery_app()
    original_send_task = RelayCelery.send_task

    def _record(
        _app: Celery,
        *call_args: Any,
        **call_kwargs: Any,
    ) -> object:
        normalized_call = _normalize_send_task_call(call_args, call_kwargs)
        name = normalized_call.pop('name')
        args = normalized_call.pop('args', None)
        kwargs = normalized_call.pop('kwargs', None)
        task_id = normalized_call.pop('task_id', None)
        headers = normalized_call.pop('headers', None)

        if _app is not relay_app:
            delegated_options = dict(normalized_call)
            if headers is not None:
                delegated_options['headers'] = headers

            return original_send_task(
                _app,
                name=name,
                args=args,
                kwargs=kwargs,
                task_id=task_id,
                **delegated_options,
            )

        recorder.calls.append(
            RecordedRelayCall(
                name=name,
                args=list(args or []),
                kwargs=dict(kwargs or {}),
                task_id=task_id or '',
                headers=dict(headers or {}),
                options=dict(normalized_call),
            )
        )
        return None

    return patch(
        'django_celery_outbox.relay._publisher.Celery.send_task',
        side_effect=_record,
    )


def run_drain_outbox_once(app: Celery, *, idle_time: float = 0.0) -> None:
    """Run one relay drain pass for the package-owned fixture support."""
    from django_celery_outbox.relay import Relay, RelayConfig

    relay = Relay(app=app, config=RelayConfig.init(idle_time=idle_time))
    with patch('django_celery_outbox.relay._relay.close_old_connections'):
        with patch('django_celery_outbox.relay._relay.time.sleep'):
            relay._processing()
