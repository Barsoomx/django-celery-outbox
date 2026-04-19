# Producer Contract And Observability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden producer enqueue behavior, widen Sentry baggage storage, add committed enqueue metrics, extend startup validation, reduce redaction overhead, extend inspection redaction to nested signatures, and document the producer signal contract without changing the public producer API.

**Architecture:** Keep `OutboxCelery.send_task()` as the orchestration seam in `django_celery_outbox/app.py`. Add small internal helpers for safe signal emission, best-effort committed metrics, validated settings loading, and inspection-only nested option redaction. Reuse the existing Django checks framework so runtime behavior and `manage.py check` stay aligned.

**Tech Stack:** Django ORM/migrations, Celery, structlog, sentry-sdk, StatsD metrics wrapper, pytest, docker compose

---

### Task 1: Safe Producer Signal And Committed Enqueue Metric

**Files:**
- Modify: `django_celery_outbox/app.py`
- Modify: `django_celery_outbox/app_tests.py`

- [ ] **Step 1: Write the failing tests**

```python
@patch('django_celery_outbox.app._logger')
@pytest.mark.django_db
def test_send_task_ignores_outbox_message_created_receiver_exception(
    m_logger: MagicMock,
    f_app: OutboxCelery,
) -> None:
    def boom(sender: type, **kwargs: object) -> None:
        raise RuntimeError('boom')

    outbox_message_created.connect(boom)
    try:
        result = f_app.send_task('my.task', task_id='safe-signal-1')
    finally:
        outbox_message_created.disconnect(boom)

    assert result.id == 'safe-signal-1'
    assert CeleryOutbox.objects.filter(task_id='safe-signal-1').exists()
    m_logger.error.assert_any_call(
        'celery_outbox_signal_error',
        signal='outbox_message_created',
        task_id='safe-signal-1',
        task_name='my.task',
        receiver='boom',
        exc_info=True,
    )


@pytest.mark.django_db(transaction=True)
def test_messages_enqueued_increments_only_after_commit(
    f_app: OutboxCelery,
    mocker,
) -> None:
    increment = mocker.patch('django_celery_outbox.app.metrics.increment')

    with transaction.atomic():
        f_app.send_task('my.task', task_id='metric-commit-1')
        increment.assert_not_called()

    increment.assert_called_once_with('messages.enqueued', tags={'task_name': 'my.task'})


@pytest.mark.django_db(transaction=True)
def test_messages_enqueued_not_emitted_on_rollback(
    f_app: OutboxCelery,
    mocker,
) -> None:
    increment = mocker.patch('django_celery_outbox.app.metrics.increment')

    with pytest.raises(RuntimeError, match='rollback'):
        with transaction.atomic():
            f_app.send_task('my.task', task_id='metric-rollback-1')
            raise RuntimeError('rollback')

    increment.assert_not_called()


@patch.object(Celery, 'send_task', return_value=MagicMock(spec=AsyncResult))
@pytest.mark.django_db(transaction=True)
def test_send_task_excluded_does_not_increment_messages_enqueued(
    m_super_send: MagicMock,
    f_app: OutboxCelery,
    mocker,
) -> None:
    increment = mocker.patch('django_celery_outbox.app.metrics.increment')

    with override_settings(CELERY_OUTBOX_EXCLUDE_TASKS={'my.excluded.task'}):
        f_app.send_task('my.excluded.task')

    increment.assert_not_called()
    m_super_send.assert_called_once()


@patch('django_celery_outbox.app._logger')
@pytest.mark.django_db(transaction=True)
def test_messages_enqueued_metric_errors_are_logged_and_swallowed(
    m_logger: MagicMock,
    f_app: OutboxCelery,
    mocker,
) -> None:
    mocker.patch('django_celery_outbox.app.metrics.increment', side_effect=RuntimeError('statsd down'))

    result = f_app.send_task('my.task', task_id='metric-error-1')

    assert result.id == 'metric-error-1'
    assert CeleryOutbox.objects.filter(task_id='metric-error-1').exists()
    m_logger.warning.assert_any_call(
        'celery_outbox_metric_error',
        metric='messages.enqueued',
        task_name='my.task',
        exc_info=True,
    )
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
docker compose run --rm app python -m pytest django_celery_outbox/app_tests.py -k "receiver_exception or messages_enqueued or metric_error" -v
```

