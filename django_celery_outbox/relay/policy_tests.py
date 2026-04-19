from amqp.exceptions import AccessRefused, InvalidPath, NotFound, PreconditionFailed
from amqp.exceptions import ChannelError as AmqpChannelError
from amqp.exceptions import ConnectionError as AmqpConnectionError
from kombu.exceptions import OperationalError

from django_celery_outbox.relay._policy import RelayPolicy, is_broker_outage


def test_is_broker_outage_timeout_error() -> None:
    assert is_broker_outage(TimeoutError('timed out')) is True


def test_is_broker_outage_builtin_connection_error() -> None:
    assert is_broker_outage(ConnectionError('broker down')) is True


def test_is_broker_outage_broken_pipe_error() -> None:
    assert is_broker_outage(BrokenPipeError('pipe broken')) is True


def test_is_broker_outage_connection_reset_error() -> None:
    assert is_broker_outage(ConnectionResetError('connection reset')) is True


def test_is_broker_outage_kombu_operational_error() -> None:
    assert is_broker_outage(OperationalError('down')) is True


def test_is_broker_outage_amqp_connection_error() -> None:
    assert is_broker_outage(AmqpConnectionError('down')) is True


def test_is_broker_outage_amqp_channel_error() -> None:
    assert is_broker_outage(AmqpChannelError('down')) is True


def test_is_broker_outage_value_error_false() -> None:
    assert is_broker_outage(ValueError('bad payload')) is False


def test_is_broker_outage_access_refused_false() -> None:
    assert is_broker_outage(AccessRefused('bad credentials')) is False


def test_is_broker_outage_not_found_false() -> None:
    assert is_broker_outage(NotFound('missing exchange')) is False


def test_is_broker_outage_precondition_failed_false() -> None:
    assert is_broker_outage(PreconditionFailed('invalid precondition')) is False


def test_is_broker_outage_invalid_path_false() -> None:
    assert is_broker_outage(InvalidPath('bad vhost path')) is False


def test_policy_opens_breaker_after_two_consecutive_outages_in_one_batch() -> None:
    policy = RelayPolicy(broker_outage_cooldown=30.0, shutdown_timeout=30.0)
    policy.begin_batch()

    assert policy.record_outage(now_monotonic=100.0) is False
    assert policy.record_outage(now_monotonic=101.0) is True
    assert policy.should_skip_batch(now_monotonic=110.0) is True
    assert policy.seconds_until_batch_retry(now_monotonic=110.0) == 21.0


def test_policy_cooldown_expiry_allows_next_batch() -> None:
    policy = RelayPolicy(broker_outage_cooldown=30.0, shutdown_timeout=30.0)
    policy.begin_batch()
    assert policy.record_outage(now_monotonic=100.0) is False
    assert policy.record_outage(now_monotonic=101.0) is True

    assert policy.should_skip_batch(now_monotonic=132.0) is False
    assert policy.seconds_until_batch_retry(now_monotonic=132.0) == 0.0


def test_policy_begin_batch_resets_outage_streak() -> None:
    policy = RelayPolicy(broker_outage_cooldown=30.0, shutdown_timeout=30.0)
    policy.begin_batch()
    assert policy.record_outage(now_monotonic=100.0) is False

    policy.begin_batch()

    assert policy.record_outage(now_monotonic=101.0) is False


def test_policy_record_success_resets_outage_streak() -> None:
    policy = RelayPolicy(broker_outage_cooldown=30.0, shutdown_timeout=30.0)
    policy.begin_batch()
    assert policy.record_outage(now_monotonic=100.0) is False

    policy.record_success()

    assert policy.record_outage(now_monotonic=101.0) is False


def test_policy_shutdown_deadline_exceeded() -> None:
    policy = RelayPolicy(broker_outage_cooldown=30.0, shutdown_timeout=30.0)
    policy.begin_shutdown(now_monotonic=100.0)

    assert policy.shutdown_deadline_exceeded(now_monotonic=129.9) is False
    assert policy.shutdown_deadline_exceeded(now_monotonic=130.0) is True
