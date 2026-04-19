#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SPECULATIVE_MARKERS = ('WIP', 'TODO', 'TBD', 'FIXME', 'draft')
MARKER_PATTERN = re.compile(r'\b(' + '|'.join(re.escape(marker) for marker in SPECULATIVE_MARKERS) + r')\b', re.IGNORECASE)


def _build_release_heading_pattern(version: str) -> re.Pattern[str]:
    escaped_version = re.escape(version)
    return re.compile(rf'^##\s+(?:\[{escaped_version}\]|{escaped_version})(?:\s+[—-].+)?\s*$')


def _has_release_heading(lines: list[str], version: str) -> bool:
    release_heading_pattern = _build_release_heading_pattern(version)
    open_fence: str | None = None

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith('```') or stripped.startswith('~~~'):
            fence = stripped[:3]
            if open_fence is None:
                open_fence = fence
            elif fence == open_fence:
                open_fence = None
            continue

        if open_fence is None and release_heading_pattern.match(line):
            return True

    return False


def check_changelog(path: Path, *, version: str | None = None) -> list[str]:
    problems: list[str] = []
    lines = path.read_text(encoding='utf-8').splitlines()

    for line_number, line in enumerate(lines, start=1):
        match = MARKER_PATTERN.search(line)
        if match:
            problems.append(f'{path}:{line_number}: speculative marker "{match.group(1)}" found: {line.strip()}')

    if version is not None:
        if not _has_release_heading(lines, version):
            problems.append(f'{path}: missing changelog section for release {version}')

    return problems


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Check release notes for speculative markers and release headings.')
    parser.add_argument(
        '--version',
        default=None,
        help='Release version that must have a dedicated changelog section',
    )
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
        problems.extend(check_changelog(path, version=args.version))

    if problems:
        for problem in problems:
            sys.stderr.write(f'{problem}\n')
        return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