Expected: FAIL because `outbox_message_created.send()` still bubbles receiver errors and `messages.enqueued` does not exist.

- [ ] **Step 3: Implement safe signal delivery and best-effort committed metric**

```python
def _send_signal_safe(*, signal: Signal, signal_name: str, task_id: str, task_name: str) -> None:
    for receiver, response in signal.send_robust(
        sender=OutboxCelery,
        task_id=task_id,
        task_name=task_name,
    ):
        if isinstance(response, Exception):
            _logger.error(
                'celery_outbox_signal_error',
                signal=signal_name,
                task_id=task_id,
                task_name=task_name,
                receiver=getattr(receiver, '__qualname__', repr(receiver)),
                exc_info=True,
            )


def _emit_enqueued_metric_safe(task_name: str) -> None:
    try:
        metrics.increment('messages.enqueued', tags=get_task_tag(task_name))
    except Exception:
        _logger.warning(
            'celery_outbox_metric_error',
            metric='messages.enqueued',
            task_name=task_name,
            exc_info=True,
        )
```

```python
CeleryOutbox.objects.create(
    task_id=task_id,
    task_name=name,
    args=args_list,
    kwargs=kwargs_dict,
    redacted_args=stored_redacted_args,
    redacted_kwargs=stored_redacted_kwargs,
    options=serialized_options,
    schema_version=CURRENT_SCHEMA_VERSION,
    sentry_trace_id=sentry_sdk.get_traceparent(),
    sentry_baggage=sentry_sdk.get_baggage(),
    structlog_context=get_structlog_context_json(),
)
_send_signal_safe(
    signal=outbox_message_created,
    signal_name='outbox_message_created',
    task_id=task_id,
    task_name=name,
)
transaction.on_commit(
    lambda: _emit_enqueued_metric_safe(name),
    using=CeleryOutbox.objects.db,
)
```

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
docker compose run --rm app python -m pytest django_celery_outbox/app_tests.py -k "receiver_exception or messages_enqueued or metric_error" -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/app.py django_celery_outbox/app_tests.py
git commit -m "feat: harden producer signal delivery and enqueue metrics"
```

### Task 2: Widen `sentry_baggage` Storage

**Files:**
- Modify: `django_celery_outbox/models.py`
- Create: `django_celery_outbox/migrations/0004_widen_sentry_baggage.py`
- Modify: `django_celery_outbox/models_tests.py`
- Modify: `django_celery_outbox/app_tests.py`
- Modify: `django_celery_outbox/integration_tests.py`

- [ ] **Step 1: Add regression tests for long baggage values**

```python
@patch('django_celery_outbox.app.sentry_sdk')
@pytest.mark.django_db
def test_send_task_accepts_long_sentry_baggage(
    m_sentry: MagicMock,
    f_app: OutboxCelery,
) -> None:
    baggage = 'x' * 3000
    m_sentry.get_traceparent.return_value = 'trace-1'
    m_sentry.get_baggage.return_value = baggage

    f_app.send_task('my.task', task_id='long-baggage-1')

    assert CeleryOutbox.objects.get(task_id='long-baggage-1').sentry_baggage == baggage


@pytest.mark.django_db
def test_e2e_dead_letter_preserves_long_sentry_baggage(f_relay: Relay) -> None:
    baggage = 'x' * 3000
    CeleryOutbox.objects.create(
        task_id='dead-letter-baggage-1',
        task_name='my.task',
        options={},
        retries=2,
        sentry_baggage=baggage,
    )

    with patch('django_celery_outbox.relay._publisher.Celery.send_task', side_effect=RuntimeError('fail')):
        with patch('django_celery_outbox.relay._relay.time.sleep'):
            f_relay._processing()

    dead = CeleryOutboxDeadLetter.objects.get(task_id='dead-letter-baggage-1')
    assert dead.sentry_baggage == baggage


def test_sentry_baggage_fields_are_text_fields() -> None:
    assert CeleryOutbox._meta.get_field('sentry_baggage').get_internal_type() == 'TextField'
    assert CeleryOutboxDeadLetter._meta.get_field('sentry_baggage').get_internal_type() == 'TextField'
```

- [ ] **Step 2: Run the baggage regression tests**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/models_tests.py \
  django_celery_outbox/app_tests.py \
  django_celery_outbox/integration_tests.py \
  -k "sentry_baggage or long_baggage" -v
```

