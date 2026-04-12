import re
from dataclasses import dataclass
from datetime import timedelta

_DURATION_PATTERN = re.compile(r'^(\d+)([smhdw])$')
_UNIT_MULTIPLIERS = {
    's': 1,
    'm': 60,
    'h': 3600,
    'd': 86400,
    'w': 604800,
}


@dataclass
class PurgeResult:
    deleted_count: int
    task_names: dict[str, int]


def parse_duration(value: str) -> timedelta:
    match = _DURATION_PATTERN.match(value)
    if not match:
        raise ValueError(
            f'Invalid duration format: \'{value}\'. Use <number><unit> where unit is s/m/h/d/w'
        )

    amount = int(match.group(1))
    unit = match.group(2)
    seconds = amount * _UNIT_MULTIPLIERS[unit]

    return timedelta(seconds=seconds)
