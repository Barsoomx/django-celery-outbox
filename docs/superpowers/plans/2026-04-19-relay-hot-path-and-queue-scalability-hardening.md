# Relay Hot Path And Queue Scalability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix relay outage correctness, make queue-wide gauges sampled instead of recomputed every batch, make stats cheap-by-default, add targeted selector and DLQ indexes, gate any selector fast path on real planner evidence, and chunk DLQ purge deletes.

**Architecture:** Keep the current relay split across `_policy.py`, `_relay.py`, `_message_selector.py`, `_mutations.py`, and `stats.py`. Land correctness fixes first, then sampled queue snapshots, then index-backed query improvements, then the conditional selector fast path, then chunked purge. Require written `EXPLAIN` evidence before shipping indexes or a SQL fast path.

**Tech Stack:** Django ORM/migrations, Celery relay command, PostgreSQL/MySQL `SKIP LOCKED`, pytest, docker compose

---

### Task 1: Fix Breaker Streak And Remaining-Row Partitioning

**Files:**
- Modify: `django_celery_outbox/relay/_policy.py`
- Modify: `django_celery_outbox/relay/_relay.py`
- Modify: `django_celery_outbox/relay/policy_tests.py`
- Modify: `tests/relay_tests.py`

- [ ] **Step 1: Add failing regression tests**

```python
def test_policy_begin_batch_preserves_outage_streak_until_success_or_cooldown() -> None:
    policy = RelayPolicy(broker_outage_cooldown=30.0, shutdown_timeout=30.0)
    policy.begin_batch()
    assert policy.record_outage(now_monotonic=100.0) is False

    policy.begin_batch()

    assert policy.record_outage(now_monotonic=101.0) is True
    assert policy.should_skip_batch(now_monotonic=110.0) is True


@pytest.mark.django_db
def test_processing_breaker_trip_dead_letters_pre_exceeded_remaining_rows(
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(
        app=m_celery_app,
        config=RelayConfig.init(
            batch_size=10,
            idle_time=0,
            backoff_time=120,
            max_retries=3,
            send_timeout=10.0,
            shutdown_timeout=30.0,
            broker_outage_cooldown=30.0,
            max_backoff=3600.0,
        ),
    )
    first = CeleryOutbox.objects.create(task_id='trip-a', task_name='some.task', retries=0, options={})
    exceeded = CeleryOutbox.objects.create(task_id='trip-b', task_name='some.task', retries=3, options={})
    third = CeleryOutbox.objects.create(task_id='trip-c', task_name='some.task', retries=0, options={})

    with patch.object(
        relay._publisher,
        'publish',
        side_effect=[TimeoutError('timed out'), TimeoutError('timed out again')],
    ):
        published, failed, exceeded_rows, deferred_due_to_outage, shutdown_aborted = relay._process_messages([first, exceeded, third])

    assert published == []
    assert failed == []
    assert [row.id for row in exceeded_rows] == [exceeded.id]
    assert deferred_due_to_outage == [first.id, third.id]
    assert shutdown_aborted == []
```

- [ ] **Step 2: Run the focused relay regressions**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/relay/policy_tests.py::test_policy_begin_batch_preserves_outage_streak_until_success_or_cooldown \
  tests/relay_tests.py::test_processing_breaker_trip_dead_letters_pre_exceeded_remaining_rows \
  tests/relay_tests.py::test_pre_exceeded_rows_do_not_reset_outage_streak \
  -v
```

Expected: FAIL because outage streak is still batch-local and breaker-trip handling still defers all remaining rows homogeneously.

- [ ] **Step 3: Implement policy and relay partitioning changes**

```python
def begin_batch(self) -> None:
    return


def should_skip_batch(self, now_monotonic: float) -> bool:
    if self._breaker_open_until is None:
        return False
    if now_monotonic >= self._breaker_open_until:
        self._breaker_open_until = None
        self._outage_streak = 0
        return False
    return True
```

```python
def _partition_remaining_messages(
    self,
    messages: list[CeleryOutbox],
) -> tuple[list[CeleryOutbox], list[int]]:
    exceeded = [msg for msg in messages if msg.retries >= self._config.max_retries]
    deferred = [msg.id for msg in messages if msg.retries < self._config.max_retries]
    return exceeded, deferred