Expected: FAIL with the current `CharField(max_length=2048)` schema.

- [ ] **Step 3: Implement the model change and migration**

```python
sentry_baggage = models.TextField(null=True, blank=True)
```

```python
class Migration(migrations.Migration):
    dependencies = [
        ('django_celery_outbox', '0003_redacted_payload_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='celeryoutbox',
            name='sentry_baggage',
            field=models.TextField(null=True, blank=True),
        ),
        migrations.AlterField(
            model_name='celeryoutboxdeadletter',
            name='sentry_baggage',
            field=models.TextField(null=True, blank=True),
        ),
    ]
```

- [ ] **Step 4: Run the focused tests and migration smoke**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/models_tests.py \
  django_celery_outbox/app_tests.py \
  django_celery_outbox/integration_tests.py \
  -k "sentry_baggage or long_baggage" -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/models.py django_celery_outbox/migrations/0004_widen_sentry_baggage.py django_celery_outbox/models_tests.py django_celery_outbox/app_tests.py django_celery_outbox/integration_tests.py
git commit -m "feat: widen sentry baggage storage"
```

### Task 3: Extend Checks For Redactor And DLQ Retention

**Files:**
- Modify: `django_celery_outbox/_settings.py`
- Modify: `django_celery_outbox/checks.py`
- Modify: `django_celery_outbox/checks_tests.py`
- Modify: `django_celery_outbox/settings_tests.py`
- Modify: `django_celery_outbox/tasks.py`
- Modify: `django_celery_outbox/tasks_tests.py`
- Modify: `django_celery_outbox/management/commands/celery_outbox_purge_dead_letter.py`
- Modify: `django_celery_outbox/management/commands/celery_outbox_purge_dead_letter_tests.py`

- [ ] **Step 1: Write failing check and runtime-parity tests**

```python
@override_settings(CELERY_OUTBOX_PII_REDACTOR='missing.module.redactor')
def test_check_celery_outbox_redactor_setting_returns_error_for_invalid_path() -> None:
    errors = check_celery_outbox_redactor_setting(None)
    assert [error.id for error in errors] == ['celery_outbox.E007']


def bad_redactor_signature(task_name: str, args: list) -> tuple[list, dict]:
    return args, {}


@override_settings(CELERY_OUTBOX_PII_REDACTOR='django_celery_outbox.checks_tests.bad_redactor_signature')
def test_check_celery_outbox_redactor_setting_returns_error_for_bad_signature() -> None:
    errors = check_celery_outbox_redactor_setting(None)
    assert [error.id for error in errors] == ['celery_outbox.E007']


@override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '30x'})
def test_check_celery_outbox_dlq_retention_setting_returns_error_for_bad_duration() -> None:
    errors = check_celery_outbox_dlq_retention_setting(None)
    assert [error.id for error in errors] == ['celery_outbox.E008']


@override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '7d', 'task_name': 'myapp.*'})
@patch('django_celery_outbox.tasks.purge_dead_letter')
def test_purge_dead_letter_task_reuses_validated_retention_setting(m_purge: MagicMock) -> None:
    m_purge.return_value = PurgeResult(deleted_count=0, task_names={})

    purge_dead_letter_task()

    m_purge.assert_called_once_with(
        older_than_dead=timedelta(days=7),
        older_than_created=None,
        task_name_pattern='myapp.*',
        dry_run=False,
    )


@override_settings(CELERY_OUTBOX_DLQ_RETENTION={'older_than_dead': '7d', 'task_name': 'myapp.*'})
@patch('django_celery_outbox.management.commands.celery_outbox_purge_dead_letter.purge_dead_letter')
def test_purge_dead_letter_command_reuses_validated_retention_setting(m_purge: MagicMock) -> None:
    m_purge.return_value = PurgeResult(deleted_count=0, task_names={})

    call_command('celery_outbox_purge_dead_letter')

    m_purge.assert_called_once_with(
        older_than_dead=timedelta(days=7),
        older_than_created=None,
        task_name_pattern='myapp.*',
        dry_run=False,
    )
```

- [ ] **Step 2: Run the failing check tests**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/checks_tests.py \
  django_celery_outbox/settings_tests.py \
  django_celery_outbox/tasks_tests.py \
  django_celery_outbox/management/commands/celery_outbox_purge_dead_letter_tests.py \
  -k "E007 or E008 or redactor or dlq_retention" -v
```

