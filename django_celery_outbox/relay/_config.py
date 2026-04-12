from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


# TODO(mcproger): introduce db-backend/dynamically dispatch from django settings
@dataclass(frozen=True, kw_only=True)
class RelayConfig:
    batch_size: int
    idle_time: float
    backoff_time: int
    max_retries: int
    stale_timeout_seconds: int
    liveness_file: Path | None

    @classmethod
    def init(
        cls,
        batch_size: int = 100,
        idle_time: float = 1.0,
        backoff_time: int = 120,
        max_retries: int = 5,
        stale_timeout_seconds: int = 300,
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

        if stale_timeout_seconds <= 0:
            raise ImproperlyConfigured('stale_timeout_seconds must be > 0')

        return cls(
            batch_size=batch_size,
            idle_time=idle_time,
            backoff_time=backoff_time,
            max_retries=max_retries,
            stale_timeout_seconds=stale_timeout_seconds,
            liveness_file=Path(liveness_file) if liveness_file else None,
        )

    @classmethod
    def from_options(cls, options: dict[str, float | int]) -> 'RelayConfig':
        return cls.init(
            batch_size=options['batch_size'],
            idle_time=options['idle_time'],
            backoff_time=options['backoff_time'],
            max_retries=options['max_retries'],
            liveness_file=options['liveness_file'],
        )
