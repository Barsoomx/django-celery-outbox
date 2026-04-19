from __future__ import annotations

from amqp.exceptions import ChannelError as AmqpChannelError
from amqp.exceptions import ConnectionError as AmqpConnectionError
from kombu.exceptions import OperationalError

_BROKER_OUTAGE_EXCEPTIONS = (
    TimeoutError,
    OperationalError,
    ConnectionError,
    AmqpConnectionError,
    AmqpChannelError,
)


def is_broker_outage(exc: Exception) -> bool:
    if isinstance(exc, _BROKER_OUTAGE_EXCEPTIONS[:3]):
        return True

    return type(exc) in _BROKER_OUTAGE_EXCEPTIONS[3:]


class RelayPolicy:
    def __init__(self, *, broker_outage_cooldown: float, shutdown_timeout: float) -> None:
        self._broker_outage_cooldown = broker_outage_cooldown
        self._shutdown_timeout = shutdown_timeout
        self._breaker_open_until: float | None = None
        self._shutdown_deadline: float | None = None
        self._outage_streak = 0

    def begin_batch(self) -> None:
        self._outage_streak = 0

    def should_skip_batch(self, now_monotonic: float) -> bool:
        if self._breaker_open_until is None:
            return False
        if now_monotonic >= self._breaker_open_until:
            self._breaker_open_until = None
            return False
        return True

    def seconds_until_batch_retry(self, now_monotonic: float) -> float:
        if self._breaker_open_until is None:
            return 0.0
        return max(self._breaker_open_until - now_monotonic, 0.0)

    def record_success(self) -> None:
        self._outage_streak = 0

    def record_outage(self, now_monotonic: float) -> bool:
        self._outage_streak += 1
        if self._outage_streak >= 2:
            self._breaker_open_until = now_monotonic + self._broker_outage_cooldown
            return True
        return False

    def begin_shutdown(self, now_monotonic: float) -> None:
        self._shutdown_deadline = now_monotonic + self._shutdown_timeout

    def shutdown_deadline_exceeded(self, now_monotonic: float) -> bool:
        return self._shutdown_deadline is not None and now_monotonic >= self._shutdown_deadline