```

```python
if breaker_opened:
    remaining_exceeded, remaining_deferred = self._partition_remaining_messages(messages[index + 1 :])
    exceeded.extend(remaining_exceeded)
    deferred_due_to_outage.extend(remaining_deferred)
    break
```

- [ ] **Step 4: Re-run the focused relay regressions**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/relay/policy_tests.py::test_policy_begin_batch_preserves_outage_streak_until_success_or_cooldown \
  tests/relay_tests.py::test_processing_breaker_trip_dead_letters_pre_exceeded_remaining_rows \
  tests/relay_tests.py::test_pre_exceeded_rows_do_not_reset_outage_streak \
  -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/relay/_policy.py django_celery_outbox/relay/_relay.py django_celery_outbox/relay/policy_tests.py tests/relay_tests.py
git commit -m "fix: harden relay breaker semantics"
```

### Task 2: Add Sampled Queue Snapshot Semantics And Cheap-By-Default Stats

**Files:**
- Modify: `django_celery_outbox/relay/_relay.py`
- Modify: `django_celery_outbox/stats.py`
- Modify: `django_celery_outbox/stats_tests.py`
- Modify: `django_celery_outbox/management/commands/celery_outbox_stats.py`
- Modify: `django_celery_outbox/management/commands/celery_outbox_stats_tests.py`
- Add: `docs/superpowers/plans/notes/2026-04-19-relay-sampled-metrics-handoff.md`

- [ ] **Step 1: Add failing stats and relay snapshot tests**

```python
@pytest.mark.django_db
def test_get_queue_stats_top_n_zero_does_not_run_group_by() -> None:
    CeleryOutboxFactory.create(task_name='app.tasks.task_a', retries=10)

    with CaptureQueriesContext(connection) as ctx:
        result = get_queue_stats(top_n=0)

    assert result.top_failing == []
    assert not any('GROUP BY' in query['sql'].upper() for query in ctx.captured_queries)


@pytest.mark.django_db
def test_relay_uses_cached_queue_snapshot_between_refreshes(
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(app=m_celery_app, config=RelayConfig.init(batch_size=10, idle_time=0, max_retries=3))

    with patch('django_celery_outbox.relay._relay.time.monotonic', side_effect=[0.0, 0.0, 0.1, 0.1, 0.2, 0.2]):
        with patch.object(relay, '_touch_liveness'):
            with patch.object(relay._selector, 'run', return_value=[]):
                with patch('django_celery_outbox.relay._relay.get_queue_stats', return_value=QueueStats(queue_depth=0, dlq_count=0, oldest_pending_seconds=None, top_failing=[]), create=True) as m_stats:
                    relay._processing()
                    relay._processing()

    assert m_stats.call_count == 1


@pytest.mark.django_db
def test_stats_command_defaults_top_to_zero() -> None:
    CeleryOutboxFactory.create(task_name='app.tasks.task_a', retries=10)

    out = StringIO()
    call_command('celery_outbox_stats', format='json', stdout=out)
    parsed = json.loads(out.getvalue())

    assert parsed['top_failing'] == []
```

- [ ] **Step 2: Run the focused stats and relay tests**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/stats_tests.py::test_get_queue_stats_top_n_zero_does_not_run_group_by \
  django_celery_outbox/management/commands/celery_outbox_stats_tests.py::test_stats_command_defaults_top_to_zero \
  tests/relay_tests.py::test_relay_uses_cached_queue_snapshot_between_refreshes \
  -v
```

Expected: FAIL because queue-wide work is still recomputed every batch and the stats command still defaults to `--top=10`.

- [ ] **Step 3: Implement the sampler and command default change**

```python
@dataclass
class QueueStats:
    queue_depth: int
    dlq_count: int
    oldest_pending_seconds: float | None
    top_failing: list[TopFailingTask]


class QueueSnapshotSampler:
    def __init__(self, *, refresh_interval_seconds: float = 5.0) -> None:
        self._refresh_interval_seconds = refresh_interval_seconds
        self._last_sampled_at: float | None = None
        self._last_stats = QueueStats(queue_depth=0, dlq_count=0, oldest_pending_seconds=None, top_failing=[])

    def get(self, *, now_monotonic: float) -> QueueStats:
        if self._last_sampled_at is None or now_monotonic - self._last_sampled_at >= self._refresh_interval_seconds:
            self._last_stats = get_queue_stats(top_n=0)
            self._last_sampled_at = now_monotonic
        return self._last_stats
