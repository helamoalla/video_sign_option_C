import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, time, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import AuthenticatedPrincipal
from app.models import JobStatus, VideoJob


MAX_ACTIVE_JOBS_PER_USER = int(
    os.getenv("MAX_ACTIVE_JOBS_PER_USER", "2")
)

DAILY_LIMITS = {
    "development": int(
        os.getenv("DAILY_JOB_LIMIT_DEVELOPMENT", "20")
    ),
    "standard": int(
        os.getenv("DAILY_JOB_LIMIT_STANDARD", "100")
    ),
    "business": int(
        os.getenv("DAILY_JOB_LIMIT_BUSINESS", "500")
    ),
}


@dataclass(frozen=True)
class JobQuotaUsage:
    active_jobs: int
    max_active_jobs: int
    daily_jobs: int
    max_daily_jobs: int


class JobQuotaExceededError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        limit: int,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.limit = limit


def get_daily_limit(plan: str) -> int:
    normalized_plan = (plan or "").strip().lower()
    return DAILY_LIMITS.get(
        normalized_plan,
        DAILY_LIMITS["development"],
    )


def get_quota_lock_id(
    *,
    tenant_id: str,
    user_id: str,
) -> int:
    """Return a stable signed 64-bit PostgreSQL advisory-lock ID."""

    value = f"{tenant_id}:{user_id}".encode("utf-8")
    digest = hashlib.sha256(value).digest()
    return int.from_bytes(
        digest[:8],
        byteorder="big",
        signed=True,
    )


def acquire_job_submission_lock(
    db: Session,
    principal: AuthenticatedPrincipal,
) -> None:
    """
    Serialize submissions for one tenant/user until the current
    PostgreSQL transaction commits or rolls back.
    """

    lock_id = get_quota_lock_id(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )

    db.execute(
        text(
            "SELECT pg_advisory_xact_lock(:lock_id)"
        ).bindparams(lock_id=lock_id)
    )


def enforce_job_quota(
    db: Session,
    principal: AuthenticatedPrincipal,
    *,
    acquire_lock: bool = True,
) -> JobQuotaUsage:
    if acquire_lock:
        acquire_job_submission_lock(
            db,
            principal,
        )

    active_jobs = int(
        db.scalar(
            select(func.count(VideoJob.id)).where(
                VideoJob.owner_id == principal.user_id,
                VideoJob.tenant_id == principal.tenant_id,
                VideoJob.status.in_(
                    [
                        JobStatus.QUEUED,
                        JobStatus.PROCESSING,
                    ]
                ),
            )
        )
        or 0
    )

    if active_jobs >= MAX_ACTIVE_JOBS_PER_USER:
        raise JobQuotaExceededError(
            code="ACTIVE_JOB_LIMIT_EXCEEDED",
            message=(
                "The maximum number of active processing jobs "
                "has been reached."
            ),
            limit=MAX_ACTIVE_JOBS_PER_USER,
        )

    now = datetime.now(timezone.utc)
    start_of_day = datetime.combine(
        now.date(),
        time.min,
        tzinfo=timezone.utc,
    )
    daily_limit = get_daily_limit(principal.plan)

    daily_jobs = int(
        db.scalar(
            select(func.count(VideoJob.id)).where(
                VideoJob.owner_id == principal.user_id,
                VideoJob.tenant_id == principal.tenant_id,
                VideoJob.created_at >= start_of_day,
            )
        )
        or 0
    )

    if daily_jobs >= daily_limit:
        raise JobQuotaExceededError(
            code="DAILY_JOB_LIMIT_EXCEEDED",
            message=(
                "The daily processing-job limit has been reached."
            ),
            limit=daily_limit,
        )

    return JobQuotaUsage(
        active_jobs=active_jobs,
        max_active_jobs=MAX_ACTIVE_JOBS_PER_USER,
        daily_jobs=daily_jobs,
        max_daily_jobs=daily_limit,
    )