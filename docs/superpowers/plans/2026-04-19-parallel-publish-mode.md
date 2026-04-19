# Parallel Publish Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional bounded parallel publish mode that preserves relay breaker, shutdown, signal, and DB-mutation invariants.

**Architecture:** Build on top of the serial relay from the hot-path plan. Add a `publish_concurrency` knob to the relay config and management command, then implement a sliding-window executor inside the relay orchestration path. Worker threads publish only materialized message payloads; the main thread owns all classification, signals, metrics, and DB mutation.

**Tech Stack:** Python `ThreadPoolExecutor`, Django, Celery/Kombu, pytest, docker compose

---

### Task 1: Add Config Surface And Sliding-Window Red Tests

**Files:**
- Modify: `django_celery_outbox/relay/_config.py`
- Modify: `django_celery_outbox/management/commands/celery_outbox_relay.py`
- Modify: `django_celery_outbox/relay/_relay.py`
- Modify: `tests/relay_tests.py`

- [ ] **Step 1: Write failing config and orchestration tests**

```python
def test_relay_config_accepts_publish_concurrency() -> None:
    config = RelayConfig.init(max_retries=3, publish_concurrency=4)
    assert config.publish_concurrency == 4


@pytest.mark.django_db
def test_parallel_mode_one_is_identical_to_serial_path(
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(app=m_celery_app, config=RelayConfig.init(idle_time=0, max_retries=3, publish_concurrency=1))
    msg = CeleryOutbox.objects.create(task_id='parallel-one-1', task_name='demo.task', options={})

    with patch.object(relay, '_process_messages_serial', return_value=([msg.id], [], [], [], [])) as m_serial:
        relay._process_messages([msg])

    m_serial.assert_called_once_with([msg])


@pytest.mark.django_db
def test_parallel_mode_never_submits_more_than_publish_concurrency(
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(app=m_celery_app, config=RelayConfig.init(idle_time=0, max_retries=3, publish_concurrency=2))
    messages = [
        CeleryOutbox.objects.create(task_id=f'parallel-window-{i}', task_name='demo.task', options={})
        for i in range(4)
    ]
    submitted: list[int] = []

    with patch.object(
        relay._publisher,
        'prepare_publish_call',
        side_effect=lambda msg: submitted.append(msg.id) or msg,
        create=True,
    ):
        with patch.object(relay._publisher, 'publish_prepared', return_value=None, create=True):
            with patch('django_celery_outbox.relay._relay.as_completed', side_effect=lambda futures: futures):
                relay._process_messages(messages)

    assert submitted[:2] == [messages[0].id, messages[1].id]
    assert len(submitted) == 4
```

- [ ] **Step 2: Run the focused tests**

Run:

```bash
docker compose run --rm app python -m pytest django_celery_outbox/relay tests/relay_tests.py -k "publish_concurrency or serial_path or sliding_window" -v
```

Expected: FAIL because the new knob and scheduling behavior do not exist.

- [ ] **Step 3: Implement config plumbing and the serial helper split**

```python
publish_concurrency: int = 1
parser.add_argument("--publish-concurrency", type=int, default=1)
```

```python
def _process_messages(self, messages: list[CeleryOutbox]) -> tuple[list[int], list[tuple[int, int]], list[CeleryOutbox], list[int], list[CeleryOutbox]]:
    if self._config.publish_concurrency == 1:
        return self._process_messages_serial(messages)
    return self._process_messages_parallel(messages)
```

Rename the current serial `_process_messages()` implementation to `_process_messages_serial()` without changing its body in this task.

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
docker compose run --rm app python -m pytest django_celery_outbox/relay tests/relay_tests.py -k "publish_concurrency or serial_path or sliding_window" -v
```

Expected: config tests PASS; orchestration tests still fail until executor logic lands.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/relay/_config.py django_celery_outbox/management/commands/celery_outbox_relay.py django_celery_outbox/relay tests/relay_tests.py
git commit -m "feat: add relay publish concurrency config"
```

### Task 2: Implement Sliding-Window Executor Semantics

