from typing import Optional
from pathlib import Path
import uuid
import traceback

from pydantic import BaseModel



from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.transcribe import transcribe_video
from app.translate import translate_text
from app.subtitles import generate_subtitles
from app.gloss_generator import generate_gloss
from app.avatar.provider_factory import get_avatar_provider
from app.video_editor import compose_final_video
from app.utils import create_file_path
from app.avatar.cwasa_recorder import record_cwasa_page
from app.sign_language_config import list_countries, get_always_available_lsa
from app.geo_router import resolve_sign_route
from app.player_builder import build_player
from app.session_manifest import save_manifest
from app.statistics import compute_language_statistics


from contextlib import asynccontextmanager
from app.config import INTERNAL_BASE_URL, PUBLIC_BASE_URL
from app.database import Base, engine
from app import models
from shutil import copyfileobj

from fastapi import Depends, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from app.tasks import process_video_assets_task

from app.database import get_db
from app.models import JobStatus, VideoJob
from app.schemas import JobCreatedResponse, JobStatusResponse
from app.tasks import process_video_task

PROJECT_ROOT = Path(__file__).resolve().parent.parent

OUTPUT_DIR = PROJECT_ROOT / "outputs"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
TEMP_DIR = PROJECT_ROOT / "temp"

def create_runtime_directories() -> None:
    """Create directories required by the application at runtime."""
    for directory in (OUTPUT_DIR, UPLOAD_DIR, TEMP_DIR):
        directory.mkdir(parents=True, exist_ok=True)


# Required before StaticFiles is mounted.
create_runtime_directories()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_runtime_directories()
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="CYRKIL Option C - Geo Adaptive Sign Video",
    lifespan=lifespan,
)

app.mount(
    "/outputs",
    StaticFiles(directory=str(OUTPUT_DIR)),
    name="outputs",
)


class AvatarRequest(BaseModel):
    text: str
    language: str = "lsa"
    provider_name: str = "cwasa_multilang"

@app.get("/health")
def health():
    return {
        "status": "healthy"
    }

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


def save_uploaded_file(source, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)

    with destination.open("wb") as output:
        copyfileobj(source, output)

