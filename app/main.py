import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    status,
    Request,
)
from fastapi.responses import (
    FileResponse,
    JSONResponse,
)
from app.asset_readiness import (
    validate_sign_asset_bundle,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.media_retention import (
    ActiveJobDeletionError,
    delete_all_media_for_job,
)

from app.auth import (
    ArtifactAccess,
    AuthenticatedPrincipal,
    create_playback_token,
    get_artifact_access,
    get_current_principal,
)
from app.avatar.capabilities import get_language_capability
from app.config import PUBLIC_BASE_URL
from app.database import Base, engine, get_db
from app.director.hf_video_director import generate_director_video
from app.geo_router import resolve_sign_route
from app.job_submission import (
    submit_video_assets_job,
)
from app.models import JobStatus, VideoJob
from app.request_limits import RequestBodyLimitMiddleware
from app.schemas import (
    JobCreatedResponse,
    JobStatusResponse,
)
from app.sign_language_config import (
    get_always_available_lsa,
    list_countries,
)
from app.celery_app import celery_app

from app.job_control import (
    JobCannotBeCancelledError,
    request_job_cancellation,
)


logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# Runtime paths
# ------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

OUTPUT_DIR = PROJECT_ROOT / "outputs"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
TEMP_DIR = PROJECT_ROOT / "temp"


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

    asset_report = validate_sign_asset_bundle()

    app.state.sign_asset_readiness = (
        asset_report
    )

    if not asset_report["ready"]:
        logger.error(
            "Sign-asset readiness validation failed. "
            "code=%s problems=%s",
            asset_report["code"],
            asset_report["problems"],
        )
    else:
        logger.info(
            "Sign-asset bundle validated. "
            "version=%s",
            asset_report["bundle_version"],
        )

    # Temporary until Alembic migrations are introduced.
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

app.add_middleware(
    RequestBodyLimitMiddleware
)

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

@app.get("/ready")
def readiness(request: Request):
    report = (
        request.app.state
        .sign_asset_readiness
    )

    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if report["ready"]
            else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        content={
            "status": (
                "ready"
                if report["ready"]
                else "not_ready"
            ),
            "code": report["code"],
            "bundle_version": (
                report["bundle_version"]
            ),
            "languages": report["languages"],
            "problems": report["problems"],
        },
    )
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

    # ---------------------------------------------------------
    # Determine whether the generated media is still available
    # ---------------------------------------------------------

    now = datetime.now(timezone.utc)
    media_expires_at = job.media_expires_at

    # Defensive support for databases returning a naive datetime.
    if (
        media_expires_at is not None
        and media_expires_at.tzinfo is None
    ):
        media_expires_at = (
            media_expires_at.replace(
                tzinfo=timezone.utc
            )
        )

    media_expired = (
        media_expires_at is not None
        and media_expires_at <= now
    )

    media_available = (
        job.media_deleted_at is None
        and not media_expired
    )

    result = dict(
        response["result"] or {}
    )

    result["media_available"] = (
        media_available
    )

    result["media_expires_at"] = (
        media_expires_at.isoformat()
        if media_expires_at is not None
        else None
    )

    result["media_deleted_at"] = (
        job.media_deleted_at.isoformat()
        if job.media_deleted_at is not None
        else None
    )

    # Never return old or expired playback links.
    result.pop("player_url", None)
    result.pop("playback_expires_at", None)
    result.pop("iframe", None)

    # ---------------------------------------------------------
    # Generate playback access only for available media
    # ---------------------------------------------------------

    if (
        job.status == JobStatus.COMPLETED
        and job.result is not None
        and media_available
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

        playback_expires_at = (
            now
            + timedelta(
                seconds=token_seconds
            )
        )

        # The playback token must not outlive media retention.
        if (
            media_expires_at is not None
            and playback_expires_at
            > media_expires_at
        ):
            playback_expires_at = (
                media_expires_at
            )

        playback_token = (
            create_playback_token(
                job_id=job.id,
                expires_at_timestamp=int(
                    playback_expires_at.timestamp()
                ),
            )
        )

        player_url = (
            f"{PUBLIC_BASE_URL}/outputs/"
            f"{job.id}/player.html"
            f"?token={playback_token}"
        )

        result["player_url"] = player_url
        result["playback_expires_at"] = (
            playback_expires_at.isoformat()
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

@app.post(
    "/jobs/{job_id}/cancel",
)
def cancel_video_job(
    job_id: str,
    principal: AuthenticatedPrincipal = Depends(
        get_current_principal
    ),
    db: Session = Depends(get_db),
):
    job = db.scalar(
        select(VideoJob)
        .where(
            VideoJob.id == job_id,
            VideoJob.owner_id
            == principal.user_id,
            VideoJob.tenant_id
            == principal.tenant_id,
        )
        .with_for_update()
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "JOB_NOT_FOUND",
                "message": "Job not found.",
            },
        )

    try:
        cancellation = (
            request_job_cancellation(
                db,
                job,
                requested_by=(
                    principal.user_id
                ),
            )
        )

        db.commit()

    except JobCannotBeCancelledError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": (
                    "JOB_CANNOT_BE_CANCELLED"
                ),
                "message": str(exc),
            },
        ) from exc

    except Exception as exc:
        db.rollback()

        error_id = create_error_reference()

        logger.exception(
            "Job cancellation failed. "
            "job_id=%s error_id=%s",
            job_id,
            error_id,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail={
                "code": (
                    "JOB_CANCELLATION_FAILED"
                ),
                "message": (
                    "The cancellation request "
                    "could not be completed."
                ),
                "reference": error_id,
            },
        ) from exc

    # A queued or retrying task can be revoked safely.
    # Processing tasks stop cooperatively at their next checkpoint.
    if (
        cancellation.revoke_task
        and cancellation.celery_task_id
    ):
        try:
            celery_app.control.revoke(
                cancellation.celery_task_id,
                terminate=False,
            )

        except Exception:
            # The database cancellation remains authoritative.
            # If the task is delivered, the worker sees
            # cancel_requested_at and exits safely.
            logger.exception(
                "Celery revoke failed for cancelled job. "
                "job_id=%s task_id=%s",
                job_id,
                cancellation.celery_task_id,
            )

    return {
        "job_id": cancellation.job_id,
        "status": cancellation.status,
        "stage": cancellation.stage,
        "cancellation_pending": (
            cancellation.cancellation_pending
        ),
        "cancel_requested_at": (
            job.cancel_requested_at
        ),
        "cancelled_at": job.cancelled_at,
        "audit_id": cancellation.audit_id,
    }

