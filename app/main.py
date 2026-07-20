import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.avatar.capabilities import (
    get_language_capability,
)
from app.database import (
    Base,
    engine,
    get_db,
)
from app.director.hf_video_director import (
    generate_director_video,
)
from app.geo_router import resolve_sign_route
from app.models import JobStatus, VideoJob
from app.schemas import (
    JobCreatedResponse,
    JobStatusResponse,
)
from app.sign_language_config import (
    get_always_available_lsa,
    list_countries,
)
from app.tasks import process_video_assets_task
from app.media_validation import (
    MediaValidationError,
    validate_media,
    sanitize_media,
)
from sqlalchemy import select
from app.auth import (
    ArtifactAccess,
    AuthenticatedPrincipal,
    create_playback_token,
    get_artifact_access,
    get_current_principal,
)
from fastapi.responses import FileResponse
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from app.config import PUBLIC_BASE_URL


logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# Runtime paths
# ------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

OUTPUT_DIR = PROJECT_ROOT / "outputs"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
TEMP_DIR = PROJECT_ROOT / "temp"


# ------------------------------------------------------------
# Upload configuration
# ------------------------------------------------------------

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
    """Raised when an upload exceeds MAX_UPLOAD_BYTES."""


# ------------------------------------------------------------
# Request models
# ------------------------------------------------------------

class DirectorRequest(BaseModel):
    prompt: str
    language: str = "french"


# ------------------------------------------------------------
# Runtime initialization
# ------------------------------------------------------------

def create_runtime_directories() -> None:
    for directory in (
        OUTPUT_DIR,
        UPLOAD_DIR,
        TEMP_DIR,
    ):
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )


# StaticFiles requires the directory to exist when mounted.
create_runtime_directories()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_runtime_directories()

    # Temporary table creation until Alembic migrations
    # are introduced.
    Base.metadata.create_all(
        bind=engine
    )

    yield


app = FastAPI(
    title=(
        "CYRKIL Option C - "
        "Geo Adaptive Sign Video"
    ),
    lifespan=lifespan,
)


# ------------------------------------------------------------
# Upload helpers
# ------------------------------------------------------------

def save_uploaded_file(
    source,
    destination: Path,
    max_bytes: int,
) -> int:
    """
    Save an uploaded file in chunks while enforcing a maximum
    byte size.

    The partial file is removed if validation or writing fails.
    """

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    total_bytes = 0

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
                    raise UploadTooLargeError(
                        "The uploaded file exceeds "
                        f"{max_bytes} bytes."
                    )

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

    return total_bytes


def create_error_reference() -> str:
    return str(uuid.uuid4())


# ------------------------------------------------------------
# Health
# ------------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "healthy",
    }


# ------------------------------------------------------------
# Job status
# ------------------------------------------------------------

@app.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
)
def get_video_job(
    job_id: str,
    principal: AuthenticatedPrincipal = Depends(
        get_current_principal
    ),
    db: Session = Depends(get_db),
):
    job = db.scalar(
        select(VideoJob).where(
            VideoJob.id == job_id,
            VideoJob.owner_id
            == principal.user_id,
            VideoJob.tenant_id
            == principal.tenant_id,
        )
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "JOB_NOT_FOUND",
                "message": "Job not found.",
            },
        )

    response = (
        JobStatusResponse
        .model_validate(job)
        .model_dump()
    )

    if (
        job.status == JobStatus.COMPLETED
        and job.result is not None
    ):
        token_seconds = int(
            os.getenv(
                "PLAYBACK_TOKEN_SECONDS",
                "600",
            )
        )

        token_seconds = max(
            60,
            min(token_seconds, 3600),
        )

        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(
                seconds=token_seconds
            )
        )

        playback_token = (
            create_playback_token(
                job_id=job.id,
                expires_at_timestamp=int(
                    expires_at.timestamp()
                ),
            )
        )

        player_url = (
            f"{PUBLIC_BASE_URL}/outputs/"
            f"{job.id}/player.html"
            f"?token={playback_token}"
        )

        result = dict(
            response["result"] or {}
        )

        result["player_url"] = player_url
        result["playback_expires_at"] = (
            expires_at.isoformat()
        )

        result["iframe"] = (
            f'<iframe src="{player_url}" '
            'width="100%" height="650" '
            'allow="fullscreen" '
            'referrerpolicy="no-referrer">'
            "</iframe>"
        )

        response["result"] = result

    return response

