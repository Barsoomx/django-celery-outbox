#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SPECULATIVE_MARKERS = ('WIP', 'TODO', 'TBD', 'FIXME', 'draft')
MARKER_PATTERN = re.compile(r'\b(' + '|'.join(re.escape(marker) for marker in SPECULATIVE_MARKERS) + r')\b', re.IGNORECASE)


def check_changelog(path: Path) -> list[str]:
    problems: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        match = MARKER_PATTERN.search(line)
        if match:
            problems.append(f'{path}:{line_number}: speculative marker "{match.group(1)}" found: {line.strip()}')
    return problems


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Check release notes for speculative markers.')
    parser.add_argument(
        'paths',
        nargs='*',
        default=['CHANGELOG.md'],
        help='Changelog file(s) to scan',
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    problems: list[str] = []

    for raw_path in args.paths:
        path = Path(raw_path)
        if not path.exists():
            problems.append(f'{path}: file not found')
            continue
        problems.extend(check_changelog(path))

    if problems:
        for problem in problems:
            sys.stderr.write(f'{problem}\n')
        return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
