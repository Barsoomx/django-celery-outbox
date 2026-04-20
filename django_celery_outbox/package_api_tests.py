import pytest

import django_celery_outbox as package
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter
from django_celery_outbox.relay import Relay
from django_celery_outbox.signals import (
    outbox_message_created,
    outbox_message_dead_lettered,
    outbox_message_failed,
    outbox_message_sent,
)


@pytest.mark.parametrize(
    ('attribute_name', 'expected'),
    [
        ('Relay', Relay),
        ('CeleryOutbox', CeleryOutbox),
        ('CeleryOutboxDeadLetter', CeleryOutboxDeadLetter),
        ('outbox_message_created', outbox_message_created),
        ('outbox_message_sent', outbox_message_sent),
        ('outbox_message_failed', outbox_message_failed),
        ('outbox_message_dead_lettered', outbox_message_dead_lettered),
    ],
)
def test_package_root_lazy_exports(attribute_name: str, expected: object) -> None:
    assert getattr(package, attribute_name) is expected


def test_package_root_unknown_attribute_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="has no attribute 'missing_symbol'"):
        package.__getattr__('missing_symbol')