@app.post(
    "/jobs",
    response_model=JobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_video_job(
    video: UploadFile = File(...),
    target_language: str = Form("same"),
    sign_language: str = Form("lsa"),
    subtitle_mode: str = Form("original"),
    country_code: Optional[str] = Form(None),
    avatar_provider_name: str = Form("cwasa_multilang"),
    manual_text: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    extension = Path(video.filename or "").suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file extension: {extension}",
        )

    job_id = str(uuid.uuid4())
    input_path = UPLOAD_DIR / job_id / f"original{extension}"

    await run_in_threadpool(
        save_uploaded_file,
        video.file,
        input_path,
    )

    job = VideoJob(
        id=job_id,
        status=JobStatus.QUEUED,
        stage="queued",
        progress=0,
        input_path=str(input_path),
        parameters={
            "target_language": target_language,
            "sign_language": sign_language,
            "subtitle_mode": subtitle_mode,
            "country_code": country_code,
            "avatar_provider_name": avatar_provider_name,
            "manual_text": manual_text,
        },
    )

    db.add(job)
    db.commit()

    try:
        process_video_task.delay(job_id)
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.stage = "queue_submission"
        job.error = f"Could not submit job: {exc}"
        db.commit()

        raise HTTPException(
            status_code=503,
            detail="The processing queue is unavailable.",
        ) from exc

    return {
        "job_id": job_id,
        "status": JobStatus.QUEUED,
        "status_url": f"/jobs/{job_id}",
    }

@app.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
)
def get_video_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = db.get(VideoJob, job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    return job

@app.post("/process-video")
def process_video(
    video: UploadFile = File(...),
    target_language: str = Form("same"),
    sign_language: str = Form("lsa"),
    subtitle_mode: str = Form("original"),  # original or translated
    country_code: Optional[str] = Form(None),
    avatar_provider_name: str = Form("cwasa_multilang"),
    manual_text: Optional[str] = Form(None),
):
    extension = video.filename.split(".")[-1].lower()
    input_path = create_file_path("uploads", extension)

    with open(input_path, "wb") as f:
        f.write(video.file.read())

    audio_extensions = ["mp3", "wav", "m4a", "aac", "ogg"]
    video_extensions = ["mp4", "mov", "avi", "mkv", "webm"]
    is_audio_only = extension in audio_extensions

    if extension not in audio_extensions + video_extensions:
        return {
            "error": f"Unsupported file format: {extension}",
            "solution": "Upload MP4, MOV, AVI, MKV, WEBM, MP3, WAV, M4A, AAC, or OGG.",
        }

    file_id = str(uuid.uuid4())
    clean_manual_text = manual_text.strip() if manual_text else ""

    if clean_manual_text and clean_manual_text.lower() != "string":
        original_text = clean_manual_text
        transcription = {
            "language": "manual",
            "text": original_text,
            "segments": [{"start": 0.0, "end": 5.0, "text": original_text}],
        }
    else:
        try:
            transcription = transcribe_video(input_path)
            original_text = transcription["text"]
        except Exception as e:
            return {
                "error": "Transcription failed",
                "details": str(e),
                "solution": "Use a valid MP4 with audio, M4A/WAV, or use manual_text.",
            }

    subtitle_output_dir = Path("outputs") / file_id / "subtitles"

    subtitle_result = generate_subtitles(
        result=transcription,
        output_dir=subtitle_output_dir,
        file_id=file_id,
    )

    original_subtitle_segments = subtitle_result["data"]["segments"]

    try:
        if target_language.lower() in ["same", "original", ""]:
            translated_text = original_text
        else:
            translated_text = translate_text(original_text, target_language)
    except Exception as e:
        return {
            "error": "Translation failed",
            "details": str(e),
            "solution": "Use target_language: same, french, arabic, german, english.",
        }

    subtitle_segments = original_subtitle_segments

    if subtitle_mode == "translated":
        duration = (
            max(seg["end"] for seg in original_subtitle_segments)
            if original_subtitle_segments
            else 5.0
        )
        subtitle_segments = [
            {
                "start": 0.0,
                "end": duration,
                "text": translated_text,
            }
        ]

    glosses = []

    if avatar_provider_name in {"cwasa_arabic", "cwasa_multilang", "cwasa_multilingual"}:
        try:
            glosses = generate_gloss(translated_text, language=sign_language)
        except Exception as e:
            return {
                "error": "Gloss generation failed",
                "details": str(e),
            }

    avatar_provider = get_avatar_provider(avatar_provider_name)
    avatar_output_path = create_file_path("outputs", "mp4")

    try:
        text_for_avatar = " ".join(glosses) if glosses else translated_text

        avatar_output = avatar_provider.generate(
            text=text_for_avatar,
            language=sign_language,
            output_path=avatar_output_path,
        )
    except Exception as e:
        return {
            "error": "Avatar generation failed",
            "details": str(e),
            "solution": "Check that the selected sign_language has matching SiGML files.",
        }

    cwasa_url = None

    if avatar_provider_name in {"cwasa_arabic", "cwasa_multilang", "cwasa_multilingual"}:
        html_path = Path(avatar_output)
        output_folder = html_path.parent.name
        cwasa_url = (
    f"{INTERNAL_BASE_URL}/outputs/{output_folder}/index.html"
)

        recorded_avatar_path = create_file_path("outputs", "mp4")

        try:
            record_cwasa_page(
                page_url=cwasa_url,
                output_path=recorded_avatar_path,
                duration_ms=15000,
                trim_start_seconds=5.0,
            )
            avatar_output = recorded_avatar_path
        except Exception:
            return {
                "error": "CWASA recording failed",
                "details": traceback.format_exc(),
                "cwasa_url": cwasa_url,
                "solution": "Open cwasa_url in Chrome. If the avatar does not play there, recording cannot work.",
            }

    final_output_path = create_file_path("outputs", "mp4")

    try:
        compose_final_video(
            original_media_path=input_path,
            avatar_video_path=avatar_output,
            translated_text=translated_text,
            output_path=final_output_path,
            is_audio_only=is_audio_only,
            subtitle_segments=subtitle_segments,
        )
    except Exception as e:
        return {
            "error": "Video composition failed",
            "details": str(e),
        }

    filename = Path(final_output_path).name

    response = {
        "status": "success",
        "original_language": transcription["language"],
        "original_text": original_text,
        "target_language": target_language,
        "translated_text": translated_text,
        "subtitle_mode": subtitle_mode,
        "subtitle_segments_used": subtitle_segments,
        "glosses": glosses,
        "avatar_provider": avatar_provider_name,
        "sign_language": sign_language,
        "country_code": country_code,
        "avatar_output": avatar_output,
        "subtitles": subtitle_result["data"],
        "subtitles_json": subtitle_result["json_path"],
        "subtitles_srt": subtitle_result["srt_path"],
        "subtitles_vtt": subtitle_result["vtt_path"],
        "download_url": f"/download/{filename}",
    }

    if cwasa_url:
        response["cwasa_url"] = cwasa_url

    return response


@app.post("/gloss/test")
def test_gloss(req: AvatarRequest):
    try:
        glosses = generate_gloss(req.text, language=req.language)
        return {
            "status": "success",
            "input_text": req.text,
            "language": req.language,
            "glosses": glosses,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/avatar/generate")
def generate_avatar(req: AvatarRequest):
    try:
        provider = get_avatar_provider(
        req.provider_name,
        language=req.language,
    )

        file_id = str(uuid.uuid4())
        output_path = f"outputs/{file_id}.mp4"

        glosses = []
        text_for_avatar = req.text

        if req.provider_name in {"cwasa_arabic", "cwasa_multilang", "cwasa_multilingual"}:
            glosses = generate_gloss(req.text, language=req.language)
            text_for_avatar = " ".join(glosses)

        avatar_output = provider.generate(
            text=text_for_avatar,
            language=req.language,
            output_path=output_path,
        )

        avatar_output_path = Path(avatar_output)

        response = {
            "status": "success",
            "provider": req.provider_name,
            "language": req.language,
            "input_text": req.text,
            "glosses": glosses,
            "text_sent_to_avatar": text_for_avatar,
            "avatar_output": avatar_output,
        }

        if req.provider_name in {"cwasa_arabic", "cwasa_multilang", "cwasa_multilingual"}:
            response["cwasa_url"] = (
                f"/outputs/{avatar_output_path.parent.name}/{avatar_output_path.name}"
            )
        else:
            response["download_url"] = f"/download/{avatar_output_path.name}"

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download/{filename}")
def download_video(filename: str):
    path = f"outputs/{filename}"
    return FileResponse(path, media_type="video/mp4", filename=filename)


@app.post("/cwasa/test-record")
def test_cwasa_record(req: AvatarRequest):
    try:
        provider = get_avatar_provider(
        "cwasa_multilang",
        language=req.language,
    )

        file_id = str(uuid.uuid4())
        output_path = f"outputs/{file_id}.mp4"

        avatar_html = provider.generate(
            text=req.text,
            language=req.language,
            output_path=output_path,
        )

        html_path = Path(avatar_html)
        output_folder = html_path.parent.name

        cwasa_url = (
    f"{INTERNAL_BASE_URL}/outputs/{output_folder}/index.html"
)
        recorded_path = create_file_path("outputs", "webm")

        record_cwasa_page(
            page_url=cwasa_url,
            output_path=recorded_path,
            duration_ms=12000,
        )

        return {
            "status": "success",
            "input_text": req.text,
            "cwasa_url": cwasa_url,
            "recorded_avatar": recorded_path,
        }

    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@app.get("/sign-languages")
def sign_languages():
    return {
        "countries": list_countries(),
        "always_available": get_always_available_lsa(),
    }


@app.get("/sign-route")
def sign_route(
    country_code: Optional[str] = None,
    manual_sign_language: Optional[str] = None,
    browser_language: Optional[str] = None,
    ip_geolocation_consent: bool = False,
):
    return resolve_sign_route(
        country_code=country_code,
        manual_sign_language=manual_sign_language,
        browser_language=browser_language,
        ip_geolocation_consent=ip_geolocation_consent,
    )

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
    avatar_provider_name: str = Form("cwasa_multilang"),
    db: Session = Depends(get_db),
):
    extension = Path(video.filename or "").suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file extension: {extension}",
        )

    job_id = str(uuid.uuid4())
    input_path = UPLOAD_DIR / job_id / f"original{extension}"

    await run_in_threadpool(
        save_uploaded_file,
        video.file,
        input_path,
    )

    job = VideoJob(
        id=job_id,
        status=JobStatus.QUEUED,
        stage="queued",
        progress=0,
        input_path=str(input_path),
        parameters={
            "pipeline": "video_assets",
            "languages": languages,
            "sign_languages": sign_languages,
            "manual_text": manual_text,
            "avatar_provider_name": avatar_provider_name,
            "extension": extension,
        },
    )

    db.add(job)
    db.commit()

    try:
        process_video_assets_task.delay(job_id)

    except Exception as exc:
        job.status = JobStatus.FAILED
        job.stage = "queue_submission"
        job.error = str(exc)
        db.commit()

        raise HTTPException(
            status_code=503,
            detail="The processing queue is unavailable.",
        ) from exc

    return {
        "job_id": job_id,
        "status": JobStatus.QUEUED,
        "status_url": f"/jobs/{job_id}",
    }
    
from app.director.hf_video_director import generate_director_video

class DirectorRequest(BaseModel):
    prompt: str
    language: str = "french"


@app.post("/director/hf-video")
def director_hf_video(req: DirectorRequest):
    try:
        result = generate_director_video(req.prompt, req.language)
        return {
            "status": "success",
            **result,
            "next_step": "Upload this MP4 to /process-video-assets"
        }
    except Exception as e:
        return {
            "error": "PixVerse video generation failed",
            "details": str(e),
        }