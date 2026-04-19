# Operator Observability And Recovery Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align bundled operator docs and alerts with real runtime signals, fix admin backlog visibility, and add a built-in DLQ replay CLI.

**Architecture:** Keep the package's operator surface split between docs, admin, and management commands. Reuse the relay hot-path plan's shared backlog semantics instead of inventing a second definition. Build the replay CLI on the same helper used by the admin bulk action so replay logic stays single-sourced.

**Tech Stack:** Django admin, Django management commands, Markdown/YAML docs, pytest, docker compose

---

### Task 1: Fix Admin Backlog Semantics

**Files:**
- Modify: `django_celery_outbox/admin.py`
- Modify: `django_celery_outbox/admin_tests.py`
- Modify: `django_celery_outbox/stats.py`
- Modify: `django_celery_outbox/templates/admin/django_celery_outbox/celeryoutbox/change_list.html`

Precondition:

- Do not execute this task before the relay hot-path plan lands the shared `queue_depth == live_backlog` semantics in `django_celery_outbox/stats.py`.

- [ ] **Step 1: Add failing admin parity tests**

```python
@pytest.mark.django_db
def test_changelist_view_uses_live_backlog_from_queue_stats() -> None:
    CeleryOutboxFactory.create(task_id='never-1', task_name='some.task', updated_at=None)
    CeleryOutboxFactory.create(
        task_id='retry-1',
        task_name='some.task',
        updated_at=timezone.now(),
        retry_after=timezone.now() - timedelta(seconds=30),
    )
    CeleryOutboxFactory.create(
        task_id='inflight-1',
        task_name='some.task',
        updated_at=timezone.now(),
        retry_after=None,
    )

    admin_instance = admin.site._registry[CeleryOutbox]
    m_request = MagicMock()
    m_request.GET = {}

    with patch.object(admin.ModelAdmin, 'changelist_view', return_value=MagicMock()) as m_super:
        admin_instance.changelist_view(m_request)

    extra_context = m_super.call_args.kwargs['extra_context']
    assert extra_context['live_backlog'] == 2
    assert extra_context['never_attempted'] == 1


@pytest.mark.django_db
def test_changelist_view_oldest_pending_uses_shared_queue_stats_snapshot() -> None:
    pending = CeleryOutboxFactory.create(task_id='oldest-1', task_name='some.task', updated_at=None)
    CeleryOutbox.objects.filter(pk=pending.pk).update(created_at=timezone.now() - timedelta(minutes=2))

    admin_instance = admin.site._registry[CeleryOutbox]
    m_request = MagicMock()
    m_request.GET = {}

    with patch.object(admin.ModelAdmin, 'changelist_view', return_value=MagicMock()) as m_super:
        admin_instance.changelist_view(m_request)

    extra_context = m_super.call_args.kwargs['extra_context']
    assert isinstance(extra_context['oldest_pending'], timedelta)
    assert extra_context['oldest_pending'] >= timedelta(seconds=110)
```

- [ ] **Step 2: Run the focused admin tests**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/admin_tests.py::test_changelist_view_uses_live_backlog_from_queue_stats \
  django_celery_outbox/admin_tests.py::test_changelist_view_oldest_pending_uses_shared_queue_stats_snapshot \
  -v
```

Expected: FAIL because admin still treats `updated_at IS NULL` as backlog and the changelist template still renders `Pending` instead of `Live backlog`.

- [ ] **Step 3: Implement the admin summary change**

```python
stats = get_queue_stats(top_n=0)
extra_context['live_backlog'] = stats.queue_depth
extra_context['never_attempted'] = CeleryOutbox.objects.filter(updated_at__isnull=True).count()
extra_context['failed_count'] = CeleryOutbox.objects.filter(retries__gt=0).count()
extra_context['total_count'] = CeleryOutbox.objects.count()
extra_context['oldest_pending'] = (
    timedelta(seconds=stats.oldest_pending_seconds)
    if stats.oldest_pending_seconds is not None
    else None
)
```

```html
<li><strong>Total:</strong> {{ total_count }}</li>
<li><strong>Live backlog:</strong> {{ live_backlog }}</li>
<li><strong>Never attempted:</strong> {{ never_attempted }}</li>
<li><strong>Failed (retries &gt; 0):</strong> {{ failed_count }}</li>
<li><strong>Oldest pending:</strong> {% if oldest_pending %}{{ oldest_pending }}{% else %}None{% endif %}</li>
```

- [ ] **Step 4: Re-run the focused admin tests and template sanity check**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/admin_tests.py::test_changelist_view_uses_live_backlog_from_queue_stats \
  django_celery_outbox/admin_tests.py::test_changelist_view_oldest_pending_uses_shared_queue_stats_snapshot \
  -v
docker compose run --rm app bash -lc "rg -n 'Live backlog|Never attempted' django_celery_outbox/templates/admin/django_celery_outbox/celeryoutbox/change_list.html"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/admin.py django_celery_outbox/admin_tests.py django_celery_outbox/stats.py django_celery_outbox/templates/admin/django_celery_outbox/celeryoutbox/change_list.html
git commit -m "feat: align admin backlog semantics with relay queue depth"
```

