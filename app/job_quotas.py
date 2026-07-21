import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import AuthenticatedPrincipal
from app.models import JobStatus, VideoJob


MAX_ACTIVE_JOBS_PER_USER = int(
    os.getenv(
        "MAX_ACTIVE_JOBS_PER_USER",
        "2",
    )
)

DAILY_LIMITS = {
    "development": int(
        os.getenv(
            "DEVELOPMENT_DAILY_JOB_LIMIT",
            "20",
        )
    ),
    "standard": int(
        os.getenv(
            "STANDARD_DAILY_JOB_LIMIT",
            "100",
        )
    ),
    "enterprise": int(
        os.getenv(
            "ENTERPRISE_DAILY_JOB_LIMIT",
            "1000",
        )
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
        code: str,
        message: str,
        limit: int,
    ) -> None:
        self.code = code
        self.message = message
        self.limit = limit

        super().__init__(message)


def get_daily_limit(
    plan: str,
) -> int:
    normalized_plan = (
        plan or "development"
    ).strip().lower()

    return DAILY_LIMITS.get(
        normalized_plan,
        DAILY_LIMITS["development"],
    )


def enforce_job_quota(
    db: Session,
    principal: AuthenticatedPrincipal,
) -> JobQuotaUsage:
    """
    Check active and daily job limits for one user inside
    one tenant.

    This must execute before the new VideoJob is inserted.
    """

    active_statuses = [
        JobStatus.QUEUED,
        JobStatus.PROCESSING,
    ]

    active_jobs = db.scalar(
        select(func.count(VideoJob.id)).where(
            VideoJob.owner_id
            == principal.user_id,
            VideoJob.tenant_id
            == principal.tenant_id,
            VideoJob.status.in_(
                active_statuses
            ),
        )
    ) or 0

    if (
        active_jobs
        >= MAX_ACTIVE_JOBS_PER_USER
    ):
        raise JobQuotaExceededError(
            code="ACTIVE_JOB_LIMIT_EXCEEDED",
            message=(
                "The maximum number of active "
                "processing jobs has been reached."
            ),
            limit=MAX_ACTIVE_JOBS_PER_USER,
        )

    now = datetime.now(timezone.utc)
    start_of_day = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    daily_limit = get_daily_limit(
        principal.plan
    )

    daily_jobs = db.scalar(
        select(func.count(VideoJob.id)).where(
            VideoJob.owner_id
            == principal.user_id,
            VideoJob.tenant_id
            == principal.tenant_id,
            VideoJob.created_at
            >= start_of_day,
            VideoJob.created_at
            < start_of_day
            + timedelta(days=1),
        )
    ) or 0

    if daily_jobs >= daily_limit:
        raise JobQuotaExceededError(
            code="DAILY_JOB_LIMIT_EXCEEDED",
            message=(
                "The daily processing job quota "
                "has been reached."
            ),
            limit=daily_limit,
        )

    return JobQuotaUsage(
        active_jobs=active_jobs,
        max_active_jobs=(
            MAX_ACTIVE_JOBS_PER_USER
        ),
        daily_jobs=daily_jobs,
        max_daily_jobs=daily_limit,
    )