@app.delete(
    "/jobs/{job_id}/media",
)
def delete_job_media(
    job_id: str,
    principal: AuthenticatedPrincipal = Depends(
        get_current_principal
    ),
    db: Session = Depends(get_db),
):
    job = db.scalar(
        select(VideoJob)
        .where(
            VideoJob.id == job_id,
            VideoJob.owner_id
            == principal.user_id,
            VideoJob.tenant_id
            == principal.tenant_id,
        )
        .with_for_update()
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "JOB_NOT_FOUND",
                "message": "Job not found.",
            },
        )

    try:
        audit = delete_all_media_for_job(
            db,
            job,
            reason="user_requested",
            requested_by=principal.user_id,
        )

        db.flush()
        db.commit()
        db.refresh(audit)

    except ActiveJobDeletionError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "JOB_STILL_ACTIVE",
                "message": (
                    "Media cannot be deleted while "
                    "the job is processing."
                ),
            },
        ) from exc

    except Exception as exc:
        db.rollback()

        error_id = create_error_reference()

        logger.exception(
            "Media deletion failed. "
            "job_id=%s error_id=%s",
            job_id,
            error_id,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail={
                "code": "MEDIA_DELETION_FAILED",
                "message": (
                    "The job media could not be deleted."
                ),
                "reference": error_id,
            },
        ) from exc

    return {
        "job_id": job.id,
        "media_available": False,
        "media_deleted_at": (
            job.media_deleted_at
        ),
        "audit_id": audit.id,
        "upload_deleted": (
            audit.upload_deleted
        ),
        "output_deleted": (
            audit.output_deleted
        ),
    }

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
        VideoJob.media_deleted_at.is_(None),
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
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    principal: AuthenticatedPrincipal = Depends(
        get_current_principal
    ),
    db: Session = Depends(get_db),
):
    return await submit_video_assets_job(
        video=video,
        languages=languages,
        sign_languages=sign_languages,
        manual_text=manual_text,
        avatar_provider_name=(
            avatar_provider_name
        ),
        idempotency_key=idempotency_key,
        principal=principal,
        db=db,
        upload_dir=UPLOAD_DIR,
    )

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