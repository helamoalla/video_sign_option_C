import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    JobStatus,
    MediaDeletionAudit,
    VideoJob,
)


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOAD_ROOT = PROJECT_ROOT / "uploads"
OUTPUT_ROOT = PROJECT_ROOT / "outputs"

OUTPUT_RETENTION_HOURS = int(
    os.getenv("OUTPUT_RETENTION_HOURS", "168")
)

FAILED_MEDIA_RETENTION_HOURS = int(
    os.getenv("FAILED_MEDIA_RETENTION_HOURS", "24")
)

RETENTION_CLEANUP_BATCH_SIZE = int(
    os.getenv("RETENTION_CLEANUP_BATCH_SIZE", "100")
)

TERMINAL_JOB_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}

class ActiveJobDeletionError(Exception):
    pass


class UnsafeMediaPathError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_media_expiration(
    status: JobStatus,
    *,
    now: datetime | None = None,
) -> datetime:
    reference_time = now or utc_now()

    if status == JobStatus.FAILED:
        retention_hours = FAILED_MEDIA_RETENTION_HOURS
    else:
        retention_hours = OUTPUT_RETENTION_HOURS

    return reference_time + timedelta(
        hours=max(1, retention_hours)
    )


def get_safe_job_directory(
    root: Path,
    job_id: str,
) -> Path:
    resolved_root = root.resolve()
    candidate = resolved_root / job_id

    # Reject a job directory that is itself a symbolic link. Its
    # target could escape the disposable media root.
    if candidate.is_symlink():
        raise UnsafeMediaPathError(
            "A symbolic-link job directory cannot be deleted."
        )

    resolved_candidate = candidate.resolve()

    if not resolved_candidate.is_relative_to(resolved_root):
        raise UnsafeMediaPathError(
            "The resolved job directory is outside its media root."
        )

    return resolved_candidate


def delete_job_directory(
    root: Path,
    job_id: str,
) -> bool:
    directory = get_safe_job_directory(
        root,
        job_id,
    )

    if not directory.exists():
        return False

    if not directory.is_dir():
        raise UnsafeMediaPathError(
            "The job media path is not a directory."
        )

    shutil.rmtree(directory)
    return True


def create_deletion_audit(
    *,
    job: VideoJob,
    reason: str,
    requested_by: str,
    upload_deleted: bool,
    output_deleted: bool,
    details: dict | None = None,
) -> MediaDeletionAudit:
    return MediaDeletionAudit(
        job_id=job.id,
        owner_id=job.owner_id,
        tenant_id=job.tenant_id,
        reason=reason,
        requested_by=requested_by,
        upload_deleted=upload_deleted,
        output_deleted=output_deleted,
        details=details or {},
    )


def delete_upload_for_job(
    db: Session,
    job: VideoJob,
    *,
    reason: str,
    requested_by: str = "system",
) -> MediaDeletionAudit:
    upload_deleted = delete_job_directory(
        UPLOAD_ROOT,
        job.id,
    )

    audit = create_deletion_audit(
        job=job,
        reason=reason,
        requested_by=requested_by,
        upload_deleted=upload_deleted,
        output_deleted=False,
        details={
            "scope": "upload",
        },
    )

    db.add(audit)
    return audit


def delete_all_media_for_job(
    db: Session,
    job: VideoJob,
    *,
    reason: str,
    requested_by: str,
    now: datetime | None = None,
) -> MediaDeletionAudit:
    if job.status not in TERMINAL_JOB_STATUSES:
        raise ActiveJobDeletionError(
            "Media cannot be deleted while a job is active."
        )

    deletion_time = now or utc_now()

    upload_deleted = delete_job_directory(
        UPLOAD_ROOT,
        job.id,
    )
    output_deleted = delete_job_directory(
        OUTPUT_ROOT,
        job.id,
    )

    audit = create_deletion_audit(
        job=job,
        reason=reason,
        requested_by=requested_by,
        upload_deleted=upload_deleted,
        output_deleted=output_deleted,
        details={
            "scope": "all_media",
            "already_missing": (
                not upload_deleted
                and not output_deleted
            ),
        },
    )

    job.media_deleted_at = deletion_time
    job.media_expires_at = None

    result = dict(job.result or {})
    result["media_available"] = False
    result["media_deleted_at"] = deletion_time.isoformat()
    job.result = result

    db.add(audit)
    return audit


def cleanup_expired_media(
    db: Session,
    *,
    now: datetime | None = None,
    batch_size: int = RETENTION_CLEANUP_BATCH_SIZE,
) -> list[str]:
    cleanup_time = now or utc_now()

    jobs = list(
        db.scalars(
            select(VideoJob)
            .where(
                VideoJob.status.in_(
                    list(TERMINAL_JOB_STATUSES)
                ),
                VideoJob.media_deleted_at.is_(None),
                or_(
                    VideoJob.media_expires_at
                    <= cleanup_time,
                    VideoJob.media_expires_at.is_(None),
                ),
            )
            .order_by(VideoJob.updated_at.asc())
            .limit(max(1, batch_size))
            .with_for_update(skip_locked=True)
        )
    )

    deleted_job_ids = []

    for job in jobs:
        # Old rows may not have an expiration value. Give them a
        # deterministic retention window based on their last update.
        if job.media_expires_at is None:
            inferred_expiration = (
                job.updated_at
                + timedelta(
                    hours=(
                        FAILED_MEDIA_RETENTION_HOURS
                        if job.status == JobStatus.FAILED
                        else OUTPUT_RETENTION_HOURS
                    )
                )
            )

            if inferred_expiration > cleanup_time:
                job.media_expires_at = inferred_expiration
                continue

        delete_all_media_for_job(
            db,
            job,
            reason="retention_expired",
            requested_by="system",
            now=cleanup_time,
        )

        deleted_job_ids.append(job.id)

    return deleted_job_ids