Expected: FAIL because the new helpers and checks do not exist.

- [ ] **Step 3: Implement shared validation helpers and check registration**

```python
def load_pii_redactor_setting() -> Callable[[str, list, dict], tuple[list, dict]] | None:
    value = getattr(settings, 'CELERY_OUTBOX_PII_REDACTOR', None)
    if value is None:
        return None
    if isinstance(value, str):
        value = import_string(value)
    if not callable(value):
        raise TypeError('CELERY_OUTBOX_PII_REDACTOR must be a callable or dotted path.')
    inspect.signature(value).bind('', [], {})
    return cast(Callable[[str, list, dict], tuple[list, dict]], value)


def load_dlq_retention_setting() -> dict[str, timedelta | str | None] | None:
    retention = getattr(settings, 'CELERY_OUTBOX_DLQ_RETENTION', None)
    if retention is None:
        return None
    if not isinstance(retention, dict):
        raise TypeError('CELERY_OUTBOX_DLQ_RETENTION must be a dict.')
    if not retention.get('older_than_dead') and not retention.get('older_than_created'):
        raise ValueError('CELERY_OUTBOX_DLQ_RETENTION must specify older_than_dead or older_than_created')
    older_than_dead = parse_duration(retention['older_than_dead']) if retention.get('older_than_dead') else None
    older_than_created = parse_duration(retention['older_than_created']) if retention.get('older_than_created') else None
    return {
        'older_than_dead': older_than_dead,
        'older_than_created': older_than_created,
        'task_name_pattern': retention.get('task_name'),
    }
```

```python
@register()
def check_celery_outbox_redactor_setting(app_configs: object, **kwargs: object) -> list[Error]:
    try:
        load_pii_redactor_setting()
    except (ImportError, TypeError, ValueError) as exc:
        return [Error(str(exc), hint='Set CELERY_OUTBOX_PII_REDACTOR to None, a dotted path, or a callable(task_name, args, kwargs).', id='celery_outbox.E007')]
    return []


@register()
def check_celery_outbox_dlq_retention_setting(app_configs: object, **kwargs: object) -> list[Error]:
    try:
        load_dlq_retention_setting()
    except (TypeError, ValueError) as exc:
        return [Error(str(exc), hint='Use the same keys supported by celery_outbox_purge_dead_letter.', id='celery_outbox.E008')]
    return []
```

```python
retention = load_dlq_retention_setting()
if retention is None:
    raise ValueError('CELERY_OUTBOX_DLQ_RETENTION setting is required for purge_dead_letter task')

result = purge_dead_letter(
    older_than_dead=cast(timedelta | None, retention['older_than_dead']),
    older_than_created=cast(timedelta | None, retention['older_than_created']),
    task_name_pattern=cast(str | None, retention['task_name_pattern']),
    dry_run=False,
)
```

```python
retention = load_dlq_retention_setting()

def _get_duration(self, key: str, options: dict[str, Any], cli_has_retention: bool) -> timedelta | None:
    cli_value = options.get(key)
    if cli_value:
        return parse_duration(cli_value)
    if cli_has_retention or retention is None:
        return None
    return cast(timedelta | None, retention[key])


def _get_task_name_pattern(self, options: dict[str, Any], cli_has_retention: bool) -> str | None:
    cli_value = options.get('task_name')
    if cli_value:
        return cli_value
    if cli_has_retention or retention is None:
        return None
    return cast(str | None, retention['task_name_pattern'])
```

- [ ] **Step 4: Re-run the focused check tests**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/checks_tests.py \
  django_celery_outbox/settings_tests.py \
  django_celery_outbox/tasks_tests.py \
  django_celery_outbox/management/commands/celery_outbox_purge_dead_letter_tests.py \
  -k "E007 or E008 or redactor or dlq_retention" -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/_settings.py django_celery_outbox/checks.py django_celery_outbox/checks_tests.py django_celery_outbox/settings_tests.py django_celery_outbox/tasks.py django_celery_outbox/tasks_tests.py django_celery_outbox/management/commands/celery_outbox_purge_dead_letter.py django_celery_outbox/management/commands/celery_outbox_purge_dead_letter_tests.py