```

Create `docs/superpowers/plans/notes/` before adding `2026-04-19-relay-sampled-metrics-handoff.md`.

```python
snapshot = self._queue_snapshot_sampler.get(now_monotonic=time.monotonic())
metrics.gauge('queue.depth', snapshot.queue_depth)
metrics.gauge('dead_letter.count', snapshot.dlq_count)
metrics.gauge('oldest_pending_age_seconds', snapshot.oldest_pending_seconds or 0)
```

```python
parser.add_argument('--top', type=int, default=0)
```

```markdown
# Sampled queue-gauge handoff

- `queue.depth`, `dead_letter.count`, and `oldest_pending_age_seconds` are sampled queue-wide gauges, not exact per-batch snapshots.
- `celery_outbox_stats queue_depth` now matches relay live-backlog semantics.
- `celery_outbox_stats --top` defaults to `0`; `GROUP BY task_name` is now opt-in.
```

- [ ] **Step 4: Re-run the focused tests and verify the handoff note**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/stats_tests.py::test_get_queue_stats_top_n_zero_does_not_run_group_by \
  django_celery_outbox/management/commands/celery_outbox_stats_tests.py::test_stats_command_defaults_top_to_zero \
  tests/relay_tests.py::test_relay_uses_cached_queue_snapshot_between_refreshes \
  -v
docker compose run --rm app bash -lc "rg -n 'sampled queue-gauge handoff|GROUP BY task_name|live-backlog semantics' docs/superpowers/plans/notes/2026-04-19-relay-sampled-metrics-handoff.md"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/relay/_relay.py django_celery_outbox/stats.py django_celery_outbox/stats_tests.py django_celery_outbox/management/commands/celery_outbox_stats.py django_celery_outbox/management/commands/celery_outbox_stats_tests.py docs/superpowers/plans/notes/2026-04-19-relay-sampled-metrics-handoff.md
git commit -m "feat: sample relay queue gauges and cheapen stats defaults"
```

### Task 3: Add Targeted Indexes And Capture `EXPLAIN` Evidence

**Files:**
- Modify: `django_celery_outbox/models.py`
- Create: `django_celery_outbox/migrations/0004_queue_selector_indexes.py`
- Modify: `django_celery_outbox/models_tests.py`
- Add: `docs/superpowers/plans/notes/2026-04-19-relay-index-explain.txt`

- [ ] **Step 1: Add migration and model tests for the new indexes**

```python
def test_outbox_retry_and_stale_indexes_declared() -> None:
    index_names = {index.name for index in CeleryOutbox._meta.indexes}
    assert 'celery_outbox_pending_idx' in index_names
    assert 'celery_outbox_retry_idx' in index_names
    assert 'celery_outbox_stale_idx' in index_names


def test_dead_letter_retention_indexes_declared() -> None:
    index_names = {index.name for index in CeleryOutboxDeadLetter._meta.indexes}
    assert 'celery_outbox_dlq_dead_at_idx' in index_names
    assert 'celery_outbox_dlq_created_at_idx' in index_names
```

- [ ] **Step 2: Run the focused model tests**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/models_tests.py::test_outbox_retry_and_stale_indexes_declared \
  django_celery_outbox/models_tests.py::test_dead_letter_retention_indexes_declared \
  -v
```

Expected: FAIL because the new indexes do not exist.

- [ ] **Step 3: Implement indexes and collect PostgreSQL and MySQL `EXPLAIN` evidence**

```python
indexes = [
    models.Index(
        fields=['id'],
        condition=models.Q(updated_at__isnull=True),
        name='celery_outbox_pending_idx',
    ),
    models.Index(fields=['retry_after', 'id'], name='celery_outbox_retry_idx'),
    models.Index(
        fields=['updated_at', 'id'],
        condition=models.Q(retry_after__isnull=True),
        name='celery_outbox_stale_idx',
    ),
]
```

```python
class CeleryOutboxDeadLetter(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=['dead_at'], name='celery_outbox_dlq_dead_at_idx'),
            models.Index(fields=['created_at'], name='celery_outbox_dlq_created_at_idx'),
        ]
