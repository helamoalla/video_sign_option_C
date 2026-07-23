import logging
import uuid
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.database import SessionLocal
from app.media_retention import (
    cleanup_expired_media,
    delete_all_media_for_job,
    delete_upload_for_job,
    get_media_expiration,
)
from app.models import JobStatus, VideoJob
from app.pipelines.video_assets import (
    run_video_assets_pipeline,
)


logger = logging.getLogger(__name__)

UNSET = object()

RETRYABLE_EXCEPTION_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ConnectionError",
    "ConnectTimeout",
    "GatewayTimeout",
    "InternalServerError",
    "NameResolutionError",
    "PoolTimeout",
    "RateLimitError",
    "ReadTimeout",
    "RemoteProtocolError",
    "ServiceUnavailableError",
    "TimeoutError",
}

RETRYABLE_HTTP_STATUSES = {
    408,
    409,
    425,
    429,
    500,
    502,
    503,
    504,
}


class JobCancellationRequested(Exception):
    """Raised when cancellation was requested for a job."""


@celery_app.task(
    name="app.tasks.test_task"
)
def test_task(value: str) -> dict:
    return {
        "status": "completed",
        "value": value,
    }


@celery_app.task(
    name="app.tasks.process_video"
)
def process_video_task(job_id: str):
    return {
        "job_id": job_id,
        "status": "received",
    }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_error_code(
    exception: BaseException,
) -> str:
    name = exception.__class__.__name__

    normalized = "".join(
        character
        if character.isalnum()
        else "_"
        for character in name
    ).strip("_")

    return (
        normalized.upper()[:80]
        or "PROCESSING_ERROR"
    )


def iter_exception_chain(
    exception: BaseException,
):
    current: BaseException | None = exception
    visited: set[int] = set()

    while (
        current is not None
        and id(current) not in visited
    ):
        visited.add(id(current))
        yield current

        current = (
            current.__cause__
            or current.__context__
        )


def get_exception_http_status(
    exception: BaseException,
) -> int | None:
    status_code = getattr(
        exception,
        "status_code",
        None,
    )

    if isinstance(status_code, int):
        return status_code

    response = getattr(
        exception,
        "response",
        None,
    )

    response_status = getattr(
        response,
        "status_code",
        None,
    )

    if isinstance(response_status, int):
        return response_status

    return None


def is_retryable_exception(
    exception: BaseException,
) -> bool:
    """
    Return True only for errors that are likely temporary.

    Validation errors, missing assets and unsupported languages are
    not retryable.
    """

    for chained_exception in iter_exception_chain(
        exception
    ):
        if isinstance(
            chained_exception,
            (TimeoutError, ConnectionError),
        ):
            return True

        if (
            chained_exception.__class__.__name__
            in RETRYABLE_EXCEPTION_NAMES
        ):
            return True

        http_status = get_exception_http_status(
            chained_exception
        )

        if http_status in RETRYABLE_HTTP_STATUSES:
            return True

    return False


def calculate_retry_delay(
    attempt_count: int,
) -> int:
    """
    Return 30, 60, 120... seconds, capped at five minutes.
    """

    exponent = max(
        0,
        attempt_count - 1,
    )

    return min(
        30 * (2 ** exponent),
        300,
    )


def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    stage: str | None = None,
    progress: int | None = None,
    result=UNSET,
    error=UNSET,
    media_expires_at=UNSET,
    last_error_code=UNSET,
    retry_requested_at=UNSET,
    dead_lettered_at=UNSET,
) -> None:
    with SessionLocal() as db:
        job = db.get(
            VideoJob,
            job_id,
        )

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

        if result is not UNSET:
            job.result = result

        if error is not UNSET:
            job.error = error

        if media_expires_at is not UNSET:
            job.media_expires_at = (
                media_expires_at
            )

        if last_error_code is not UNSET:
            job.last_error_code = (
                last_error_code
            )

        if retry_requested_at is not UNSET:
            job.retry_requested_at = (
                retry_requested_at
            )

        if dead_lettered_at is not UNSET:
            job.dead_lettered_at = (
                dead_lettered_at
            )

        db.commit()


def start_job_attempt(
    job_id: str,
) -> tuple[str, dict, int, int]:
    with SessionLocal() as db:
        job = db.get(
            VideoJob,
            job_id,
            with_for_update=True,
        )

        if job is None:
            raise RuntimeError(
                f"Job not found: {job_id}"
            )

        if job.cancel_requested_at is not None:
            raise JobCancellationRequested(
                "Cancellation was requested for job "
                f"{job_id}."
            )

        if job.status in {
            JobStatus.COMPLETED,
            JobStatus.CANCELLED,
        }:
            raise RuntimeError(
                "A terminal job cannot start another "
                f"worker attempt: {job_id}"
            )

        job.attempt_count += 1
        job.status = JobStatus.PROCESSING
        job.stage = "starting"
        job.progress = max(
            1,
            job.progress,
        )
        job.error = None
        job.last_error_code = None
        job.retry_requested_at = None

        input_path = job.input_path
        parameters = dict(
            job.parameters
        )
        attempt_count = job.attempt_count
        max_attempts = max(
            1,
            job.max_attempts,
        )

        db.commit()

    return (
        input_path,
        parameters,
        attempt_count,
        max_attempts,
    )


def raise_if_cancellation_requested(
    job_id: str,
) -> None:
    """
    Read the latest job state from Postgres.

    A new database session is used so cancellation changes made by
    the API are visible to the worker.
    """

    with SessionLocal() as db:
        job = db.get(
            VideoJob,
            job_id,
        )

        if job is None:
            raise RuntimeError(
                f"Job not found: {job_id}"
            )

        if job.cancel_requested_at is not None:
            raise JobCancellationRequested(
                "Cancellation was requested for job "
                f"{job_id}."
            )