git commit -m "feat: validate producer redactor and dlq retention settings"
```

### Task 4: Reduce Copy Cost And Lock The Top-Level Redactor Contract

**Files:**
- Modify: `django_celery_outbox/app.py`
- Modify: `django_celery_outbox/app_tests.py`

- [ ] **Step 1: Add failing top-level redactor contract tests**

```python
@pytest.mark.django_db
def test_send_task_redactor_invoked_once_for_top_level_payload(
    f_app: OutboxCelery,
    mocker,
) -> None:
    redactor = mocker.Mock(return_value=([{'email': '[REDACTED]'}], {'token': '[REDACTED]'}))

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=redactor):
        f_app.send_task(
            'test.task',
            args=({'email': 'user@example.com'},),
            kwargs={'token': 'secret'},
        )

    redactor.assert_called_once_with(
        'test.task',
        [{'email': 'user@example.com'}],
        {'token': 'secret'},
    )


@pytest.mark.django_db
def test_send_task_without_redactor_skips_deepcopy(
    f_app: OutboxCelery,
    mocker,
) -> None:
    m_deepcopy = mocker.patch('django_celery_outbox.app.deepcopy')

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=None):
        f_app.send_task('test.task', args=({'email': 'user@example.com'},), kwargs={'token': 'secret'})

    m_deepcopy.assert_not_called()


@pytest.mark.django_db
def test_send_task_with_redactor_clones_payload_once(
    f_app: OutboxCelery,
    mocker,
) -> None:
    from copy import deepcopy as real_deepcopy

    m_deepcopy = mocker.patch('django_celery_outbox.app.deepcopy', side_effect=real_deepcopy)

    with override_settings(CELERY_OUTBOX_PII_REDACTOR='django_celery_outbox.app_tests.sample_redactor'):
        f_app.send_task('test.task', args=({'email': 'user@example.com'},), kwargs={'email': 'user@example.com'})

    m_deepcopy.assert_called_once()
```

- [ ] **Step 2: Run the focused redactor contract tests**

Run:

```bash
docker compose run --rm app python -m pytest django_celery_outbox/app_tests.py -k "redactor_invoked_once or skips_deepcopy or clones_payload_once" -v
```

Expected: FAIL until the top-level redaction path is centralized.

- [ ] **Step 3: Consolidate the top-level redaction helper**

```python
def _build_redacted_payloads(
    task_name: str,
    args_list: list[Any],
    kwargs_dict: dict[str, Any],
) -> tuple[list[Any] | None, dict[str, Any] | None]:
    redactor = _get_redactor()
    if redactor is None:
        return None, None

    payload = deepcopy(
        {
            'args': args_list,
            'kwargs': kwargs_dict,
        }
    )
    redacted_args, redacted_kwargs = redactor(
        task_name,
        payload['args'],
        payload['kwargs'],
    )
    return (
        redacted_args if redacted_args != args_list else None,
        redacted_kwargs if redacted_kwargs != kwargs_dict else None,
    )
```

```python
stored_redacted_args, stored_redacted_kwargs = _build_redacted_payloads(
    name,
    args_list,
    kwargs_dict,
)
```

- [ ] **Step 4: Re-run the focused redactor contract tests**

Run:

```bash
docker compose run --rm app python -m pytest django_celery_outbox/app_tests.py -k "redactor_invoked_once or skips_deepcopy or clones_payload_once" -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/app.py django_celery_outbox/app_tests.py
git commit -m "refactor: centralize top level producer redaction"
```

### Task 5: Add Inspection-Time Nested Redaction And Document The Signal Contract

**Files:**
- Modify: `django_celery_outbox/app.py`
- Modify: `django_celery_outbox/models.py`
- Modify: `django_celery_outbox/admin.py`
- Modify: `django_celery_outbox/app_tests.py`
- Modify: `django_celery_outbox/models_tests.py`
- Modify: `django_celery_outbox/admin_tests.py`
- Modify: `django_celery_outbox/signals_tests.py`
- Modify: `docs/architecture.md`
- Modify: `docs/configuration.md`
- Modify: `docs/observability/metrics.md`

- [ ] **Step 1: Add failing nested-redaction, admin, and signal-contract tests**

```python
def _redact_payloads(task_name: str, args: list, kwargs: dict) -> tuple[list, dict]:
    redacted_args = [
        {'email': '[REDACTED]'} if isinstance(item, dict) and 'email' in item else item
        for item in args
    ]
    redacted_kwargs = {
        key: '[REDACTED]' if key in {'email', 'token'} else value
        for key, value in kwargs.items()
    }
    return redacted_args, redacted_kwargs


