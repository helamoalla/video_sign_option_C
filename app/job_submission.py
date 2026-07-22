import hashlib
import json
import logging
import os
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AuthenticatedPrincipal
from app.job_quotas import (
    JobQuotaExceededError,
    acquire_job_submission_lock,
    enforce_job_quota,
)
from app.media_validation import (
    MediaValidationError,
    sanitize_media,
    validate_media,
)
from app.models import JobStatus, VideoJob
from app.tasks import process_video_assets_task


logger = logging.getLogger(__name__)


MAX_UPLOAD_BYTES = int(
    os.getenv(
        "MAX_UPLOAD_BYTES",
        str(100 * 1024 * 1024),
    )
)

UPLOAD_CHUNK_SIZE = 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
}


class UploadTooLargeError(Exception):
    pass


def create_error_reference() -> str:
    return str(uuid.uuid4())


def delete_job_upload(
    input_path: Path,
) -> None:
    shutil.rmtree(
        input_path.parent,
        ignore_errors=True,
    )


def save_uploaded_file(
    source,
    destination: Path,
    max_bytes: int,
) -> tuple[int, str]:
    """
    Save an upload in chunks and calculate its SHA-256 hash in
    the same pass.
    """

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    total_bytes = 0
    digest = hashlib.sha256()

    try:
        with destination.open("wb") as output:
            while True:
                chunk = source.read(
                    UPLOAD_CHUNK_SIZE
                )

                if not chunk:
                    break

                total_bytes += len(chunk)

                if total_bytes > max_bytes:
                    raise UploadTooLargeError

                digest.update(chunk)
                output.write(chunk)

    except Exception:
        destination.unlink(
            missing_ok=True
        )
        raise

    if total_bytes == 0:
        destination.unlink(
            missing_ok=True
        )

        raise ValueError(
            "The uploaded file is empty."
        )

    return total_bytes, digest.hexdigest()


def normalize_csv_values(
    value: str,
) -> list[str]:
    return [
        item.strip().lower()
        for item in value.split(",")
        if item.strip()
    ]


def resolve_idempotency_key(
    supplied_key: str | None,
) -> str:
    normalized_key = (
        supplied_key.strip()
        if supplied_key
        else ""
    )

    if not normalized_key:
        return str(uuid.uuid4())

    if not 8 <= len(normalized_key) <= 128:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail={
                "code": "INVALID_IDEMPOTENCY_KEY",
                "message": (
                    "Idempotency-Key must contain "
                    "between 8 and 128 characters."
                ),
            },
        )

    return normalized_key


def calculate_request_fingerprint(
    *,
    file_sha256: str,
    extension: str,
    languages: list[str],
    sign_languages: list[str],
    manual_text: str | None,
    avatar_provider_name: str,
) -> str:
    payload = {
        "file_sha256": file_sha256,
        "extension": extension,
        "languages": languages,
        "sign_languages": sign_languages,
        "manual_text": manual_text,
        "avatar_provider_name": (
            avatar_provider_name
            .strip()
            .lower()
        ),
    }

    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        serialized
    ).hexdigest()