```

Run:

```bash
docker compose run --rm -e DB_ENGINE=postgresql -e DB_HOST=postgres app bash -lc "mkdir -p docs/superpowers/plans/notes && DJANGO_SETTINGS_MODULE=tests.settings python -m django migrate --noinput && DJANGO_SETTINGS_MODULE=tests.settings python - <<'PY'
import django
from datetime import timedelta
from django.db import transaction
from django.utils import timezone

django.setup()

from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter
from django_celery_outbox.relay._message_selector import get_pending_filter

print('## postgres:selector_pending')
with transaction.atomic():
    selector_qs = (
        CeleryOutbox.objects.select_for_update(skip_locked=True)
        .filter(get_pending_filter())
        .order_by('id')[:100]
    )
    print(selector_qs.explain(analyze=True, buffers=True))

print('## postgres:dlq_dead')
dlq_dead_qs = CeleryOutboxDeadLetter.objects.filter(dead_at__lt=timezone.now() - timedelta(days=30)).order_by('id')[:1000]
print(dlq_dead_qs.explain(analyze=True, buffers=True))

print('## postgres:dlq_created')
dlq_created_qs = CeleryOutboxDeadLetter.objects.filter(created_at__lt=timezone.now() - timedelta(days=90)).order_by('id')[:1000]
print(dlq_created_qs.explain(analyze=True, buffers=True))
PY" > docs/superpowers/plans/notes/2026-04-19-relay-index-explain.txt

docker compose run --rm -e DB_ENGINE=mysql -e DB_HOST=mysql app bash -lc "DJANGO_SETTINGS_MODULE=tests.settings python -m django migrate --noinput && DJANGO_SETTINGS_MODULE=tests.settings python - <<'PY'
import django
from datetime import timedelta
from django.db import transaction
from django.utils import timezone

django.setup()

from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter
from django_celery_outbox.relay._message_selector import get_pending_filter

print('## mysql:selector_pending')
with transaction.atomic():
    selector_qs = (
        CeleryOutbox.objects.select_for_update(skip_locked=True)
        .filter(get_pending_filter())
        .order_by('id')[:100]
    )
    print(selector_qs.explain(format='JSON'))

print('## mysql:dlq_dead')
dlq_dead_qs = CeleryOutboxDeadLetter.objects.filter(dead_at__lt=timezone.now() - timedelta(days=30)).order_by('id')[:1000]
print(dlq_dead_qs.explain(format='JSON'))

print('## mysql:dlq_created')
dlq_created_qs = CeleryOutboxDeadLetter.objects.filter(created_at__lt=timezone.now() - timedelta(days=90)).order_by('id')[:1000]
print(dlq_created_qs.explain(format='JSON'))
PY" >> docs/superpowers/plans/notes/2026-04-19-relay-index-explain.txt

```

After reviewing the two selector `EXPLAIN` blocks, append two explicit decision lines to the note file using one of these exact forms:

- `decision: postgres selector_pending acceptable`
- `decision: postgres selector_pending needs_postgres_fast_path`
- `decision: mysql selector_pending acceptable`
- `decision: mysql selector_pending mysql_orm_path_retained`

- [ ] **Step 4: Run tests and verify the `EXPLAIN` note file**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/models_tests.py::test_outbox_retry_and_stale_indexes_declared \
  django_celery_outbox/models_tests.py::test_dead_letter_retention_indexes_declared \
  -v
docker compose run --rm app bash -lc "rg -n '^## (postgres|mysql):(selector_pending|dlq_dead|dlq_created)$|^decision: (postgres|mysql) selector_pending ' docs/superpowers/plans/notes/2026-04-19-relay-index-explain.txt"
```

