# Совместимый рефакторинг relay pipeline

**Дата**: 2026-04-18
**Статус**: spec approved, ready for plan
**Заменяет**: предыдущую версию `2026-04-11-audit-refactoring-design.md`

## Контекст

Изначальная версия этой спеки описывала капитальный рефакторинг всего пакета и исходила из предположения, что breaking changes допустимы. С тех пор репозиторий изменился:

- часть relay-рефакторинга уже реализована в `django_celery_outbox/relay/`
- отдельными спеками и PR уже закрыты смежные темы: `schema_version`, `celery_outbox_stats`, Django system checks, документационные улучшения
- текущая цель изменилась: нужен один большой, но прагматичный PR поверх `master`, без изменения публичного API, import paths, settings names и миграционной истории

Главная оставшаяся проблема не в package layout целиком, а в том, что `django_celery_outbox/relay/_relay.py` всё ещё держит слишком много обязанностей:

- orchestration batch loop
- broker publish и восстановление контекста
- классификацию ошибок и logging policy
- retry scheduling и bulk updates
- dead-letter move
- signal safety
- batch bookkeeping и часть runtime-policy

Спека должна сузить прошлую амбицию до совместимого внутреннего рефакторинга relay pipeline.

## Цели

1. Уменьшить размер и связность `relay/_relay.py`, оставив `Relay` тонким оркестратором.
2. Разделить независимые обязанности relay на небольшие внутренние коллабораторы.
3. Сохранить текущее внешнее поведение:
   - публичный API `OutboxCelery`
   - `Relay` / `RelayConfig`
   - существующие management commands и CLI flags
   - текущие settings names
   - существующие signals
   - миграции и модельные классы
4. Улучшить тестируемость без DI-framework и без массового patching private methods.
5. Не тащить в PR уже реализованные или плохо окупающиеся архитектурные идеи.

## Не-цели

Следующее в этот рефакторинг не входит:

- package-wide redesign всего `django_celery_outbox`
- split `models.py` в package `models/`
- split `metrics.py` / `statsd.py` в package `metrics/` c `Protocol`-based DI
- split `serialization.py` в package `options/` с `HandlerRegistry` и набором handler-классов
- reset, squash или переписывание миграционной истории
- переименование публичных import paths
- смена сигнатур публичных API и names существующих settings/signals
- отдельный perf-budget / benchmark framework с жёсткими query-count и wall-time SLA
- перевод тестовой инфраструктуры на PostgreSQL-only
- повторное описание тем, уже покрытых отдельными спеками (`schema_version`, operator stats, system checks)

## Scope

### In Scope

- внутренняя декомпозиция `relay/_relay.py`
- выделение 2-3 внутренних модулей внутри `django_celery_outbox/relay/`, если каждый убирает самостоятельную обязанность из `Relay`
- сохранение текущего поведения publish/retry/dead-letter/metrics/signals/schema-version filtering
- уменьшение количества тестов, которые патчат private `_send_task`
- точечное обновление `ARCHITECTURE.md` и связанных doc-описаний под новую внутреннюю структуру

### Out Of Scope

- новые extension points без подтверждённой необходимости
- абстракции "на будущее" ради потенциальных backend-ов
- реорганизация файлов вне hot path relay, если она не обслуживает эту задачу напрямую

### Правило отбора

Новый модуль появляется только если он убирает из `Relay` отдельную ответственность со своим понятным контрактом. Вынесение ради красоты запрещено.

## Целевая внутренняя структура

После рефакторинга пакет `django_celery_outbox/relay/` должен остаться небольшим и понятным:

```text
django_celery_outbox/relay/
├── __init__.py
├── _config.py
├── _message_selector.py
├── _publisher.py
├── _mutations.py
├── _runtime.py
└── _relay.py
```

### Что сохраняется без redesign

- `RelayConfig` остаётся в `_config.py`
- `MessageSelector` остаётся в `_message_selector.py`
- публичный re-export `Relay, RelayConfig` из `relay/__init__.py` сохраняется
- `metrics.py`, `statsd.py`, `_settings.py`, `models.py`, `serialization.py` остаются на своих местах

### `_publisher.py`

Назначение: изолировать broker publish path.

Ответственность модуля:

- десериализовать `msg.options` через существующий `deserialize_options`
- восстановить sentry headers
- восстановить `structlog` context, если он есть
- вызвать raw `Celery.send_task(...)`, обходя override `OutboxCelery.send_task`

Ожидаемый результат:

- `Relay` больше не знает детали восстановления headers/context/options
- тесты publish-пути перестают зависеть от patching `Relay._send_task`
- логика обхода `OutboxCelery.send_task` живёт в одном месте

### `_mutations.py`

Назначение: изолировать post-processing БД после обработки батча.

Ответственность модуля:

- удалить успешно отправленные сообщения
- обновить failed сообщения с backoff и increment retries
- перенести exceeded сообщения в `CeleryOutboxDeadLetter`
- при необходимости сгруппировать retry updates так, чтобы не вводить N+1

Ожидаемый результат:

- `Relay` перестаёт держать в себе bulk DB mutation logic
- проще тестировать retry math и DLQ move отдельно от network send path
- сохраняется текущее поведение по retry/backoff и dead-letter semantics

### `_runtime.py`

Назначение: хранить небольшой runtime-specific код, который не является orchestration и не относится к БД или publish.

Допустимое содержимое:

- `ProcessResult`
- helper классификации exception
- policy helper для traceback logging
- при необходимости небольшой dataclass/структура результата батча

Ограничение:

`_runtime.py` не должен становиться новым "складом утилит". Если helper не относится к runtime-policy relay, он остаётся в своём исходном модуле.

