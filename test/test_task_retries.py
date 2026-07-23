from types import SimpleNamespace

import pytest

from app.tasks import (
    calculate_retry_delay,
    create_error_code,
    is_retryable_exception,
)


class TemporaryHttpError(Exception):
    def __init__(self, status_code: int):
        super().__init__(
            f"HTTP {status_code}"
        )

        self.response = SimpleNamespace(
            status_code=status_code
        )


@pytest.mark.parametrize(
    "exception",
    [
        TimeoutError("timeout"),
        ConnectionError("connection"),
        TemporaryHttpError(429),
        TemporaryHttpError(500),
        TemporaryHttpError(502),
        TemporaryHttpError(503),
        TemporaryHttpError(504),
    ],
)
def test_temporary_errors_are_retryable(
    exception,
):
    assert (
        is_retryable_exception(exception)
        is True
    )


@pytest.mark.parametrize(
    "exception",
    [
        ValueError("invalid input"),
        FileNotFoundError("asset missing"),
        TemporaryHttpError(400),
        TemporaryHttpError(401),
        TemporaryHttpError(404),
    ],
)
def test_permanent_errors_are_not_retryable(
    exception,
):
    assert (
        is_retryable_exception(exception)
        is False
    )


def test_nested_timeout_is_retryable():
    timeout = TimeoutError(
        "provider timeout"
    )

    wrapper = RuntimeError(
        "pipeline failed"
    )
    wrapper.__cause__ = timeout

    assert (
        is_retryable_exception(wrapper)
        is True
    )


def test_retry_delay_uses_exponential_backoff():
    assert calculate_retry_delay(1) == 30
    assert calculate_retry_delay(2) == 60
    assert calculate_retry_delay(3) == 120
    assert calculate_retry_delay(4) == 240
    assert calculate_retry_delay(5) == 300
    assert calculate_retry_delay(10) == 300


def test_error_code_does_not_expose_message():
    exception = ValueError(
        "/private/path/secret-file.mp4"
    )

    error_code = create_error_code(
        exception
    )

    assert error_code == "VALUEERROR"
    assert "private" not in error_code.lower()
    assert "secret" not in error_code.lower()