@app.get(
    "/outputs/{job_id}/{artifact_path:path}",
    response_class=FileResponse,
)
@app.head(
    "/outputs/{job_id}/{artifact_path:path}",
    include_in_schema=False,
)
def download_output_artifact(
    job_id: str,
    artifact_path: str,
    access: ArtifactAccess = Depends(
        get_artifact_access
    ),
    db: Session = Depends(get_db),
):
    """
    Return a generated artifact to:

    - The user who owns the job.
    - An authenticated internal worker.

    Missing and unauthorized artifacts both return 404.
    """

    conditions = [
        VideoJob.id == job_id,
    ]

    if access.playback_job_id is not None:
        if access.playback_job_id != job_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "ARTIFACT_NOT_FOUND",
                    "message": "Artifact not found.",
                },
            )

    elif not access.is_internal_worker:
        principal = access.principal

        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "AUTHENTICATION_REQUIRED",
                    "message": (
                        "A valid credential is required."
                    ),
                },
            )

        conditions.extend(
            [
                VideoJob.owner_id
                == principal.user_id,
                VideoJob.tenant_id
                == principal.tenant_id,
            ]
        )

    job = db.scalar(
        select(VideoJob).where(
            *conditions
        )
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ARTIFACT_NOT_FOUND",
                "message": "Artifact not found.",
            },
        )

    normalized_artifact_path = (
        artifact_path.strip().lstrip("/")
    )

    if not normalized_artifact_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ARTIFACT_NOT_FOUND",
                "message": "Artifact not found.",
            },
        )

    job_output_directory = (
        OUTPUT_DIR / job_id
    ).resolve()

    requested_path = (
        job_output_directory
        / normalized_artifact_path
    ).resolve()

    # Prevent ../ traversal and symbolic-link escapes.
    if not requested_path.is_relative_to(
        job_output_directory
    ):
        logger.warning(
            "Blocked artifact path traversal. "
            "job_id=%s internal_worker=%s",
            job_id,
            access.is_internal_worker,
        )

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ARTIFACT_NOT_FOUND",
                "message": "Artifact not found.",
            },
        )

    if (
        not requested_path.is_file()
        or requested_path.is_symlink()
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ARTIFACT_NOT_FOUND",
                "message": "Artifact not found.",
            },
        )

    # No filename argument: HTML must render inline for Playwright.
    return FileResponse(
        path=requested_path,
    )

# ------------------------------------------------------------
# Avatar capabilities
# ------------------------------------------------------------

@app.get(
    "/avatar/capabilities/"
    "{provider_name}/{language}"
)
def avatar_capability(
    provider_name: str,
    language: str,
):
    try:
        return get_language_capability(
            provider_name,
            language,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_CAPABILITY_REQUEST",
                "message": str(exc),
            },
        ) from exc

    except Exception:
        error_id = create_error_reference()

        logger.exception(
            "Capability lookup failed. "
            "provider=%s language=%s error_id=%s",
            provider_name,
            language,
            error_id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "CAPABILITY_LOOKUP_FAILED",
                "message": (
                    "The capability could not be checked."
                ),
                "reference": error_id,
            },
        )


# ------------------------------------------------------------
# Sign-language configuration
# ------------------------------------------------------------

@app.get("/sign-languages")
def sign_languages():
    return {
        "countries": list_countries(),
        "always_available": (
            get_always_available_lsa()
        ),
    }


@app.get("/sign-route")
def sign_route(
    country_code: Optional[str] = None,
    manual_sign_language: Optional[str] = None,
    browser_language: Optional[str] = None,
    ip_geolocation_consent: bool = False,
):
    try:
        return resolve_sign_route(
            country_code=country_code,
            manual_sign_language=(
                manual_sign_language
            ),
            browser_language=browser_language,
            ip_geolocation_consent=(
                ip_geolocation_consent
            ),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_SIGN_ROUTE",
                "message": str(exc),
            },
        ) from exc

    except Exception:
        error_id = create_error_reference()

        logger.exception(
            "Sign-route resolution failed. "
            "error_id=%s",
            error_id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "SIGN_ROUTE_FAILED",
                "message": (
                    "The sign-language route could "
                    "not be resolved."
                ),
                "reference": error_id,
            },
        )


# ------------------------------------------------------------
# Asynchronous video-assets processing
# ------------------------------------------------------------

