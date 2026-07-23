from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.media_retention import (
    delete_all_media_for_job,
)
from app.models import JobStatus, VideoJob


class JobCannotBeCancelledError(Exception):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CancellationResult:
    job_id: str
    status: JobStatus
    stage: str
    cancellation_pending: bool
    celery_task_id: str | None
    revoke_task: bool
    audit_id: str | None


def request_job_cancellation(
    db: Session,
    job: VideoJob,
    *,
    requested_by: str,
) -> CancellationResult:
    """
    Request cooperative cancellation.

    Queued/retrying jobs are cancelled immediately. A processing job
    is marked for cancellation and stops at its next pipeline
    progress checkpoint.
    """

    now = utc_now()

    if job.status == JobStatus.CANCELLED:
        return CancellationResult(
            job_id=job.id,
            status=job.status,
            stage=job.stage,
            cancellation_pending=False,
            celery_task_id=job.celery_task_id,
            revoke_task=False,
            audit_id=None,
        )

    if job.status in {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    }:
        raise JobCannotBeCancelledError(
            "A completed or failed job cannot be cancelled. "
            "Use the media-deletion endpoint if its artifacts "
            "must be removed."
        )

    job.cancel_requested_at = (
        job.cancel_requested_at
        or now
    )

    if job.status in {
        JobStatus.QUEUED,
        JobStatus.RETRYING,
    }:
        job.status = JobStatus.CANCELLED
        job.stage = "cancelled"
        job.cancelled_at = now
        job.error = None
        job.last_error_code = None
        job.dead_lettered_at = None

        audit = delete_all_media_for_job(
            db,
            job,
            reason="user_cancelled",
            requested_by=requested_by,
            now=now,
        )

        db.flush()

        return CancellationResult(
            job_id=job.id,
            status=job.status,
            stage=job.stage,
            cancellation_pending=False,
            celery_task_id=job.celery_task_id,
            revoke_task=True,
            audit_id=audit.id,
        )

    job.stage = "cancellation_requested"

    return CancellationResult(
        job_id=job.id,
        status=job.status,
        stage=job.stage,
        cancellation_pending=True,
        celery_task_id=job.celery_task_id,
        revoke_task=False,
        audit_id=None,
    )