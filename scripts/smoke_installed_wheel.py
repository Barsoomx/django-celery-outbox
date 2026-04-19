#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import sys


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Smoke-check an installed django-celery-outbox distribution.')
    parser.add_argument(
        '--expect-wheel-origin',
        action='store_true',
        help='Fail unless direct_url.json points at a wheel file',
    )
    return parser.parse_args(argv)


def bootstrap_django() -> None:
    from django.conf import settings

    if settings.configured:
        return

    settings.configure(
        SECRET_KEY='django-celery-outbox-smoke',
        INSTALLED_APPS=[
            'django.contrib.contenttypes',
            'django_celery_outbox',
        ],
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        },
        DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
        USE_TZ=True,
    )

    import django

    django.setup()


def verify_distribution(*, expect_wheel_origin: bool) -> None:
    distribution = metadata.distribution('django-celery-outbox')
    pytest11 = metadata.entry_points(group='pytest11')
    if not any(ep.name == 'django_celery_outbox' for ep in pytest11):
        raise SystemExit('pytest11 entry point missing for django_celery_outbox')

    if expect_wheel_origin:
        direct_url = distribution.read_text('direct_url.json')
        if direct_url is None:
            raise SystemExit('direct_url.json missing from installed distribution metadata')

        origin = json.loads(direct_url)
        url = origin.get('url', '')
        if not url.endswith('.whl'):
            raise SystemExit(f'Installed distribution was not loaded from a wheel: {url!r}')

        sys.stdout.write(f'{url}\n')


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    verify_distribution(expect_wheel_origin=args.expect_wheel_origin)
    bootstrap_django()

    import django_celery_outbox
    import django_celery_outbox.fixtures
    import django_celery_outbox.management.commands.celery_outbox_purge_dead_letter
    import django_celery_outbox.management.commands.celery_outbox_relay
    import django_celery_outbox.management.commands.celery_outbox_replay_dead_letter
    import django_celery_outbox.management.commands.celery_outbox_stats

    sys.stdout.write(f'{django_celery_outbox.__file__}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