Expected: PASS, with both PostgreSQL and MySQL `EXPLAIN` sections recorded for the actual selector queryset plus explicit selector decisions before deciding on a fast path.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/models.py django_celery_outbox/migrations/0004_queue_selector_indexes.py django_celery_outbox/models_tests.py docs/superpowers/plans/notes/2026-04-19-relay-index-explain.txt
git commit -m "feat: add selector and retention indexes"
```

### Task 4: Add The Selector Fast Path Only If `EXPLAIN` Still Shows A Real Selector Problem

**Files:**
- Modify: `django_celery_outbox/relay/_message_selector.py`
- Modify: `tests/relay_tests.py`
- Modify: `docs/superpowers/plans/notes/2026-04-19-relay-index-explain.txt`

Precondition:

- Execute this task only if Task 3's note file contains `decision: postgres selector_pending needs_postgres_fast_path`.
- If Task 3 records `decision: postgres selector_pending acceptable`, skip this task entirely, even if MySQL remains on the ORM path. Record `selector fast path skipped: postgres indexed plan acceptable` in the note file when skipping.

- [ ] **Step 1: Add failing selector parity tests**

```python
@pytest.mark.django_db
def test_selector_fast_path_returns_same_ids_as_orm_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    selected = [
        CeleryOutbox.objects.create(task_id='fast-path-1', task_name='app.task', updated_at=None),
        CeleryOutbox.objects.create(task_id='fast-path-2', task_name='app.task', updated_at=None),
    ]
    selector = MessageSelector(batch_size=10)
    postgres_connection = SimpleNamespace(vendor='postgresql')

    with patch.object(selector, '_select_and_mark_with_postgres_cte', return_value=selected, create=True) as m_fast:
        with patch('django_celery_outbox.relay._message_selector.connection', postgres_connection, create=True):
            result = selector.run()

    m_fast.assert_called_once_with()
    assert [row.id for row in result] == [selected[0].id, selected[1].id]