async def submit_video_assets_job(
    *,
    video: UploadFile,
    languages: str,
    sign_languages: str,
    manual_text: str | None,
    avatar_provider_name: str,
    idempotency_key: str | None,
    principal: AuthenticatedPrincipal,
    db: Session,
    upload_dir: Path,
) -> dict:
    extension = Path(
        video.filename or ""
    ).suffix.lower()

    declared_content_type = video.content_type

    try:
        effective_idempotency_key = (
            resolve_idempotency_key(
                idempotency_key
            )
        )

    except HTTPException:
        await video.close()
        raise

    if extension not in ALLOWED_EXTENSIONS:
        await video.close()

        raise HTTPException(
            status_code=(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
            ),
            detail={
                "code": "UNSUPPORTED_EXTENSION",
                "message": (
                    "Unsupported media file extension."
                ),
                "extension": extension,
                "allowed_extensions": sorted(
                    ALLOWED_EXTENSIONS
                ),
            },
        )

    requested_languages = normalize_csv_values(
        languages
    )
    requested_sign_languages = (
        normalize_csv_values(
            sign_languages
        )
    )

    if not requested_languages:
        await video.close()

        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail={
                "code": "MISSING_LANGUAGES",
                "message": (
                    "At least one subtitle language "
                    "must be requested."
                ),
            },
        )

    if not requested_sign_languages:
        await video.close()

        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail={
                "code": "MISSING_SIGN_LANGUAGES",
                "message": (
                    "At least one sign language "
                    "must be requested."
                ),
            },
        )

    clean_manual_text = (
        manual_text.strip()
        if manual_text
        else ""
    )
    has_manual_text = bool(
        clean_manual_text
        and clean_manual_text.lower()
        != "string"
    )
    effective_manual_text = (
        clean_manual_text
        if has_manual_text
        else None
    )

    job_id = str(uuid.uuid4())
    input_path = (
        upload_dir
        / job_id
        / f"original{extension}"
    )

    try:
        (
            uploaded_bytes,
            uploaded_file_sha256,
        ) = await run_in_threadpool(
            save_uploaded_file,
            video.file,
            input_path,
            MAX_UPLOAD_BYTES,
        )

    except UploadTooLargeError as exc:
        delete_job_upload(input_path)

        raise HTTPException(
            status_code=(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            ),
            detail={
                "code": "UPLOAD_TOO_LARGE",
                "message": (
                    "The uploaded media exceeds "
                    "the maximum allowed size."
                ),
                "max_bytes": MAX_UPLOAD_BYTES,
            },
        ) from exc

    except ValueError as exc:
        delete_job_upload(input_path)

        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail={
                "code": "EMPTY_UPLOAD",
                "message": str(exc),
            },
        ) from exc

    except OSError as exc:
        delete_job_upload(input_path)
        error_id = create_error_reference()

        logger.exception(
            "Upload storage failed. "
            "job_id=%s error_id=%s",
            job_id,
            error_id,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail={
                "code": "UPLOAD_STORAGE_FAILED",
                "message": (
                    "The uploaded media could not "
                    "be stored."
                ),
                "reference": error_id,
            },
        ) from exc

    finally:
        await video.close()

    try:
        await run_in_threadpool(
            validate_media,
            input_path,
            extension,
            declared_content_type,
            not has_manual_text,
        )

        await run_in_threadpool(
            sanitize_media,
            input_path,
        )

        media_metadata = await run_in_threadpool(
            validate_media,
            input_path,
            extension,
            declared_content_type,
            not has_manual_text,
        )

    except MediaValidationError as exc:
        delete_job_upload(input_path)

        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        ) from exc

    except Exception as exc:
        delete_job_upload(input_path)
        error_id = create_error_reference()

        logger.exception(
            "Unexpected media validation failure. "
            "job_id=%s error_id=%s",
            job_id,
            error_id,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail={
                "code": "MEDIA_VALIDATION_FAILED",
                "message": (
                    "The uploaded media could not "
                    "be validated."
                ),
                "reference": error_id,
            },
        ) from exc

    request_fingerprint = (
        calculate_request_fingerprint(
            file_sha256=uploaded_file_sha256,
            extension=extension,
            languages=requested_languages,
            sign_languages=(
                requested_sign_languages
            ),
            manual_text=effective_manual_text,
            avatar_provider_name=(
                avatar_provider_name
            ),
        )
    )

    try:
        acquire_job_submission_lock(
            db,
            principal,
        )

        existing_job = db.scalar(
            select(VideoJob).where(
                VideoJob.owner_id
                == principal.user_id,
                VideoJob.tenant_id
                == principal.tenant_id,
                VideoJob.idempotency_key
                == effective_idempotency_key,
            )
        )

        if existing_job is not None:
            db.rollback()
            delete_job_upload(input_path)

            if (
                existing_job.request_fingerprint
                != request_fingerprint
            ):
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "IDEMPOTENCY_KEY_CONFLICT"
                        ),
                        "message": (
                            "This Idempotency-Key was "
                            "already used for a different "
                            "request."
                        ),
                    },
                )

            return {
                "job_id": existing_job.id,
                "status": existing_job.status,
                "status_url": (
                    f"/jobs/{existing_job.id}"
                ),
                "idempotency_key": (
                    effective_idempotency_key
                ),
                "idempotent_replay": True,
            }

        existing_fingerprint_job = db.scalar(
            select(VideoJob)
            .where(
                VideoJob.owner_id
                == principal.user_id,
                VideoJob.tenant_id
                == principal.tenant_id,
                VideoJob.request_fingerprint
                == request_fingerprint,
                VideoJob.status.in_(
                    [
                        JobStatus.QUEUED,
                        JobStatus.PROCESSING,
                        JobStatus.COMPLETED,
                    ]
                ),
            )
            .order_by(
                VideoJob.created_at.desc()
            )
        )

        if existing_fingerprint_job is not None:
            db.rollback()
            delete_job_upload(input_path)

            return {
                "job_id": (
                    existing_fingerprint_job.id
                ),
                "status": (
                    existing_fingerprint_job.status
                ),
                "status_url": (
                    f"/jobs/"
                    f"{existing_fingerprint_job.id}"
                ),
                "idempotency_key": (
                    existing_fingerprint_job
                    .idempotency_key
                ),
                "idempotent_replay": True,
            }
        quota_usage = enforce_job_quota(
            db,
            principal,
            acquire_lock=False,
        )

    except JobQuotaExceededError as exc:
        db.rollback()
        delete_job_upload(input_path)

        raise HTTPException(
            status_code=(
                status.HTTP_429_TOO_MANY_REQUESTS
            ),
            detail={
                "code": exc.code,
                "message": exc.message,
                "limit": exc.limit,
            },
            headers={
                "Retry-After": "60",
            },
        ) from exc

    except HTTPException:
        raise

    except Exception as exc:
        db.rollback()
        delete_job_upload(input_path)
        error_id = create_error_reference()

        logger.exception(
            "Submission validation failed. "
            "job_id=%s error_id=%s",
            job_id,
            error_id,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail={
                "code": "JOB_SUBMISSION_FAILED",
                "message": (
                    "The processing job could not "
                    "be submitted."
                ),
                "reference": error_id,
            },
        ) from exc

    job = VideoJob(
        id=job_id,
        owner_id=principal.user_id,
        tenant_id=principal.tenant_id,
        idempotency_key=(
            effective_idempotency_key
        ),
        request_fingerprint=(
            request_fingerprint
        ),
        celery_task_id=job_id,
        status=JobStatus.QUEUED,
        stage="queued",
        progress=0,
        input_path=str(input_path),
        parameters={
            "pipeline": "video_assets",
            "languages": ",".join(
                requested_languages
            ),
            "sign_languages": ",".join(
                requested_sign_languages
            ),
            "manual_text": (
                effective_manual_text
            ),
            "avatar_provider_name": (
                avatar_provider_name
            ),
            "extension": extension,
            "declared_content_type": (
                declared_content_type
            ),
            "uploaded_bytes": uploaded_bytes,
            "uploaded_file_sha256": (
                uploaded_file_sha256
            ),
            "media_metadata": media_metadata,
            "quota_at_submission": {
                "active_jobs": (
                    quota_usage.active_jobs
                ),
                "max_active_jobs": (
                    quota_usage.max_active_jobs
                ),
                "daily_jobs": (
                    quota_usage.daily_jobs
                ),
                "max_daily_jobs": (
                    quota_usage.max_daily_jobs
                ),
            },
        },
    )

    try:
        db.add(job)
        db.commit()

    except Exception as exc:
        db.rollback()
        delete_job_upload(input_path)
        error_id = create_error_reference()

        logger.exception(
            "Job persistence failed. "
            "job_id=%s error_id=%s",
            job_id,
            error_id,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail={
                "code": "JOB_CREATION_FAILED",
                "message": (
                    "The processing job could not "
                    "be created."
                ),
                "reference": error_id,
            },
        ) from exc

    try:
        process_video_assets_task.apply_async(
            args=[job_id],
            task_id=job.celery_task_id,
        )

    except Exception as exc:
        error_id = create_error_reference()

        logger.exception(
            "Celery submission failed. "
            "job_id=%s error_id=%s",
            job_id,
            error_id,
        )

        job.status = JobStatus.FAILED
        job.stage = "queue_submission"
        job.error = (
            "The processing queue is unavailable. "
            f"Reference: {error_id}"
        )

        try:
            db.commit()
        except Exception:
            db.rollback()

            logger.exception(
                "Failed to persist queue failure. "
                "job_id=%s error_id=%s",
                job_id,
                error_id,
            )

        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail={
                "code": "QUEUE_UNAVAILABLE",
                "message": (
                    "The processing queue is unavailable."
                ),
                "reference": error_id,
            },
        ) from exc

    return {
        "job_id": job_id,
        "status": JobStatus.QUEUED,
        "status_url": f"/jobs/{job_id}",
        "idempotency_key": (
            effective_idempotency_key
        ),
        "idempotent_replay": False,
    }