### `_relay.py`

После рефакторинга `Relay` остаётся orchestrator-классом.

Внутри него допустимо оставить:

- lifecycle: `start()`, signal handlers, delayed-delivery setup, shutdown flag
- orchestration одной итерации
- связывание `MessageSelector`, publisher, mutation helper и runtime helpers
- emission batch-level metrics/logging/signals

Внутри него не должно оставаться:

- детальной логики восстановления message options/context
- полного кода DB mutations для failed/published/exceeded
- размазанной по файлу retry/backoff логики

## Целевой pipeline

### 1. Selection phase

Без концептуальных изменений:

- `MessageSelector.run()` выбирает batch
- выбранные rows помечаются `updated_at=Now()`
- schema-version filtering остаётся там, где он уже реализован

### 2. Publish phase

`Relay` итерирует выбранные сообщения, а publish boundary делегируется в `_publisher.py`.

Инварианты:

- raw `Celery.send_task` вызывается так же, как сейчас
- broad exception на broker boundary остаётся допустимым
- исключения по-прежнему классифицируются для логов/метрик
- `structlog` / sentry context propagation не меняется семантически

### 3. Mutation phase

После обработки сообщений `Relay` передаёт результат батча в `_mutations.py`.

Инварианты:

- published сообщения удаляются
- failed сообщения получают increment retries и `retry_after` по текущей backoff-логике
- exceeded сообщения переносятся в DLQ без дополнительного `SELECT` по уже загруженным сообщениям
- no N+1 на failed updates

### 4. Batch-level side effects

Сохраняются в orchestration-слое:

- batch metrics
- queue/dead-letter gauges
- oldest pending age gauge
- batch logging
- liveness touch
- idle/busy decision

## Поведенческие инварианты

Рефакторинг не должен менять следующее:

1. Relay loop не падает насовсем из-за одной неудачной итерации.
2. Ошибки broker/send boundary продолжают логироваться и классифицироваться.
3. `outbox_message_sent`, `outbox_message_failed`, `outbox_message_dead_lettered` сохраняют текущее поведение.
4. Delayed delivery setup остаётся best-effort и не блокирует запуск relay.
5. `schema_version` filtering и десериализация продолжают работать как сейчас.
6. Management command `celery_outbox_relay` сохраняет текущие аргументы и точку входа.
7. `metrics.py` и `statsd.py` не меняют публичную форму ради этого рефакторинга.

## Testing Strategy

Цель тестов в этой спеке не переписать весь suite, а улучшить seams вокруг relay.

### Что меняется

- появляются unit-тесты для `_publisher.py`
- появляются unit/integration-тесты для `_mutations.py`
- существующие relay-тесты смещаются к orchestration-level assertions
- уменьшается зависимость от patching private `_send_task`

### Что остаётся

- существующие e2e/integration сценарии остаются главным защитным контуром от регрессий
- текущий multi-DB baseline сохраняется
- нет отдельного benchmark-suite с жёсткими wall-time утверждениями

### Что проверяем

- publish helper корректно восстанавливает options, headers и context
- mutation helper корректно:
  - удаляет published
  - обновляет failed без N+1-pattern
  - переносит exceeded в dead letter
- `Relay` правильно координирует helpers и сохраняет текущие side effects
- регрессионные кейсы на robustness и exception handling остаются покрыты

## Документация

В рамках PR обновляются только документы, которые реально описывают внутреннее устройство relay:

- `ARCHITECTURE.md`
- при необходимости короткие комментарии/README-фрагменты, если они описывают старую структуру relay

В эту спеку не включаются отдельные doc-only инициативы и не дублируются уже принятые/реализованные design docs.

## Риски и ограничения

### Риск: слишком мелкая декомпозиция

Если выносить каждую мелочь в отдельный файл, `Relay` станет тоньше только формально, а общая сложность вырастет.

Решение:

- ограничить рефакторинг 2-3 новыми внутренними модулями
- держать каждый новый модуль вокруг одной обязанности

### Риск: скрытый breaking change через внутренний rewire

Даже без смены API можно случайно поменять semantics headers, retries, signals или logging.

Решение:

- считать текущие integration/e2e тесты главным поведенческим контрактом
- добавить targeted regression tests только на новые seams

### Риск: perf assertions превращаются в шум

Жёсткие benchmark SLA в тестах будут нестабильными между backend-ами и CI окружениями.

Решение:

- фиксировать только поведенческие/perf-инварианты
- избегать wall-time assertions и хрупких query-budget чисел в acceptance criteria

## Acceptance Criteria

- `relay/_relay.py` заметно уменьшается и превращается в orchestration layer
- publish path вынесен в отдельный внутренний модуль
- batch DB mutations вынесены в отдельный внутренний модуль
- runtime-policy helpers вынесены из `_relay.py`, если это действительно уменьшает сложность
- публичный API, settings, signals, CLI flags и миграционная история не меняются
- существующие tests остаются зелёными
- добавлены targeted tests на новые internal seams
- `ARCHITECTURE.md` больше не описывает relay как монолит, если после рефакторинга это уже не так

## Что было сознательно удалено из прошлой версии

Из предыдущей версии этой спеки намеренно удалены как overengineering или уже неактуальные пункты:

- package-wide `models/`, `metrics/`, `options/` redesign
- `Protocol`-heavy DI для metrics/broker interfaces
- reset `0001_initial.py`
- PostgreSQL-only test infrastructure как обязательное условие
- benchmark framework с жёсткими query/time числами
- повторное включение уже реализованных тем (`schema_version`, operator stats, system checks)

Итоговая форма спеки должна оставаться компактной и служить одному большому совместимому PR, а не новой "идеальной архитектуре" проекта.
