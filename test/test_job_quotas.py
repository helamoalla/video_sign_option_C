from types import SimpleNamespace

import pytest

import app.job_quotas as quotas
from app.auth import AuthenticatedPrincipal
from app.job_quotas import (
    JobQuotaExceededError,
    enforce_job_quota,
    get_daily_limit,
    get_quota_lock_id,
)


class FakeDatabase:
    def __init__(
        self,
        scalar_results: list[int],
    ):
        self.scalar_results = list(
            scalar_results
        )
        self.executed_statements = []
        self.scalar_statements = []

    def execute(self, statement):
        self.executed_statements.append(
            statement
        )
        return SimpleNamespace()

    def scalar(self, statement):
        self.scalar_statements.append(
            statement
        )
        return self.scalar_results.pop(0)


@pytest.fixture
def principal():
    return AuthenticatedPrincipal(
        credential_id=(
            "11111111-1111-1111-1111-111111111111"
        ),
        user_id=(
            "22222222-2222-2222-2222-222222222222"
        ),
        tenant_id=(
            "33333333-3333-3333-3333-333333333333"
        ),
        role="user",
        plan="development",
    )


def test_quota_lock_id_is_stable():
    first = get_quota_lock_id(
        tenant_id="tenant-1",
        user_id="user-1",
    )
    second = get_quota_lock_id(
        tenant_id="tenant-1",
        user_id="user-1",
    )

    assert first == second
    assert -(2**63) <= first < 2**63


def test_unknown_plan_uses_development_limit(
    monkeypatch,
):
    monkeypatch.setitem(
        quotas.DAILY_LIMITS,
        "development",
        7,
    )

    assert get_daily_limit("unknown") == 7


def test_valid_quota_returns_usage(
    principal,
    monkeypatch,
):
    monkeypatch.setattr(
        quotas,
        "MAX_ACTIVE_JOBS_PER_USER",
        2,
    )
    monkeypatch.setitem(
        quotas.DAILY_LIMITS,
        "development",
        20,
    )

    database = FakeDatabase(
        scalar_results=[1, 5]
    )

    usage = enforce_job_quota(
        database,
        principal,
    )

    assert usage.active_jobs == 1
    assert usage.max_active_jobs == 2
    assert usage.daily_jobs == 5
    assert usage.max_daily_jobs == 20
    assert len(
        database.executed_statements
    ) == 1


def test_active_job_limit_is_rejected(
    principal,
    monkeypatch,
):
    monkeypatch.setattr(
        quotas,
        "MAX_ACTIVE_JOBS_PER_USER",
        2,
    )

    database = FakeDatabase(
        scalar_results=[2]
    )

    with pytest.raises(
        JobQuotaExceededError
    ) as error:
        enforce_job_quota(
            database,
            principal,
        )

    assert (
        error.value.code
        == "ACTIVE_JOB_LIMIT_EXCEEDED"
    )
    assert error.value.limit == 2
    assert len(
        database.executed_statements
    ) == 1


def test_daily_job_limit_is_rejected(
    principal,
    monkeypatch,
):
    monkeypatch.setattr(
        quotas,
        "MAX_ACTIVE_JOBS_PER_USER",
        2,
    )
    monkeypatch.setitem(
        quotas.DAILY_LIMITS,
        "development",
        20,
    )

    database = FakeDatabase(
        scalar_results=[0, 20]
    )

    with pytest.raises(
        JobQuotaExceededError
    ) as error:
        enforce_job_quota(
            database,
            principal,
        )

    assert (
        error.value.code
        == "DAILY_JOB_LIMIT_EXCEEDED"
    )
    assert error.value.limit == 20
    assert len(
        database.executed_statements
    ) == 1