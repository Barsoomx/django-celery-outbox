# Schema Version Marker Design

**Issue:** https://github.com/Barsoomx/django-celery-outbox/issues/30
**Date:** 2026-04-12

## Problem

`CeleryOutbox.options` is a JSONField storing serialized Celery metadata. Future versions may rename keys, restructure signatures, or change ETA format. No schema version marker exists — relay running new code on old rows cannot determine if upgrade is needed.

Current upgrade path is implicitly "drain queue before upgrading", which contradicts zero-downtime goal.

## Decisions

1. **Storage**: Separate `schema_version` field (SmallIntegerField), not JSON key
2. **Compatibility**: N-1 policy (support only previous version)
3. **Dead letter**: Add `schema_version` to `CeleryOutboxDeadLetter` too
4. **Unknown version**: Skip (relay takes other messages, compatible relay picks up later)

## Design

### 1. Models

```python
# models.py
class CeleryOutbox(models.Model):
    # ... existing fields ...
    schema_version = models.SmallIntegerField(default=1)

class CeleryOutboxDeadLetter(models.Model):
    # ... existing fields ...
    schema_version = models.SmallIntegerField(default=1)
```

Migration 0002 adds field to both models with `default=1`.

### 2. Serialization

```python
# serialization.py
CURRENT_SCHEMA_VERSION = 1
MIN_SUPPORTED_VERSION = 1

class UnsupportedSchemaVersion(Exception):
    def __init__(self, version: int):
        self.version = version
        super().__init__(f'Unsupported schema version: {version}')

def serialize_options_v1(options, countdown, eta) -> dict:
    # current serialize_options logic
    ...

def deserialize_options_v1(options, app) -> dict:
    # current deserialize_options logic
    ...

_DESERIALIZERS = {
    1: deserialize_options_v1,
}

def deserialize_options(options: dict, app: Celery, schema_version: int) -> dict:
    if schema_version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(schema_version)
    if schema_version < MIN_SUPPORTED_VERSION:
        raise UnsupportedSchemaVersion(schema_version)
    return _DESERIALIZERS[schema_version](options, app)

def serialize_options(...) -> dict:
    return serialize_options_v1(...)
```

### 3. Relay

```python
# relay.py — _select_messages
def _select_messages(self) -> list[CeleryOutbox]:
    queryset = (
        CeleryOutbox.objects.select_for_update(skip_locked=True)
        .filter(
            Q(updated_at__isnull=True) | Q(retry_after__lte=Now()) | ...,
            schema_version__lte=CURRENT_SCHEMA_VERSION,
        )
        .order_by('id')[: self._batch_size]
    )
    return list(queryset)

# relay.py — _send_task
def _send_task(self, msg: CeleryOutbox) -> None:
    options = deserialize_options(msg.options, self._app, msg.schema_version)
    # ... rest unchanged

# relay.py — _move_to_dead_letter
CeleryOutboxDeadLetter(
    # ... existing fields ...
    schema_version=msg.schema_version,
)
```

### 4. App

```python
# app.py — send_task
from django_celery_outbox.serialization import CURRENT_SCHEMA_VERSION

CeleryOutbox.objects.create(
    # ... existing fields ...
    schema_version=CURRENT_SCHEMA_VERSION,
)
```

### 5. Admin

Add `schema_version` to:
- `list_display`
- `readonly_fields`

### 6. Tests

- `test_serialize_deserialize_v1_roundtrip` — basic round-trip
- `test_deserialize_unsupported_future_version_raises` — version > current
- `test_deserialize_below_min_version_raises` — version < min
- `test_select_messages_skips_future_versions` — relay skips v2+
- `test_dead_letter_preserves_schema_version` — version copied

### 7. Documentation

README section "Schema Versioning":
- Upgrade policy (N-1 support)
- Rolling deployment behavior
- Dead letter considerations

## Files to Modify

- `django_celery_outbox/models.py`
- `django_celery_outbox/migrations/0002_schema_version.py` (new)
- `django_celery_outbox/serialization.py`
- `django_celery_outbox/relay.py`
- `django_celery_outbox/app.py`
- `django_celery_outbox/admin.py`
- `django_celery_outbox/serialization_tests.py`
- `django_celery_outbox/relay_tests.py`
- `README.md`