@pytest.mark.django_db
def test_outbox_inspection_options_redacts_link_signature() -> None:
    msg = CeleryOutbox.objects.create(
        task_id='inspect-link-1',
        task_name='parent.task',
        options={
            'link': [
                {
                    'task': 'callback.task',
                    'args': [{'email': 'user@example.com'}],
                    'kwargs': {'token': 'secret'},
                    'options': {},
                    'subtask_type': None,
                    'immutable': False,
                    'chord_size': None,
                }
            ],
        },
    )

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=_redact_payloads):
        assert msg.inspection_options['link'][0]['kwargs']['token'] == '[REDACTED]'


@pytest.mark.django_db
def test_outbox_inspection_options_redacts_link_error_chain_and_chord() -> None:
    msg = CeleryOutbox.objects.create(
        task_id='inspect-nested-1',
        task_name='parent.task',
        options={
            'link_error': [
                {
                    'task': 'error.task',
                    'args': [],
                    'kwargs': {'token': 'secret'},
                    'options': {},
                    'subtask_type': None,
                    'immutable': False,
                    'chord_size': None,
                }
            ],
            'chain': [
                {
                    'task': 'chain.task',
                    'args': [{'email': 'user@example.com'}],
                    'kwargs': {},
                    'options': {},
                    'subtask_type': None,
                    'immutable': False,
                    'chord_size': None,
                }
            ],
            'chord': {
                'task': 'chord.task',
                'args': [],
                'kwargs': {'token': 'secret'},
                'options': {},
                'subtask_type': None,
                'immutable': False,
                'chord_size': None,
            },
        },
    )

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=_redact_payloads):
        inspected = msg.inspection_options

    assert inspected['link_error'][0]['kwargs']['token'] == '[REDACTED]'
    assert inspected['chain'][0]['args'][0]['email'] == '[REDACTED]'
    assert inspected['chord']['kwargs']['token'] == '[REDACTED]'


@patch('django_celery_outbox.app._logger')
@pytest.mark.django_db
def test_outbox_inspection_options_falls_back_to_raw_options_when_nested_redaction_fails(
    m_logger: MagicMock,
) -> None:
    def bad_redactor(task_name: str, args: list, kwargs: dict) -> tuple[list, dict]:
        raise RuntimeError('broken nested redaction')

    msg = CeleryOutbox.objects.create(
        task_id='inspect-fallback-1',
        task_name='parent.task',
        options={'link': [{'task': 'callback.task', 'args': [], 'kwargs': {'token': 'secret'}, 'options': {}, 'subtask_type': None, 'immutable': False, 'chord_size': None}]},
    )

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=bad_redactor):
        assert msg.inspection_options == msg.options

    m_logger.warning.assert_any_call(
        'celery_outbox_inspection_redaction_failed',
        task_name='parent.task',
        exc_info=True,
    )


@pytest.mark.django_db
def test_admin_display_options_uses_inspection_options() -> None:
    admin_instance: CeleryOutboxAdmin = admin.site._registry[CeleryOutbox]  # type: ignore[assignment]
    entry = CeleryOutboxFactory.build(
        task_name='parent.task',
        options={'link': [{'task': 'callback.task', 'args': [], 'kwargs': {'token': 'secret'}, 'options': {}, 'subtask_type': None, 'immutable': False, 'chord_size': None}]},
    )

    with override_settings(CELERY_OUTBOX_PII_REDACTOR=_redact_payloads):
        displayed = admin_instance.display_options(entry)

    assert displayed['link'][0]['kwargs']['token'] == '[REDACTED]'


def test_readonly_fields() -> None:
    admin_instance = admin.site._registry[CeleryOutbox]
    expected = [
        'id',
        'task_name',
        'task_id',
        'display_args',
        'display_kwargs',
        'display_options',
        'retries',
        'schema_version',
        'created_at',
        'updated_at',
        'retry_after',
        'sentry_trace_id',
        'sentry_baggage',
        'structlog_context',
    ]

    assert admin_instance.readonly_fields == expected


def test_dead_letter_readonly_fields_use_display_options() -> None:
    dead_letter_admin = admin.site._registry[CeleryOutboxDeadLetter]

    assert 'display_options' in dead_letter_admin.readonly_fields
    assert 'options' not in dead_letter_admin.readonly_fields