**Files:**
- Modify: `django_celery_outbox/relay/_publisher.py`
- Modify: `django_celery_outbox/relay/publisher_tests.py`
- Modify: `django_celery_outbox/relay/_relay.py`
- Modify: `tests/relay_tests.py`

- [ ] **Step 1: Add failing shutdown/breaker concurrency tests**

```python
@pytest.mark.django_db
def test_parallel_mode_stops_submitting_after_shutdown_deadline(
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(app=m_celery_app, config=RelayConfig.init(idle_time=0, max_retries=3, publish_concurrency=2, shutdown_timeout=30.0))
    messages = [
        CeleryOutbox.objects.create(task_id='shutdown-parallel-1', task_name='demo.task', options={}),
        CeleryOutbox.objects.create(task_id='shutdown-parallel-2', task_name='demo.task', options={}),
    ]
    relay._policy.begin_shutdown(now_monotonic=0.0)

    with patch.object(relay._publisher, 'prepare_publish_call', side_effect=lambda msg: msg, create=True):
        with patch.object(relay._publisher, 'publish_prepared', return_value=None, create=True):
            with patch('django_celery_outbox.relay._relay.time.monotonic', side_effect=[0.0, 0.0, 31.0, 31.0]):
                published, failed, exceeded, deferred_due_to_outage, shutdown_aborted = relay._process_messages(messages)

    assert published == [messages[0].id]
    assert failed == []
    assert exceeded == []
    assert deferred_due_to_outage == []
    assert [row.id for row in shutdown_aborted] == [messages[1].id]


@pytest.mark.django_db
def test_parallel_mode_stops_submitting_after_breaker_open(
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(app=m_celery_app, config=RelayConfig.init(idle_time=0, max_retries=5, publish_concurrency=2, broker_outage_cooldown=30.0))
    messages = [
        CeleryOutbox.objects.create(task_id='breaker-parallel-1', task_name='demo.task', options={}),
        CeleryOutbox.objects.create(task_id='breaker-parallel-2', task_name='demo.task', options={}),
        CeleryOutbox.objects.create(task_id='breaker-parallel-3', task_name='demo.task', options={}),
    ]

    with patch.object(relay._publisher, 'prepare_publish_call', side_effect=lambda msg: msg, create=True):
        with patch.object(relay._publisher, 'publish_prepared', side_effect=[TimeoutError('outage-1'), TimeoutError('outage-2')], create=True):
            published, failed, exceeded, deferred_due_to_outage, shutdown_aborted = relay._process_messages(messages)

    assert published == []
    assert failed == []
    assert exceeded == []
    assert deferred_due_to_outage == [messages[0].id, messages[1].id, messages[2].id]
    assert shutdown_aborted == []


@pytest.mark.django_db
def test_inflight_futures_complete_and_are_classified_normally(
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(app=m_celery_app, config=RelayConfig.init(idle_time=0, max_retries=3, publish_concurrency=2))
    first = CeleryOutbox.objects.create(task_id='inflight-1', task_name='demo.task', options={})
    second = CeleryOutbox.objects.create(task_id='inflight-2', task_name='demo.task', options={}, retries=2)

    with patch.object(relay._publisher, 'prepare_publish_call', side_effect=lambda msg: msg, create=True):
        with patch.object(relay._publisher, 'publish_prepared', side_effect=[None, RuntimeError('boom')], create=True):
            published, failed, exceeded, deferred_due_to_outage, shutdown_aborted = relay._process_messages([first, second])

    assert published == [first.id]
    assert failed == []
    assert [row.id for row in exceeded] == [second.id]
    assert deferred_due_to_outage == []
    assert shutdown_aborted == []
```

- [ ] **Step 2: Run the focused concurrency tests**

Run:

```bash
docker compose run --rm app python -m pytest tests/relay_tests.py -k "parallel_mode or inflight_futures" -v
```

Expected: FAIL because the relay is still serial.

- [ ] **Step 3: Implement the bounded executor**

