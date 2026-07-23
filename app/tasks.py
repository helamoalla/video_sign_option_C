import logging
import uuid

from app.celery_app import celery_app
from app.database import SessionLocal
from app.media_retention import (
    cleanup_expired_media,
    delete_upload_for_job,
    get_media_expiration,
)
from app.models import JobStatus, VideoJob
from app.pipelines.video_assets import run_video_assets_pipeline


logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.test_task")
def test_task(value: str) -> dict:
    return {
        "status": "completed",
        "value": value,
    }


@celery_app.task(name="app.tasks.process_video")
def process_video_task(job_id: str):
    return {
        "job_id": job_id,
        "status": "received",
    }


def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    stage: str | None = None,
    progress: int | None = None,
    result: dict | None = None,
    error: str | None = None,
    media_expires_at=None,
) -> None:
    with SessionLocal() as db:
        job = db.get(VideoJob, job_id)

        if job is None:
            raise RuntimeError(
                f"Job not found: {job_id}"
            )

        if status is not None:
            job.status = status

        if stage is not None:
            job.stage = stage

        if progress is not None:
            job.progress = progress

        if result is not None:
            job.result = result

        if error is not None:
            job.error = error

        if media_expires_at is not None:
            job.media_expires_at = media_expires_at

        db.commit()


def cleanup_terminal_upload(
    job_id: str,
    *,
    reason: str,
) -> None:
    """
    Remove the original upload after the pipeline no longer needs it.

    Cleanup failure is logged but does not change a successfully
    completed processing result into a failed job.
    """

    try:
        with SessionLocal() as db:
            job = db.get(VideoJob, job_id)

            if job is None:
                logger.warning(
                    "Upload cleanup skipped; job was not found. "
                    "job_id=%s",
                    job_id,
                )
                return

            delete_upload_for_job(
                db,
                job,
                reason=reason,
                requested_by="system",
            )

            db.commit()

    except Exception:
        logger.exception(
            "Terminal upload cleanup failed. "
            "job_id=%s reason=%s",
            job_id,
            reason,
        )


@celery_app.task(
    bind=True,
    name="app.tasks.process_video_assets",
)
def process_video_assets_task(
    self,
    job_id: str,
):
    with SessionLocal() as db:
        job = db.get(VideoJob, job_id)

        if job is None:
            raise RuntimeError(
                f"Job not found: {job_id}"
            )

        input_path = job.input_path
        parameters = job.parameters

    update_job(
        job_id,
        status=JobStatus.PROCESSING,
        stage="starting",
        progress=1,
    )

    def report_progress(
        stage: str,
        progress: int,
    ) -> None:
        update_job(
            job_id,
            status=JobStatus.PROCESSING,
            stage=stage,
            progress=progress,
        )

    try:
        result = run_video_assets_pipeline(
            job_id=job_id,
            input_path=input_path,
            parameters=parameters,
            update_progress=report_progress,
        )

        result = dict(result or {})
        result["media_available"] = True

        expiration = get_media_expiration(
            JobStatus.COMPLETED
        )

        result["media_expires_at"] = (
            expiration.isoformat()
        )

        update_job(
            job_id,
            status=JobStatus.COMPLETED,
            stage="completed",
            progress=100,
            result=result,
            media_expires_at=expiration,
        )

        cleanup_terminal_upload(
            job_id,
            reason=(
                "processing_completed_upload_cleanup"
            ),
        )

        return result

    except Exception:
        error_id = str(uuid.uuid4())
        expiration = get_media_expiration(
            JobStatus.FAILED
        )

        logger.exception(
            "Video processing failed. "
            "job_id=%s error_id=%s",
            job_id,
            error_id,
        )

        update_job(
            job_id,
            status=JobStatus.FAILED,
            stage="failed",
            error=(
                "Video processing failed. "
                f"Reference: {error_id}"
            ),
            media_expires_at=expiration,
        )

        cleanup_terminal_upload(
            job_id,
            reason=(
                "processing_failed_upload_cleanup"
            ),
        )

        raise


@celery_app.task(
    name="app.tasks.cleanup_expired_media",
)
def cleanup_expired_media_task() -> dict:
    with SessionLocal() as db:
        try:
            deleted_job_ids = cleanup_expired_media(
                db
            )
            db.commit()

        except Exception:
            db.rollback()
            logger.exception(
                "Scheduled media-retention cleanup failed."
            )
            raise

    return {
        "deleted_count": len(deleted_job_ids),
        "deleted_job_ids": deleted_job_ids,
    }