@pytest.mark.django_db
def test_outbox_message_created_signal_contract_matches_documented_kwargs() -> None:
    app = OutboxCelery('test')
    received: list[dict[str, object]] = []

    def handler(sender: type, **kwargs: object) -> None:
        received.append(kwargs)

    outbox_message_created.connect(handler)
    try:
        app.send_task('signal.created', task_id='signal-created-1')
    finally:
        outbox_message_created.disconnect(handler)

    assert sorted(received[0]) == ['signal', 'task_id', 'task_name']


@pytest.mark.django_db
def test_relay_signal_contracts_match_documented_kwargs(f_relay: Relay) -> None:
    sent_msg = CeleryOutboxFactory.create(task_id='signal-sent-1', task_name='signal.sent', options={}, retries=0)
    failed_msg = CeleryOutboxFactory.create(task_id='signal-failed-1', task_name='signal.failed', options={}, retries=0)
    sent_received: list[dict[str, object]] = []
    failed_received: list[dict[str, object]] = []

    def sent_handler(sender: type, **kwargs: object) -> None:
        sent_received.append(kwargs)

    def failed_handler(sender: type, **kwargs: object) -> None:
        failed_received.append(kwargs)

    outbox_message_sent.connect(sent_handler)
    outbox_message_failed.connect(failed_handler)
    try:
        with patch.object(f_relay._publisher, 'publish', side_effect=[None, RuntimeError('boom')]):
            f_relay._process_messages([sent_msg, failed_msg])
    finally:
        outbox_message_sent.disconnect(sent_handler)
        outbox_message_failed.disconnect(failed_handler)

    assert sorted(sent_received[0]) == ['signal', 'task_id', 'task_name']
    assert sorted(failed_received[0]) == ['retries', 'signal', 'task_id', 'task_name']


@pytest.mark.django_db
def test_outbox_message_dead_lettered_signal_contract_matches_documented_kwargs(m_celery_app: MagicMock) -> None:
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(batch_size=10, idle_time=0.01, backoff_time=120, max_retries=3),
    )
    CeleryOutboxFactory.create(task_id='signal-dead-1', task_name='signal.dead', options={}, retries=3)
    received: list[dict[str, object]] = []

    def handler(sender: type, **kwargs: object) -> None:
        received.append(kwargs)

    outbox_message_dead_lettered.connect(handler)
    try:
        with patch('django_celery_outbox.relay._publisher.Celery.send_task'):
            with patch('django_celery_outbox.relay._relay.time.sleep'):
                with patch('django_celery_outbox.relay._relay.close_old_connections'):
                    relay._processing()
    finally:
        outbox_message_dead_lettered.disconnect(handler)

    assert sorted(received[0]) == ['signal', 'task_ids', 'task_names']
```

- [ ] **Step 2: Run the inspection-focused tests**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/app_tests.py \
  django_celery_outbox/models_tests.py \
  django_celery_outbox/admin_tests.py \
  django_celery_outbox/signals_tests.py \
  -k "inspection_options or display_options or readonly_fields or signal_contract" -v
```

Expected: FAIL because nested signature redaction is not implemented, admin still displays raw `options`, and the docs contract is incomplete.

- [ ] **Step 3: Implement `inspection_options`, safe fallback, admin display, and docs updates**

```python
def _redact_serialized_signature(
    task_name: str,
    signature: dict[str, Any],
    redactor: Callable[[str, list, dict], tuple[list, dict]],
) -> dict[str, Any]:
    redacted_args, redacted_kwargs = redactor(
        task_name,
        deepcopy(list(signature.get('args', []))),
        deepcopy(dict(signature.get('kwargs', {}))),
    )
    updated = dict(signature)
    updated['args'] = redacted_args
    updated['kwargs'] = redacted_kwargs
    return updated


def _redact_options_for_inspection(task_name: str, options: dict[str, Any]) -> dict[str, Any]:
    redactor = _get_redactor()
    if redactor is None:
        return options

    try:
        cloned = deepcopy(options)
        for key in ('link', 'link_error', 'chain'):
            if key in cloned and isinstance(cloned[key], list):
                cloned[key] = [
                    _redact_serialized_signature(task_name, item, redactor)
                    if isinstance(item, dict)
                    else item
                    for item in cloned[key]
                ]
        if 'chord' in cloned and isinstance(cloned['chord'], dict):
            cloned['chord'] = _redact_serialized_signature(task_name, cloned['chord'], redactor)
        return cloned
    except Exception:
        _logger.warning(
            'celery_outbox_inspection_redaction_failed',
            task_name=task_name,
            exc_info=True,
        )
        return options
```