```python
@dataclass(frozen=True)
class PreparedPublishCall:
    task_name: str
    task_id: str
    args: list[Any]
    kwargs: dict[str, Any]
    options: dict[str, Any]
    headers: dict[str, Any]
    structlog_context: dict[str, Any]


def _classify_parallel_publish_exception(
    self,
    msg: CeleryOutbox,
    exc: Exception,
    failed: list[tuple[int, int]],
    exceeded: list[CeleryOutbox],
    deferred_due_to_outage: list[int],
) -> bool:
    if is_broker_outage(exc):
        deferred_due_to_outage.append(msg.id)
        return self._policy.record_outage(time.monotonic())

    self._policy.record_success()
    if msg.retries + 1 >= self._config.max_retries:
        exceeded.append(msg)
    else:
        failed.append((msg.id, msg.retries))
        self._send_signal_safe(outbox_message_failed, msg.task_id, msg.task_name, retries=msg.retries)
    return False


class RelayPublisher:
    def _apply_sentry_headers(self, headers: dict[str, Any], msg: CeleryOutbox) -> dict[str, Any]:
        merged = dict(headers)
        if msg.sentry_trace_id:
            merged['sentry-trace'] = msg.sentry_trace_id
        if msg.sentry_baggage:
            merged['baggage'] = msg.sentry_baggage
        return merged

    def prepare_publish_call(self, msg: CeleryOutbox) -> PreparedPublishCall:
        options = deserialize_options(msg.options, self._app, msg.schema_version)
        headers = dict(options.pop('headers', {}) or {})
        headers = self._apply_sentry_headers(headers, msg)
        eta = options.pop('eta', None)
        if eta is not None:
            options['eta'] = eta
        return PreparedPublishCall(
            task_name=msg.task_name,
            task_id=msg.task_id,
            args=msg.args,
            kwargs=msg.kwargs,
            options=options,
            headers=headers,
            structlog_context=parse_structlog_context(msg.structlog_context),
        )

    def publish_prepared(self, call: PreparedPublishCall) -> None:
        with structlog.contextvars.bound_contextvars(**call.structlog_context):
            Celery.send_task(
                self._app,
                name=call.task_name,
                args=call.args,
                kwargs=call.kwargs,
                task_id=call.task_id,
                headers=call.headers,
                timeout=self._send_timeout,
                **call.options,
            )


remaining = deque(messages)
pending: dict[Future[None], CeleryOutbox] = {}

with ThreadPoolExecutor(max_workers=self._config.publish_concurrency) as pool:
    while pending or remaining:
        while remaining and len(pending) < self._config.publish_concurrency and not stop_submitting:
            msg = remaining.popleft()
            pending[pool.submit(self._publisher.publish_prepared, self._publisher.prepare_publish_call(msg))] = msg

        for future in as_completed(list(pending)):
            msg = pending.pop(future)
            exc = future.exception()
            if exc is None:
                published.append(msg.id)
                self._policy.record_success()
            else:
                stop_submitting = self._classify_parallel_publish_exception(msg, exc, failed, exceeded, deferred_due_to_outage)
            break
```

- [ ] **Step 4: Re-run the focused concurrency tests**

Run:

```bash
docker compose run --rm app python -m pytest django_celery_outbox/relay/publisher_tests.py tests/relay_tests.py -k "parallel_mode or inflight_futures or publish_prepared" -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_celery_outbox/relay/_publisher.py django_celery_outbox/relay/publisher_tests.py django_celery_outbox/relay/_relay.py tests/relay_tests.py
git commit -m "feat: add bounded parallel relay publish mode"
```

### Task 3: Protect Main-Thread Mutation And Real-Broker Verification

**Files:**
- Modify: `tests/relay_tests.py`
- Modify: `.github/workflows/tests.yml`
- Modify: `docker-compose.yml`
- Add: `tests/parallel_broker_smoke_tests.py`
- Modify: `docs/relay/tuning.md`
- Modify: `docs/relay/overview.md`

- [ ] **Step 1: Add failing main-thread-only mutation test**