@app.post(
    "/process-video-assets",
    response_model=JobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_video_assets(
    video: UploadFile = File(...),
    languages: str = Form(
        "french,arabic,german,english,greek"
    ),
    sign_languages: str = Form(
        "lsf,lsa,dgs,bsl,gsl"
    ),
    manual_text: Optional[str] = Form(None),
    avatar_provider_name: str = Form(
        "cwasa_multilang"
    ),
    principal: AuthenticatedPrincipal = Depends(
        get_current_principal
    ),
    db: Session = Depends(get_db),
):
    extension = Path(
        video.filename or ""
    ).suffix.lower()

    declared_content_type = video.content_type

    # ---------------------------------------------------------
    # Extension validation
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # Request parameter validation
    # ---------------------------------------------------------

    requested_languages = [
        value.strip().lower()
        for value in languages.split(",")
        if value.strip()
    ]

    requested_sign_languages = [
        value.strip().lower()
        for value in sign_languages.split(",")
        if value.strip()
    ]

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

    has_valid_manual_text = bool(
        clean_manual_text
        and clean_manual_text.lower() != "string"
    )

    # ---------------------------------------------------------
    # Server-generated storage path
    # ---------------------------------------------------------

    job_id = str(uuid.uuid4())

    input_path = (
        UPLOAD_DIR
        / job_id
        / f"original{extension}"
    )

    # ---------------------------------------------------------
    # Size-limited upload
    # ---------------------------------------------------------

    try:
        uploaded_bytes = await run_in_threadpool(
            save_uploaded_file,
            video.file,
            input_path,
            MAX_UPLOAD_BYTES,
        )

    except UploadTooLargeError as exc:
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
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail={
                "code": "EMPTY_UPLOAD",
                "message": str(exc),
            },
        ) from exc

    except OSError:
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
        )

    finally:
        await video.close()

    # ---------------------------------------------------------
    # ffprobe validation
    # ---------------------------------------------------------

    try:
        # Validate the original upload first.
        await run_in_threadpool(
            validate_media,
            input_path,
            extension,
            declared_content_type,
            not has_valid_manual_text,
        )

        # Remove metadata, chapters and unrelated streams.
        await run_in_threadpool(
            sanitize_media,
            input_path,
        )

        # Verify that the sanitized result is still valid.
        media_metadata = await run_in_threadpool(
            validate_media,
            input_path,
            extension,
            declared_content_type,
            not has_valid_manual_text,
        )

    except MediaValidationError as exc:
        input_path.unlink(missing_ok=True)

        try:
            input_path.parent.rmdir()
        except OSError:
            pass

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        ) from exc

    except Exception:
        input_path.unlink(missing_ok=True)

        try:
            input_path.parent.rmdir()
        except OSError:
            pass

        error_id = create_error_reference()

        logger.exception(
            "Unexpected media validation failure. "
            "job_id=%s error_id=%s",
            job_id,
            error_id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "MEDIA_VALIDATION_FAILED",
                "message": (
                    "The uploaded media could not "
                    "be validated."
                ),
                "reference": error_id,
            },
        )

    # ---------------------------------------------------------
    # Persist queued job
    # ---------------------------------------------------------

    job = VideoJob(
        id=job_id,
        owner_id=principal.user_id,
        tenant_id=principal.tenant_id,
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
                clean_manual_text
                if has_valid_manual_text
                else None
            ),
            "avatar_provider_name": (
                avatar_provider_name
            ),
            "extension": extension,
            "declared_content_type": (
                declared_content_type
            ),
            "uploaded_bytes": uploaded_bytes,
            "media_metadata": media_metadata,
        },
    )

    try:
        db.add(job)
        db.commit()

    except Exception:
        db.rollback()

        input_path.unlink(
            missing_ok=True
        )

        try:
            input_path.parent.rmdir()
        except OSError:
            pass

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
        )

    # ---------------------------------------------------------
    # Submit to Celery
    # ---------------------------------------------------------

    try:
        process_video_assets_task.delay(
            job_id
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
    }

# ------------------------------------------------------------
# AI video director
# ------------------------------------------------------------

@app.post("/director/hf-video")
def director_hf_video(
    request: DirectorRequest,
    principal: AuthenticatedPrincipal = Depends(
        get_current_principal
    ),
):
    try:
        result = generate_director_video(
            request.prompt,
            request.language,
        )

        return {
            "status": "success",
            **result,
            "next_step": (
                "Upload this MP4 to "
                "/process-video-assets"
            ),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail={
                "code": "INVALID_DIRECTOR_REQUEST",
                "message": str(exc),
            },
        ) from exc

    except Exception:
        error_id = create_error_reference()

        logger.exception(
            "AI video director failed. "
            "user_id=%s tenant_id=%s "
            "error_id=%s",
            principal.user_id,
            principal.tenant_id,
            error_id,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "DIRECTOR_GENERATION_FAILED",
                "message": (
                    "The AI video could not "
                    "be generated."
                ),
                "reference": error_id,
            },
        )