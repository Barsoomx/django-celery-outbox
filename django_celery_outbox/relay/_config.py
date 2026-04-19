import math
from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def _validate_positive_finite_seconds(name: str, value: float) -> None:
    if value <= 0 or not math.isfinite(value):
        raise ImproperlyConfigured(f'{name} must be > 0 and finite')


# TODO(mcproger): introduce db-backend/dynamically dispatch from django settings
@dataclass(frozen=True, kw_only=True)
class RelayConfig:
    batch_size: int
    idle_time: float
    backoff_time: int
    max_retries: int
    publish_concurrency: int
    stale_timeout_seconds: int
    send_timeout: float
    shutdown_timeout: float
    broker_outage_cooldown: float
    max_backoff: float
    liveness_file: Path | None

    @classmethod
    def init(
        cls,
        batch_size: int = 100,
        idle_time: float = 1.0,
        backoff_time: int = 120,
        max_retries: int = 5,
        publish_concurrency: int = 1,
        stale_timeout_seconds: int = 300,
        send_timeout: float = 10.0,
        shutdown_timeout: float = 30.0,
        broker_outage_cooldown: float = 30.0,
        max_backoff: float = 3600.0,
        liveness_file: str | None = None,
    ) -> 'RelayConfig':
        if batch_size <= 0:
            raise ImproperlyConfigured('batch_size must be > 0')

        if idle_time < 0:
            raise ImproperlyConfigured('idle_time must be >= 0')

        if backoff_time <= 0:
            raise ImproperlyConfigured('backoff_time must be > 0')

        if max_retries <= 0:
            raise ImproperlyConfigured('max_retries must be > 0')

        if publish_concurrency <= 0:
            raise ImproperlyConfigured('publish_concurrency must be > 0')

        if stale_timeout_seconds <= 0:
            raise ImproperlyConfigured('stale_timeout_seconds must be > 0')

        _validate_positive_finite_seconds('send_timeout', send_timeout)
        _validate_positive_finite_seconds('shutdown_timeout', shutdown_timeout)
        _validate_positive_finite_seconds('broker_outage_cooldown', broker_outage_cooldown)
        _validate_positive_finite_seconds('max_backoff', max_backoff)

        return cls(
            batch_size=batch_size,
            idle_time=idle_time,
            backoff_time=backoff_time,
            max_retries=max_retries,
            publish_concurrency=publish_concurrency,
            stale_timeout_seconds=stale_timeout_seconds,
            send_timeout=send_timeout,
            shutdown_timeout=shutdown_timeout,
            broker_outage_cooldown=broker_outage_cooldown,
            max_backoff=max_backoff,
            liveness_file=Path(liveness_file) if liveness_file else None,
        )

    @classmethod
    def from_options(cls, options: dict[str, float | int | str | None]) -> 'RelayConfig':
        return cls.init(
            batch_size=int(options['batch_size']),  # type: ignore[arg-type]
            idle_time=float(options['idle_time']),  # type: ignore[arg-type]
            backoff_time=int(options['backoff_time']),  # type: ignore[arg-type]
            max_retries=int(options['max_retries']),  # type: ignore[arg-type]
            publish_concurrency=int(options.get('publish_concurrency', 1)),  # type: ignore[arg-type]
            stale_timeout_seconds=int(options['stale_timeout_seconds']),  # type: ignore[arg-type]
            send_timeout=float(options['send_timeout']),  # type: ignore[arg-type]
            shutdown_timeout=float(options['shutdown_timeout']),  # type: ignore[arg-type]
            broker_outage_cooldown=float(options['broker_outage_cooldown']),  # type: ignore[arg-type]
            max_backoff=float(options['max_backoff']),  # type: ignore[arg-type]
            liveness_file=str(options['liveness_file']) if options.get('liveness_file') else None,
        )