```python
@pytest.mark.django_db
def test_parallel_mode_keeps_db_mutation_and_signals_on_main_thread(
    m_celery_app: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_relay_for_sqlite(monkeypatch)
    relay = Relay(app=m_celery_app, config=RelayConfig.init(idle_time=0, max_retries=3, publish_concurrency=2))
    main_thread_id = threading.get_ident()
    signal_threads: list[int] = []
    mutation_threads: list[int] = []

    CeleryOutbox.objects.create(task_id='thread-1', task_name='demo.task', options={})

    def sent_handler(sender: type, **kwargs: object) -> None:
        signal_threads.append(threading.get_ident())

    outbox_message_sent.connect(sent_handler)
    try:
        with patch.object(relay._mutations, 'delete_published', side_effect=lambda ids: mutation_threads.append(threading.get_ident())):
            relay._processing()
    finally:
        outbox_message_sent.disconnect(sent_handler)

    assert signal_threads == [main_thread_id]
    assert mutation_threads == [main_thread_id]
```

- [ ] **Step 2: Run the focused tests**

Run:

```bash
docker compose run --rm app python -m pytest tests/relay_tests.py -k "main_thread" -v
```

Expected: FAIL until thread ownership is explicit in the implementation.

- [ ] **Step 3: Add docs and a concrete broker-backed smoke lane**

```markdown
`--publish-concurrency` is advanced tuning. Start with `1` and increase only after broker-backed verification on the supported broker lane.
```

```yaml
services:
  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    healthcheck:
      test: ['CMD', 'rabbitmq-diagnostics', 'check_running']
      interval: 5s
      timeout: 5s
      retries: 10
```

```yaml
jobs:
  parallel_broker_smoke:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432
      rabbitmq:
        image: rabbitmq:3.13-management-alpine
        options: >-
          --health-cmd "rabbitmq-diagnostics check_running"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 10
        ports:
          - 5672:5672
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - run: pip install -e '.[test]'
      - env:
          CELERY_BROKER_URL: amqp://guest:guest@127.0.0.1:5672//
          DB_ENGINE: postgresql
          DB_HOST: 127.0.0.1
          DB_NAME: test_db
          DB_USER: test
          DB_PASSWORD: test
          DB_PORT: 5432
        run: pytest tests/parallel_broker_smoke_tests.py -v
```

```python
@pytest.mark.django_db(transaction=True)
def test_parallel_publish_smoke_to_live_rabbitmq() -> None:
    app = OutboxCelery('parallel-smoke')
    app.conf.broker_url = os.environ['CELERY_BROKER_URL']
    app.conf.task_default_queue = 'parallel-smoke'

    app.send_task('smoke.task', task_id='parallel-smoke-1')
    relay = Relay(app=app, config=RelayConfig.init(batch_size=1, idle_time=0, max_retries=1, publish_concurrency=2))
    relay._processing()

    with Connection(os.environ['CELERY_BROKER_URL']) as connection:
        queue = connection.SimpleQueue('parallel-smoke')
        message = queue.get(timeout=10)
        try:
            assert message.payload['headers']['id'] == 'parallel-smoke-1'
        finally:
            message.ack()
            queue.close()
```

- [ ] **Step 4: Re-run tests and one bounded broker-backed smoke**

Run:

```bash
docker compose run --rm app python -m pytest tests/relay_tests.py -k "main_thread or parallel_mode" -v
docker compose up -d postgres rabbitmq --wait
docker compose run --rm -e CELERY_BROKER_URL=amqp://guest:guest@rabbitmq:5672// app python -m pytest tests/parallel_broker_smoke_tests.py -v
docker compose down -v
```

Expected: PASS for both unit tests and the concrete broker-backed smoke.

- [ ] **Step 5: Commit**

```bash
git add tests/relay_tests.py tests/parallel_broker_smoke_tests.py django_celery_outbox/relay/_publisher.py django_celery_outbox/relay/publisher_tests.py .github/workflows/tests.yml docker-compose.yml docs/relay/tuning.md docs/relay/overview.md
git commit -m "docs: document and verify parallel relay publish mode"
```