```python
class CeleryOutbox(models.Model):
    @property
    def inspection_options(self) -> dict:
        return _redact_options_for_inspection(self.task_name, self.options)


class CeleryOutboxDeadLetter(models.Model):
    @property
    def inspection_options(self) -> dict:
        return _redact_options_for_inspection(self.task_name, self.options)
```

```python
class CeleryOutboxAdmin(admin.ModelAdmin):
    readonly_fields = [
        'id',
        'task_name',
        'task_id',
        'display_args',
        'display_kwargs',
        'display_options',
        'retries',
        'schema_version',
        'created_at',
        'updated_at',
        'retry_after',
        'sentry_trace_id',
        'sentry_baggage',
        'structlog_context',
    ]

    @admin.display(description='options')
    def display_options(self, obj: CeleryOutbox) -> dict:
        return obj.inspection_options


class CeleryOutboxDeadLetterAdmin(admin.ModelAdmin):
    readonly_fields = [
        'id',
        'task_name',
        'task_id',
        'display_args',
        'display_kwargs',
        'display_options',
        'retries',
        'schema_version',
        'created_at',
        'dead_at',
        'sentry_trace_id',
        'sentry_baggage',
        'structlog_context',
        'failure_reason',
    ]

    @admin.display(description='options')
    def display_options(self, obj: CeleryOutboxDeadLetter) -> dict:
        return obj.inspection_options
```

```markdown
| `messages.enqueued` | counter | `task_name` | Committed outbox rows only; rollback and excluded-task bypass do not emit it |

| Signal | kwargs | When |
|--------|--------|------|
| `outbox_message_created` | `task_id`, `task_name` | After outbox row insert, before commit; receiver failures are logged and swallowed |
| `outbox_message_sent` | `task_id`, `task_name` | Relay publish success |
| `outbox_message_failed` | `task_id`, `task_name`, `retries` | Relay non-outage retryable failure |
| `outbox_message_dead_lettered` | `task_ids`, `task_names` | Relay dead-letter move |
```

- [ ] **Step 4: Re-run tests and docs smoke**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/app_tests.py \
  django_celery_outbox/models_tests.py \
  django_celery_outbox/admin_tests.py \
  django_celery_outbox/signals_tests.py \
  -k "inspection_options or display_options or readonly_fields or signal_contract" -v
docker compose run --rm app bash -lc "rg -n 'messages\\.enqueued|outbox_message_created|outbox_message_sent|outbox_message_failed|outbox_message_dead_lettered' docs/architecture.md docs/configuration.md docs/observability/metrics.md"
docker compose run --rm app bash -lc "pip install -q -e .[docs] && mkdocs build --strict"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/app.py django_celery_outbox/models.py django_celery_outbox/admin.py django_celery_outbox/app_tests.py django_celery_outbox/models_tests.py django_celery_outbox/admin_tests.py django_celery_outbox/signals_tests.py docs/architecture.md docs/configuration.md docs/observability/metrics.md
git commit -m "feat: extend producer inspection redaction and signal docs"
```

### Task 6: Final Verification Sweep

**Files:**
- Verify only

- [ ] **Step 1: Run producer-focused verification**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/app_tests.py \
  django_celery_outbox/models_tests.py \
  django_celery_outbox/checks_tests.py \
  django_celery_outbox/settings_tests.py \
  django_celery_outbox/tasks_tests.py \
  django_celery_outbox/admin_tests.py \
  django_celery_outbox/signals_tests.py \
  django_celery_outbox/integration_tests.py \
  django_celery_outbox/management/commands/celery_outbox_purge_dead_letter_tests.py \
  -v
docker compose run --rm app python manage.py check
docker compose run --rm app bash -lc "pip install -q -e .[docs] && mkdocs build --strict"
```

Expected: PASS across tests, checks, and docs build.

- [ ] **Step 2: Commit the verification checkpoint**

```bash
git commit --allow-empty -m "chore: verify producer hardening plan"
```