### Task 2: Add Shared DLQ Replay Helper And CLI

**Files:**
- Add: `django_celery_outbox/replay.py`
- Add: `django_celery_outbox/replay_tests.py`
- Add: `django_celery_outbox/management/commands/celery_outbox_replay_dead_letter.py`
- Add: `django_celery_outbox/management/commands/celery_outbox_replay_dead_letter_tests.py`
- Modify: `django_celery_outbox/admin.py`
- Modify: `django_celery_outbox/admin_tests.py`

- [ ] **Step 1: Add failing replay tests**

```python
@pytest.mark.django_db
def test_replay_dead_letters_preserves_payload_and_schema_version() -> None:
    dead = CeleryOutboxDeadLetterFactory.create(
        task_id='replay-1',
        task_name='app.tasks.replay',
        args=[1, 2],
        kwargs={'key': 'value'},
        redacted_args=['[REDACTED]', 2],
        redacted_kwargs={'key': '[REDACTED]'},
        options={'queue': 'critical'},
        schema_version=2,
        sentry_trace_id='trace-1',
        sentry_baggage='baggage-1',
        structlog_context='{"request_id": "req-1"}',
    )

    count = replay_dead_letters([dead.pk])

    assert count == 1
    outbox = CeleryOutbox.objects.get(task_id='replay-1')
    assert outbox.args == [1, 2]
    assert outbox.kwargs == {'key': 'value'}
    assert outbox.redacted_kwargs == {'key': '[REDACTED]'}
    assert outbox.options == {'queue': 'critical'}
    assert outbox.schema_version == 2
    assert outbox.sentry_baggage == 'baggage-1'


@pytest.mark.django_db
def test_replay_command_replays_selected_ids_only() -> None:
    dead1 = CeleryOutboxDeadLetterFactory.create(task_id='cmd-replay-1')
    dead2 = CeleryOutboxDeadLetterFactory.create(task_id='cmd-replay-2')

    call_command('celery_outbox_replay_dead_letter', str(dead1.pk))

    assert CeleryOutbox.objects.filter(task_id='cmd-replay-1').exists()
    assert not CeleryOutbox.objects.filter(task_id='cmd-replay-2').exists()
    assert CeleryOutboxDeadLetter.objects.filter(pk=dead2.pk).exists()
```

- [ ] **Step 2: Run the focused replay tests**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/replay_tests.py \
  django_celery_outbox/admin_tests.py \
  django_celery_outbox/management/commands/celery_outbox_replay_dead_letter_tests.py \
  -k "replay or retry_selected" -v
```

Expected: FAIL because no shared replay helper or CLI exists.

- [ ] **Step 3: Implement the helper and command**

```python
def replay_dead_letters(dead_letter_ids: Sequence[int], *, limit: int | None = None) -> int:
    queryset = CeleryOutboxDeadLetter.objects.filter(pk__in=dead_letter_ids).order_by('pk')
    if limit is not None:
        queryset = queryset[:limit]

    rows = list(queryset)
    if not rows:
        return 0

    with transaction.atomic():
        CeleryOutbox.objects.bulk_create(
            [
                CeleryOutbox(
                    task_id=row.task_id,
                    task_name=row.task_name,
                    args=row.args,
                    kwargs=row.kwargs,
                    redacted_args=row.redacted_args,
                    redacted_kwargs=row.redacted_kwargs,
                    options=row.options,
                    schema_version=row.schema_version,
                    sentry_trace_id=row.sentry_trace_id,
                    sentry_baggage=row.sentry_baggage,
                    structlog_context=row.structlog_context,
                )
                for row in rows
            ]
        )
        CeleryOutboxDeadLetter.objects.filter(pk__in=[row.pk for row in rows]).delete()

    return len(rows)
```

```python
def add_arguments(self, parser: CommandParser) -> None:
    parser.add_argument('dead_letter_ids', nargs='+', type=int)
    parser.add_argument('--limit', type=int, default=None)
```

- [ ] **Step 4: Re-run replay tests**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/replay_tests.py \
  django_celery_outbox/admin_tests.py \
  django_celery_outbox/management/commands/celery_outbox_replay_dead_letter_tests.py \
  -k "replay or retry_selected" -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/replay.py django_celery_outbox/replay_tests.py django_celery_outbox/management/commands/celery_outbox_replay_dead_letter.py django_celery_outbox/management/commands/celery_outbox_replay_dead_letter_tests.py django_celery_outbox/admin.py django_celery_outbox/admin_tests.py
git commit -m "feat: add dead letter replay helper and cli"
```

### Task 3: Align Docs And Alert Artifacts

**Files:**
- Modify: `docs/observability/alert-rules.yml`
- Modify: `docs/observability/metrics.md`
- Modify: `docs/observability/logging-events.md`
- Modify: `docs/operations/runbook.md`
- Modify: `docs/operations/dead-letter.md`
- Modify: `docs/operations/admin-interface.md`
- Modify: `docs/deployment/database-setup.md`
- Modify: `docs/security.md`
- Modify: `docs/deployment/kubernetes.md`