@pytest.mark.django_db
def test_selector_fast_path_marks_selected_rows_inflight(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    message = CeleryOutbox.objects.create(task_id='fast-path-mark-1', task_name='app.task', updated_at=None)
    selector = MessageSelector(batch_size=10)
    postgres_connection = SimpleNamespace(vendor='postgresql')

    def fake_postgres_cte() -> list[CeleryOutbox]:
        CeleryOutbox.objects.filter(pk=message.pk).update(updated_at=django_timezone.now())
        message.refresh_from_db()
        return [message]

    with patch.object(selector, '_select_and_mark_with_postgres_cte', side_effect=fake_postgres_cte, create=True) as m_fast:
        with patch.object(selector, '_mark_in_flight') as m_mark:
            with patch('django_celery_outbox.relay._message_selector.connection', postgres_connection, create=True):
                result = selector.run()

    m_fast.assert_called_once_with()
    m_mark.assert_not_called()
    message.refresh_from_db()
    assert [row.id for row in result] == [message.id]
    assert message.updated_at is not None
```

- [ ] **Step 2: Run the selector parity test**

Run:

```bash
docker compose run --rm app python -m pytest \
  tests/relay_tests.py::test_selector_fast_path_returns_same_ids_as_orm_path \
  tests/relay_tests.py::test_selector_fast_path_marks_selected_rows_inflight \
  -v
```

Expected: FAIL because no fast path exists.

- [ ] **Step 3: Implement the backend-guarded fast path**

```python
def run(self) -> list[CeleryOutbox]:
    if connection.vendor == 'postgresql':
        return self._select_and_mark_with_postgres_cte()

    messages = self._select()
    self._mark_in_flight(messages)
    return messages
```

```python
def _select_and_mark_with_postgres_cte(self) -> list[CeleryOutbox]:
    with connection.cursor() as cursor:
        cursor.execute(
            '''
            WITH claimed AS (
                SELECT id
                FROM celery_outbox
                WHERE (
                    updated_at IS NULL
                    OR retry_after <= NOW()
                    OR (retry_after IS NULL AND updated_at <= NOW() - INTERVAL '5 minutes')
                )
                AND schema_version BETWEEN %s AND %s
                ORDER BY id
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE celery_outbox
            SET updated_at = NOW()
            WHERE id IN (SELECT id FROM claimed)
            RETURNING *
            ''',
            [MIN_SUPPORTED_VERSION, CURRENT_SCHEMA_VERSION, self._batch_size],
        )
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
    return [
        CeleryOutbox(**dict(zip(columns, row, strict=True)))
        for row in rows
    ]
```

- [ ] **Step 4: Re-run selector parity tests and append the decision to the note file**

Run:

```bash
docker compose run --rm app python -m pytest \
  tests/relay_tests.py::test_selector_fast_path_returns_same_ids_as_orm_path \
  tests/relay_tests.py::test_selector_fast_path_marks_selected_rows_inflight \
  -v
docker compose run --rm app bash -lc "printf '\nselector fast path implemented: postgres CTE claim+mark\n' >> docs/superpowers/plans/notes/2026-04-19-relay-index-explain.txt"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/relay/_message_selector.py tests/relay_tests.py docs/superpowers/plans/notes/2026-04-19-relay-index-explain.txt
git commit -m "feat: add relay selector fast path"
```

### Task 5: Chunk Dead-Letter Purge Deletes

**Files:**
- Modify: `django_celery_outbox/purge.py`
- Modify: `django_celery_outbox/purge_tests.py`

- [ ] **Step 1: Add failing chunked-purge tests**

```python
@pytest.mark.django_db
def test_purge_dead_letter_deletes_in_pk_chunks() -> None:
    now = timezone.now()
    old_time = now - timedelta(days=31)
    with patch('django.utils.timezone.now', return_value=now):
        records = CeleryOutboxDeadLetterFactory.create_batch(3, task_name='myapp.task')
    CeleryOutboxDeadLetter.objects.filter(pk__in=[row.pk for row in records]).update(dead_at=old_time)

    with patch('django_celery_outbox.purge._DELETE_CHUNK_SIZE', 2):
        with CaptureQueriesContext(connection) as ctx:
            result = purge_dead_letter(older_than_dead=timedelta(days=30), dry_run=False)

    delete_queries = [query['sql'] for query in ctx.captured_queries if query['sql'].lstrip().upper().startswith('DELETE')]
    assert result.deleted_count == 3
    assert len(delete_queries) == 2
    assert CeleryOutboxDeadLetter.objects.count() == 0


@pytest.mark.django_db
def test_purge_dead_letter_dry_run_unchanged() -> None:
    now = timezone.now()
    old_time = now - timedelta(days=31)
    with patch('django.utils.timezone.now', return_value=now):
        record = CeleryOutboxDeadLetterFactory.create(task_name='myapp.task')
    CeleryOutboxDeadLetter.objects.filter(pk=record.pk).update(dead_at=old_time)

    with patch('django_celery_outbox.purge._DELETE_CHUNK_SIZE', 2):
        result = purge_dead_letter(older_than_dead=timedelta(days=30), dry_run=True)

    assert result.deleted_count == 1
    assert CeleryOutboxDeadLetter.objects.filter(pk=record.pk).exists()
```

- [ ] **Step 2: Run the purge tests**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/purge_tests.py::test_purge_dead_letter_deletes_in_pk_chunks \
  django_celery_outbox/purge_tests.py::test_purge_dead_letter_dry_run_unchanged \
  -v
```

Expected: FAIL because purge still uses one large `queryset.delete()`.

- [ ] **Step 3: Implement ordered PK chunk deletion**

```python
_DELETE_CHUNK_SIZE = 1000


def _delete_in_chunks(queryset: QuerySet[CeleryOutboxDeadLetter]) -> None:
    while ids := list(queryset.order_by('pk').values_list('pk', flat=True)[:_DELETE_CHUNK_SIZE]):
        CeleryOutboxDeadLetter.objects.filter(pk__in=ids).delete()
```

```python
if not dry_run and deleted_count > 0:
    _delete_in_chunks(queryset)
```

- [ ] **Step 4: Re-run purge tests**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/purge_tests.py::test_purge_dead_letter_deletes_in_pk_chunks \
  django_celery_outbox/purge_tests.py::test_purge_dead_letter_dry_run_unchanged \
  -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/purge.py django_celery_outbox/purge_tests.py django_celery_outbox/tasks_tests.py
git commit -m "feat: chunk dead letter purge deletes"
```

### Task 6: Final Relay Verification Sweep

**Files:**
- Verify only

- [ ] **Step 1: Run the relay-focused verification suite**

Run:

```bash
docker compose run --rm app python -m pytest \
  django_celery_outbox/relay/policy_tests.py \
  django_celery_outbox/stats_tests.py \
  django_celery_outbox/models_tests.py \
  django_celery_outbox/purge_tests.py \
  django_celery_outbox/management/commands/celery_outbox_stats_tests.py \
  tests/relay_tests.py \
  -v
docker compose run --rm app bash -lc "rg -n '^## (postgres|mysql):(selector_pending|dlq_dead|dlq_created)$|^decision: (postgres|mysql) selector_pending ' docs/superpowers/plans/notes/2026-04-19-relay-index-explain.txt"
```

Expected: PASS.

- [ ] **Step 2: Commit the verification checkpoint**

```bash
git commit --allow-empty -m "chore: verify relay scalability plan"
```