def finalize_cancelled_job(
    job_id: str,
) -> dict:
    cancellation_time = utc_now()

    with SessionLocal() as db:
        job = db.get(
            VideoJob,
            job_id,
            with_for_update=True,
        )

        if job is None:
            raise RuntimeError(
                f"Job not found: {job_id}"
            )

        job.status = JobStatus.CANCELLED
        job.stage = "cancelled"
        job.error = None

        job.cancel_requested_at = (
            job.cancel_requested_at
            or cancellation_time
        )

        job.cancelled_at = (
            cancellation_time
        )

        job.last_error_code = None
        job.retry_requested_at = None
        job.dead_lettered_at = None

        delete_all_media_for_job(
            db,
            job,
            reason="processing_cancelled",
            requested_by="system",
            now=cancellation_time,
        )

        db.commit()

    logger.info(
        "Video processing cancelled. "
        "job_id=%s",
        job_id,
    )

    return {
        "job_id": job_id,
        "status": JobStatus.CANCELLED.value,
    }


def cleanup_terminal_upload(
    job_id: str,
    *,
    reason: str,
) -> None:
    """
    Delete the upload only when no retry will occur.
    """

    try:
        with SessionLocal() as db:
            job = db.get(
                VideoJob,
                job_id,
            )

            if job is None:
                logger.warning(
                    "Upload cleanup skipped; "
                    "job was not found. job_id=%s",
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
    try:
        (
            input_path,
            parameters,
            attempt_count,
            max_attempts,
        ) = start_job_attempt(
            job_id
        )

    except JobCancellationRequested:
        return finalize_cancelled_job(
            job_id
        )

    logger.info(
        "Video processing attempt started. "
        "job_id=%s attempt=%s max_attempts=%s",
        job_id,
        attempt_count,
        max_attempts,
    )

    def report_progress(
        stage: str,
        progress: int,
    ) -> None:
        # Cancellation checkpoint during the pipeline.
        raise_if_cancellation_requested(
            job_id
        )

        update_job(
            job_id,
            status=JobStatus.PROCESSING,
            stage=stage,
            progress=progress,
        )

    try:
        # Check before starting expensive processing.
        raise_if_cancellation_requested(
            job_id
        )

        result = run_video_assets_pipeline(
            job_id=job_id,
            input_path=input_path,
            parameters=parameters,
            update_progress=report_progress,
        )

        # Check again after the pipeline. This prevents a cancellation
        # requested during the final long operation from being replaced
        # with COMPLETED.
        raise_if_cancellation_requested(
            job_id
        )

        result = dict(
            result or {}
        )

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
            error=None,
            media_expires_at=expiration,
            last_error_code=None,
            retry_requested_at=None,
            dead_lettered_at=None,
        )

        cleanup_terminal_upload(
            job_id,
            reason=(
                "processing_completed_upload_cleanup"
            ),
        )

        return result

    except JobCancellationRequested:
        return finalize_cancelled_job(
            job_id
        )

    except Exception as exception:
        error_id = str(
            uuid.uuid4()
        )

        error_code = create_error_code(
            exception
        )

        retryable = is_retryable_exception(
            exception
        )

        attempts_remaining = (
            attempt_count < max_attempts
        )

        logger.exception(
            "Video processing attempt failed. "
            "job_id=%s error_id=%s error_code=%s "
            "attempt=%s max_attempts=%s retryable=%s",
            job_id,
            error_id,
            error_code,
            attempt_count,
            max_attempts,
            retryable,
        )

        if (
            retryable
            and attempts_remaining
        ):
            # A cancellation could be requested at the same moment
            # that the processing error occurs. Do not schedule another
            # attempt in that case.
            try:
                raise_if_cancellation_requested(
                    job_id
                )

            except JobCancellationRequested:
                return finalize_cancelled_job(
                    job_id
                )

            retry_delay = (
                calculate_retry_delay(
                    attempt_count
                )
            )

            update_job(
                job_id,
                status=JobStatus.RETRYING,
                stage="retry_wait",
                error=(
                    "A temporary processing failure "
                    "occurred. Retry scheduled. "
                    f"Reference: {error_id}"
                ),
                last_error_code=error_code,
                retry_requested_at=utc_now(),
            )

            logger.warning(
                "Video processing retry scheduled. "
                "job_id=%s next_attempt=%s "
                "countdown=%s",
                job_id,
                attempt_count + 1,
                retry_delay,
            )

            raise self.retry(
                exc=exception,
                countdown=retry_delay,
                max_retries=(
                    max_attempts - 1
                ),
            )

        expiration = get_media_expiration(
            JobStatus.FAILED
        )

        exhausted_retryable_failure = (
            retryable
            and not attempts_remaining
        )

        update_job(
            job_id,
            status=JobStatus.FAILED,
            stage=(
                "dead_lettered"
                if exhausted_retryable_failure
                else "failed"
            ),
            error=(
                "Video processing failed. "
                f"Reference: {error_id}"
            ),
            media_expires_at=expiration,
            last_error_code=error_code,
            dead_lettered_at=(
                utc_now()
                if exhausted_retryable_failure
                else None
            ),
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
            deleted_job_ids = (
                cleanup_expired_media(
                    db
                )
            )

            db.commit()

        except Exception:
            db.rollback()

            logger.exception(
                "Scheduled media-retention "
                "cleanup failed."
            )

            raise

    return {
        "deleted_count": len(
            deleted_job_ids
        ),
        "deleted_job_ids": (
            deleted_job_ids
        ),
    }