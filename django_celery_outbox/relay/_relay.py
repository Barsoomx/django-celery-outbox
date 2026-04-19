import signal
import time
from datetime import timedelta
from types import FrameType

import sentry_sdk
import structlog
from celery import Celery
from django.db import close_old_connections, connections, transaction
from django.dispatch import Signal
from django.utils import timezone
from kombu.transport.native_delayed_delivery import (
    declare_native_delayed_delivery_exchanges_and_queues,
)

from django_celery_outbox import metrics
from django_celery_outbox.metrics import get_task_tag
from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter
from django_celery_outbox.relay._config import RelayConfig
from django_celery_outbox.relay._message_selector import MessageSelector, get_pending_filter
from django_celery_outbox.relay._mutations import RelayMutations
from django_celery_outbox.relay._policy import RelayPolicy, is_broker_outage
from django_celery_outbox.relay._publisher import RelayPublisher
from django_celery_outbox.relay._runtime import classify_exception, should_log_traceback
from django_celery_outbox.signals import (
    outbox_message_dead_lettered,
    outbox_message_failed,
    outbox_message_sent,
)

_logger = structlog.getLogger(__name__)


class Relay:
    def __init__(
        self,
        app: Celery,
        config: RelayConfig,
        selector: MessageSelector | None = None,
    ) -> None:
        db_alias = CeleryOutbox.objects.db
        db_connection = connections[db_alias]
        if not db_connection.features.has_select_for_update_skip_locked:
            raise RuntimeError(
                f'Database backend "{db_connection.vendor}" does not support '
                f'SELECT FOR UPDATE SKIP LOCKED. '
                f'django-celery-outbox requires PostgreSQL >= 9.5 or MySQL >= 8.0.1.'
            )

        self._app = app
        self._config = config
        self._selector = selector or MessageSelector(
            batch_size=config.batch_size,
            stale_timeout=timedelta(seconds=config.stale_timeout_seconds),
        )
        self._publisher = RelayPublisher(app=app, send_timeout=config.send_timeout)
        self._mutations = RelayMutations(
            backoff_time=config.backoff_time,
            max_backoff=config.max_backoff,
        )
        self._policy = RelayPolicy(
            broker_outage_cooldown=config.broker_outage_cooldown,
            shutdown_timeout=config.shutdown_timeout,
        )
        self._running = True

    def start(self) -> None:
        self._setup_signals()
        self._setup_delayed_delivery()

        _logger.info(
            'celery_outbox_relay_started',
            batch_size=self._config.batch_size,
            idle_time=self._config.idle_time,
            backoff_time=self._config.backoff_time,
            max_retries=self._config.max_retries,
        )

        while self._running or self._should_continue_draining():
            try:
                self._processing()
            except Exception as exc:
                sentry_sdk.capture_exception(exc)
                log_kwargs = {
                    'exception_type': type(exc).__name__,
                    'exception_message': str(exc),
                }
                if should_log_traceback():
                    _logger.error('celery_outbox_relay_iteration_failed', **log_kwargs, exc_info=True)
                else:
                    _logger.error('celery_outbox_relay_iteration_failed', **log_kwargs)

                if self._running or self._should_continue_draining():
                    time.sleep(self._config.idle_time)

    def _setup_signals(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _setup_delayed_delivery(self) -> None:
        queue_type = self._app.conf.broker_native_delayed_delivery_queue_type or 'quorum'
        try:
            with self._app.connection_for_write() as connection:
                declare_native_delayed_delivery_exchanges_and_queues(connection, queue_type)
                _logger.info('celery_outbox_delayed_delivery_setup', queue_type=queue_type)
        except Exception as exc:
            _logger.warning(
                'celery_outbox_delayed_delivery_setup_failed',
                exception_type=type(exc).__name__,
                exception_message=str(exc),
            )

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        _logger.info('celery_outbox_relay_shutdown', signal=signum)
        self._policy.begin_shutdown(time.monotonic())
        self._running = False

    def _should_continue_draining(self) -> bool:
        if not self._policy.shutdown_requested():
            return False

        if self._policy.shutdown_deadline_exceeded(time.monotonic()):
            return False

        return CeleryOutbox.objects.filter(get_pending_filter()).exists()

    def _finalize_processing_cycle(
        self,
        *,
        start_time: float,
        published: int,
        failed: int,
        exceeded: int,
        deferred_due_to_outage: int,
        shutdown_aborted: int,
    ) -> None:
        queue_depth = CeleryOutbox.objects.count()
        metrics.gauge('queue.depth', queue_depth)
        metrics.gauge('dead_letter.count', CeleryOutboxDeadLetter.objects.count())
        metrics.timing('batch.duration_ms', (time.monotonic() - start_time) * 1000)

        oldest = CeleryOutbox.objects.filter(get_pending_filter()).order_by('created_at').values_list('created_at', flat=True).first()
        if oldest:
            age_seconds = (timezone.now() - oldest).total_seconds()
            metrics.gauge('oldest_pending_age_seconds', age_seconds)
        else:
            metrics.gauge('oldest_pending_age_seconds', 0)

        _logger.info(
            'celery_outbox_batch_processed',
            published=published,
            failed=failed,
            exceeded=exceeded,
            deferred_due_to_outage=deferred_due_to_outage,
            shutdown_aborted=shutdown_aborted,
            queue_depth=queue_depth,
        )

        self._touch_liveness()

    def _processing(self) -> None:
        start_time = time.monotonic()
        now_monotonic = time.monotonic()
        with sentry_sdk.start_span(op='queue.process', name='celery_outbox.relay.batch') as batch_span:
            if self._policy.should_skip_batch(now_monotonic):
                sleep_for = self._policy.seconds_until_batch_retry(now_monotonic)
                if self._policy.shutdown_requested():
                    sleep_for = min(
                        sleep_for,
                        self._policy.seconds_until_shutdown_deadline(time.monotonic()),
                    )
                _logger.warning(
                    'celery_outbox_relay_breaker_open',
                    cooldown_seconds=sleep_for,
                )
                batch_span.set_data('celery_outbox.published', 0)
                batch_span.set_data('celery_outbox.failed', 0)
                batch_span.set_data('celery_outbox.exceeded', 0)
                batch_span.set_data('celery_outbox.deferred_due_to_outage', 0)
                batch_span.set_data('celery_outbox.shutdown_aborted', 0)
                batch_span.set_data('celery_outbox.batch_size', 0)
                batch_span.set_status('ok')
                close_old_connections()
                time.sleep(sleep_for)
                close_old_connections()
                self._finalize_processing_cycle(
                    start_time=start_time,
                    published=0,
                    failed=0,
                    exceeded=0,
                    deferred_due_to_outage=0,
                    shutdown_aborted=0,
                )
                return

            close_old_connections()

            with transaction.atomic():
                messages = self._selector.run()

            published, failed, exceeded, deferred_due_to_outage, shutdown_aborted = self._process_messages(messages)

            close_old_connections()

            with transaction.atomic():
                self._mutations.update_failed(failed)
                self._mutations.delete_published(published)
                self._mutations.move_exceeded_to_dead_letter(exceeded)
                self._mutations.defer_due_to_outage(
                    deferred_due_to_outage,
                    cooldown_seconds=self._config.broker_outage_cooldown,
                )
                for msg in exceeded:
                    self._send_signal_safe(
                        outbox_message_dead_lettered,
                        msg.task_id,
                        msg.task_name,
                        task_ids=[msg.task_id],
                        task_names=[msg.task_name],
                    )

            batch_span.set_data('celery_outbox.published', len(published))
            batch_span.set_data('celery_outbox.failed', len(failed))
            batch_span.set_data('celery_outbox.exceeded', len(exceeded))
            batch_span.set_data('celery_outbox.deferred_due_to_outage', len(deferred_due_to_outage))
            batch_span.set_data('celery_outbox.shutdown_aborted', len(shutdown_aborted))
            batch_span.set_data('celery_outbox.batch_size', len(messages))

            if failed or exceeded or deferred_due_to_outage:
                batch_span.set_status('internal_error')
            else:
                batch_span.set_status('ok')

        self._finalize_processing_cycle(
            start_time=start_time,
            published=len(published),
            failed=len(failed),
            exceeded=len(exceeded),
            deferred_due_to_outage=len(deferred_due_to_outage),
            shutdown_aborted=len(shutdown_aborted),
        )

        if len(messages) < self._config.batch_size:
            _logger.debug('celery_outbox_relay_idle')
            time.sleep(self._config.idle_time)
        else:
            _logger.debug('celery_outbox_relay_busy')

    def _process_messages(
        self,
        messages: list[CeleryOutbox],
    ) -> tuple[list[int], list[tuple[int, int]], list[CeleryOutbox], list[int], list[CeleryOutbox]]:
        published: list[int] = []
        failed: list[tuple[int, int]] = []
        exceeded: list[CeleryOutbox] = []
        deferred_due_to_outage: list[int] = []
        shutdown_aborted: list[CeleryOutbox] = []

        self._policy.begin_batch()

        for index, msg in enumerate(messages):
            if self._policy.shutdown_deadline_exceeded(time.monotonic()):
                shutdown_aborted = messages[index:]
                _logger.warning(
                    'celery_outbox_relay_shutdown_deadline_exceeded',
                    aborted_count=len(shutdown_aborted),
                    aborted_task_ids=[item.task_id for item in shutdown_aborted],
                    aborted_task_names=[item.task_name for item in shutdown_aborted],
                )
                break

            msg_context = {
                'outbox_id': msg.id,
                'task_name': msg.task_name,
                'task_id': msg.task_id,
                'retries': msg.retries,
            }

            with structlog.contextvars.bound_contextvars(**msg_context):
                if msg.retries >= self._config.max_retries:
                    _logger.warning(
                        'celery_outbox_max_retries_exceeded',
                        exception_type='pre_exceeded',
                        exception_message='message already exceeded max retries before send attempt',
                    )
                    tags = get_task_tag(msg.task_name)
                    tags['exception_type'] = 'pre_exceeded'
                    metrics.increment('messages.exceeded', tags=tags)
                    exceeded.append(msg)
                    continue

                with sentry_sdk.start_span(op='celery_outbox.relay.send', name=msg.task_name) as span:
                    span.set_data('messaging.message.id', msg.task_id)
                    span.set_data('messaging.message.retry.count', msg.retries)

                    try:
                        self._publisher.publish(msg)
                    except Exception as exc:
                        span.set_status('internal_error')

                        if is_broker_outage(exc):
                            deferred_due_to_outage.append(msg.id)
                            breaker_opened = self._policy.record_outage(time.monotonic())
                            if breaker_opened:
                                remaining_messages = messages[index + 1 :]
                                deferred_due_to_outage.extend(item.id for item in remaining_messages)
                                _logger.warning(
                                    'celery_outbox_relay_breaker_trip',
                                    deferred_count=len(deferred_due_to_outage),
                                    exception_type=type(exc).__name__,
                                    exception_message=str(exc),
                                )
                                break
                            continue

                        self._policy.record_success()
                        exc_type = classify_exception(exc)
                        log_kwargs = {
                            'exception_type': exc_type,
                            'exception_message': str(exc),
                        }

                        if should_log_traceback():
                            _logger.error('celery_outbox_send_failed', **log_kwargs, exc_info=True)
                        else:
                            _logger.error('celery_outbox_send_failed', **log_kwargs)

                        if msg.retries >= self._config.max_retries - 1:
                            _logger.warning(
                                'celery_outbox_max_retries_exceeded',
                                exception_type=exc_type,
                                exception_message=str(exc),
                            )
                            tags = get_task_tag(msg.task_name)
                            tags['exception_type'] = exc_type
                            metrics.increment('messages.exceeded', tags=tags)
                            exceeded.append(msg)
                        else:
                            tags = get_task_tag(msg.task_name)
                            tags['exception_type'] = exc_type
                            metrics.increment('messages.failed', tags=tags)
                            self._send_signal_safe(
                                outbox_message_failed,
                                msg.task_id,
                                msg.task_name,
                                retries=msg.retries,
                            )
                            failed.append((msg.id, msg.retries))
                    else:
                        span.set_status('ok')
                        self._policy.record_success()
                        latency_ms = (time.time() - msg.created_at.timestamp()) * 1000
                        tags = get_task_tag(msg.task_name)
                        metrics.timing('send_latency_ms', latency_ms, tags=tags)
                        metrics.increment('messages.published', tags=tags)
                        self._send_signal_safe(outbox_message_sent, msg.task_id, msg.task_name)
                        published.append(msg.id)

        return published, failed, exceeded, deferred_due_to_outage, shutdown_aborted

    def _touch_liveness(self) -> None:
        if self._config.liveness_file is None:
            return

        self._config.liveness_file.touch()

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
