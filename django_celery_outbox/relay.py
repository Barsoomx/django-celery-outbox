import json
import random
import signal
import time
from datetime import timedelta
from pathlib import Path
from types import FrameType

import sentry_sdk
import structlog
from celery import Celery
from django.db import close_old_connections, transaction
from django.db.models import F, Q
from django.db.models.functions import Now
from django.dispatch import Signal

from django_celery_outbox import metrics
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter
from django_celery_outbox.serialization import deserialize_options
from django_celery_outbox.signals import (
    outbox_message_dead_lettered,
    outbox_message_failed,
    outbox_message_sent,
)

_logger = structlog.getLogger(__name__)
_STALE_TIMEOUT = timedelta(minutes=5)


class Relay:
    def __init__(
        self,
        app: Celery,
        batch_size: int = 100,
        idle_time: float = 1.0,
        backoff_time: int = 120,
        max_retries: int = 5,
        liveness_file: str | None = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError('batch_size must be > 0')

        if idle_time < 0:
            raise ValueError('idle_time must be >= 0')

        if backoff_time <= 0:
            raise ValueError('backoff_time must be > 0')

        if max_retries <= 0:
            raise ValueError('max_retries must be > 0')

        self._app = app
        self._batch_size = batch_size
        self._idle_time = idle_time
        self._backoff_time = backoff_time
        self._max_retries = max_retries
        self._liveness_file = Path(liveness_file) if liveness_file else None
        self._running = True

    def start(self) -> None:
        self._setup_signals()

        _logger.info(
            'celery_outbox_relay_started',
            batch_size=self._batch_size,
            idle_time=self._idle_time,
            backoff_time=self._backoff_time,
            max_retries=self._max_retries,
        )

        while self._running:
            self._processing()

    def _setup_signals(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        _logger.info('celery_outbox_relay_shutdown', signal=signum)
        self._running = False

    def _processing(self) -> None:
        start_time = time.monotonic()
        close_old_connections()

        with sentry_sdk.start_span(op='queue.process', name='celery_outbox.relay.batch') as batch_span:
            with transaction.atomic():
                messages = self._select_messages()
                message_ids = [msg.id for msg in messages]
                if message_ids:
                    CeleryOutbox.objects.filter(pk__in=message_ids).update(
                        updated_at=Now(),
                    )

            published, failed, exceeded = self._process_messages(messages)

            close_old_connections()

            with transaction.atomic():
                self._update_failed(failed)
                self._delete_done(published)
                self._move_to_dead_letter(exceeded)

            batch_span.set_data('celery_outbox.published', len(published))
            batch_span.set_data('celery_outbox.failed', len(failed))
            batch_span.set_data('celery_outbox.exceeded', len(exceeded))
            batch_span.set_data('celery_outbox.batch_size', len(messages))

            if failed or exceeded:
                batch_span.set_status('internal_error')
            else:
                batch_span.set_status('ok')

        queue_depth = CeleryOutbox.objects.count()
        metrics.gauge('queue.depth', queue_depth)
        metrics.gauge('dead_letter.count', CeleryOutboxDeadLetter.objects.count())
        metrics.timing('batch.duration_ms', (time.monotonic() - start_time) * 1000)

        _logger.info(
            'celery_outbox_batch_processed',
            published=len(published),
            failed=len(failed),
            exceeded=len(exceeded),
            queue_depth=queue_depth,
        )

        self._touch_liveness()

        batch_total = len(published) + len(failed) + len(exceeded)
        if batch_total < self._batch_size:
            _logger.debug('celery_outbox_relay_idle')
            time.sleep(self._idle_time)
        else:
            _logger.debug('celery_outbox_relay_busy')

    def _select_messages(self) -> list[CeleryOutbox]:
        queryset = (
            CeleryOutbox.objects.select_for_update(
                skip_locked=True,
            )
            .filter(
                Q(updated_at__isnull=True)
                | Q(retry_after__lte=Now())
                | Q(updated_at__lte=Now() - _STALE_TIMEOUT, retry_after__isnull=True),
            )
            .order_by('id')[: self._batch_size]
        )

        return list(queryset)

    def _process_messages(
        self,
        messages: list[CeleryOutbox],
    ) -> tuple[list[int], list[tuple[int, int]], list[int]]:
        published: list[int] = []
        failed: list[tuple[int, int]] = []
        exceeded: list[int] = []

        for msg in messages:
            if msg.retries >= self._max_retries:
                _logger.warning(
                    'celery_outbox_max_retries_exceeded',
                    outbox_id=msg.id,
                    task_name=msg.task_name,
                    task_id=msg.task_id,
                    retries=msg.retries,
                )
                exceeded.append(msg.id)
                metrics.increment('messages.exceeded', tags={'task_name': msg.task_name})
                continue

            with sentry_sdk.start_span(op='celery_outbox.relay.send', name=msg.task_name) as span:
                span.set_data('messaging.message.id', msg.task_id)
                span.set_data('messaging.message.retry.count', msg.retries)

                try:
                    self._send_task(msg)
                except Exception:
                    span.set_status('internal_error')
                    _logger.error(
                        'celery_outbox_send_failed',
                        outbox_id=msg.id,
                        task_name=msg.task_name,
                        task_id=msg.task_id,
                        retries=msg.retries,
                        exc_info=True,
                    )
                    if msg.retries >= self._max_retries - 1:
                        _logger.warning(
                            'celery_outbox_max_retries_exceeded',
                            outbox_id=msg.id,
                            task_name=msg.task_name,
                            task_id=msg.task_id,
                            retries=msg.retries,
                        )
                        exceeded.append(msg.id)
                        metrics.increment('messages.exceeded', tags={'task_name': msg.task_name})
                    else:
                        failed.append((msg.id, msg.retries))
                        metrics.increment('messages.failed', tags={'task_name': msg.task_name})
                        self._send_signal_safe(outbox_message_failed, msg.task_id, msg.task_name, retries=msg.retries)
                else:
                    span.set_status('ok')
                    published.append(msg.id)
                    metrics.increment('messages.published', tags={'task_name': msg.task_name})
                    self._send_signal_safe(outbox_message_sent, msg.task_id, msg.task_name)

        return published, failed, exceeded

    def _send_task(self, msg: CeleryOutbox) -> None:
        options = deserialize_options(msg.options, self._app)

        headers = options.pop('headers', {}) or {}
        if msg.sentry_trace_id:
            headers['sentry-trace'] = msg.sentry_trace_id
        if msg.sentry_baggage:
            headers['baggage'] = msg.sentry_baggage

        eta = options.pop('eta', None)

        ctx = self._parse_structlog_context(msg.structlog_context)

        with structlog.contextvars.bound_contextvars(**ctx):
            Celery.send_task(
                self._app,
                name=msg.task_name,
                args=msg.args,
                kwargs=msg.kwargs,
                task_id=msg.task_id,
                eta=eta,
                headers=headers,
                **options,
            )

    def _touch_liveness(self) -> None:
        if self._liveness_file is None:
            return

        self._liveness_file.touch()

    @staticmethod
    def _send_signal_safe(sig: Signal, task_id: str, task_name: str, **kwargs: object) -> None:
        try:
            sig.send(sender=Relay, task_id=task_id, task_name=task_name, **kwargs)
        except Exception:
            _logger.error(
                'celery_outbox_signal_error',
                signal=getattr(sig, 'providing_args', str(sig)),
                task_id=task_id,
                task_name=task_name,
                exc_info=True,
            )

    @staticmethod
    def _parse_structlog_context(raw: str | None) -> dict:
        if not raw:
            return {}

        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    def _update_failed(self, failed_messages: list[tuple[int, int]]) -> None:
        if not failed_messages:
            return

        for msg_id, retries in failed_messages:
            jitter = random.uniform(0, self._backoff_time * 0.1)  # noqa: S311
            delay = timedelta(seconds=self._backoff_time * (2 ** retries) + jitter)
            CeleryOutbox.objects.filter(pk=msg_id).update(
                retries=F('retries') + 1,
                updated_at=Now(),
                retry_after=Now() + delay,
            )

    def _delete_done(self, message_ids: list[int]) -> None:
        if not message_ids:
            return

        CeleryOutbox.objects.filter(pk__in=message_ids).delete()

    def _move_to_dead_letter(self, exceeded_ids: list[int]) -> None:
        if not exceeded_ids:
            return

        messages = CeleryOutbox.objects.filter(pk__in=exceeded_ids)
        dead_letters = []
        for msg in messages:
            dead_letters.append(
                CeleryOutboxDeadLetter(
                    created_at=msg.created_at,
                    retries=msg.retries,
                    task_id=msg.task_id,
                    task_name=msg.task_name,
                    args=msg.args,
                    kwargs=msg.kwargs,
                    options=msg.options,
                    sentry_trace_id=msg.sentry_trace_id,
                    sentry_baggage=msg.sentry_baggage,
                    structlog_context=msg.structlog_context,
                    failure_reason='max retries exceeded',
                )
            )

        CeleryOutboxDeadLetter.objects.bulk_create(dead_letters)
        CeleryOutbox.objects.filter(pk__in=exceeded_ids).delete()

        for msg in messages:
            self._send_signal_safe(
                outbox_message_dead_lettered,
                msg.task_id,
                msg.task_name,
                task_ids=[msg.task_id],
                task_names=[msg.task_name],
            )