- [ ] **Step 1: Add doc-level regression checks**

```bash
rg -n 'up\\{job="celery-outbox-relay"\\}|dead_letter\\.count > [0-9]+|GRANT ALL PRIVILEGES|terminationGracePeriodSeconds: 30' docs
```

- [ ] **Step 2: Run the doc sanity checks**

Run:

```bash
docker compose run --rm app bash -lc "rg -n 'up\\{job=\"celery-outbox-relay\"\\}|dead_letter\\.count > [0-9]+|GRANT ALL PRIVILEGES|terminationGracePeriodSeconds: 30' docs || true"
```

Expected: current docs still contain at least one of the stale relay-down alert, absolute dead-letter threshold, over-privileged DB grant, or undersized Kubernetes grace-period examples.

- [ ] **Step 3: Update docs and alert guidance**

```yaml
- alert: CeleryOutboxQueueAgeHigh
  expr: celery_outbox_oldest_pending_age_seconds > 60
  for: 10m

- alert: CeleryOutboxNewDeadLetters
  expr: increase(celery_outbox_messages_exceeded_total[10m]) > 0
  for: 0m
```

```markdown
- `celery_outbox_relay_iteration_failed` is the catch-all relay-loop failure event.
- Wire that log event into your log-alerting stack.
- Treat `celery_outbox_relay_breaker_open` as "relay alive but broker unavailable", not "relay dead".
```

```markdown
## docs/observability/metrics.md

- Replace absolute `dead_letter.count > 10` alert guidance with `increase(celery_outbox_messages_exceeded_total[10m]) > 0`.
- Document that `queue.depth` is the live backlog summary, not just `updated_at IS NULL`.
- Call out `celery_outbox_relay_breaker_open` as a broker-unavailable condition that should page differently from process-down alerts.

## docs/operations/admin-interface.md

- Rename the changelist summary terms to `Live backlog`, `Never attempted`, `Failed (retries > 0)`, and `Oldest pending`.
- Document `celery_outbox_replay_dead_letter <dead_letter_id_1> <dead_letter_id_2>` as the CLI counterpart to the admin `retry_selected` bulk action.
- Clarify that replay preserves stored payload/schema/context fields and removes replayed rows from the dead-letter table.

## docs/operations/dead-letter.md

- Replace any fixed `dead_letter.count > N` alert advice with `increase(celery_outbox_messages_exceeded_total[10m]) > 0`.
- Explain that replay is available both via the admin `retry_selected` action and the `celery_outbox_replay_dead_letter` CLI.
- Clarify that dead-letter growth should be triaged as new failures over time, not as a fixed table-size threshold.

## docs/deployment/database-setup.md

- Replace any `GRANT ALL PRIVILEGES` examples with least-privilege grants for the runtime app/relay role.
- Show the runtime role needing only the DML required by enqueue/relay/purge flows on the outbox tables, while schema migration privileges stay with a separate deploy role.
- Clarify that production runtime credentials should not own the schema or grant rights onward.

## docs/security.md

- Document least-privilege database credentials as the default security posture for app and relay processes.
- Call out dead-letter replay/purge commands as operator-only actions that should be audited and restricted.
- Link PII handling guidance back to the redaction/configuration docs so stored payload visibility is framed as a controlled operational surface.
```

```yaml
terminationGracePeriodSeconds: 120  # >= shutdown_timeout + send_timeout + margin
```

- [ ] **Step 4: Re-run docs checks and strict docs build**

Run:

```bash
docker compose run --rm app bash -lc "rg -n 'up\\{job=\"celery-outbox-relay\"\\}|dead_letter\\.count > [0-9]+|GRANT ALL PRIVILEGES|terminationGracePeriodSeconds: 30' docs || true"
docker compose run --rm app bash -lc "pip install -q -e .[docs] && mkdocs build --strict"
```

Expected: banned patterns gone; docs build passes.

- [ ] **Step 5: Commit**

```bash
git add docs/observability/alert-rules.yml docs/observability/metrics.md docs/observability/logging-events.md docs/operations/runbook.md docs/operations/dead-letter.md docs/operations/admin-interface.md docs/deployment/database-setup.md docs/security.md docs/deployment/kubernetes.md
git commit -m "docs: align operator alerts runbook and security guidance"
```

### Task 4: Final Verification Sweep

**Files:**
- Verify only

- [ ] **Step 1: Run the operator-focused verification suite**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/admin_tests.py \
  django_celery_outbox/replay_tests.py \
  django_celery_outbox/management/commands/celery_outbox_replay_dead_letter_tests.py \
  -v
docker compose run --rm app bash -lc "pip install -q -e .[docs] && mkdocs build --strict"
```

Expected: PASS.

- [ ] **Step 2: Commit the verification checkpoint**

```bash
git commit --allow-empty -m "chore: verify operator tooling plan"
```
