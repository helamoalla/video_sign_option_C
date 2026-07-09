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


Path("outputs").mkdir(exist_ok=True)
Path("uploads").mkdir(exist_ok=True)
Path("temp").mkdir(exist_ok=True)

app = FastAPI(title="CYRKIL Option C - Geo Adaptive Sign Video")
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")


class AvatarRequest(BaseModel):
    text: str
    language: str = "lsa"
    provider_name: str = "cwasa_multilang"


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
        cwasa_url = f"http://127.0.0.1:8000/outputs/{output_folder}/index.html"

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
        provider = get_avatar_provider(req.provider_name)

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
        provider = get_avatar_provider("cwasa_multilang")

        file_id = str(uuid.uuid4())
        output_path = f"outputs/{file_id}.mp4"

        avatar_html = provider.generate(
            text=req.text,
            language=req.language,
            output_path=output_path,
        )

        html_path = Path(avatar_html)
        output_folder = html_path.parent.name

        cwasa_url = f"http://127.0.0.1:8000/outputs/{output_folder}/index.html"
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

@app.post("/process-video-assets")
def process_video_assets(
    video: UploadFile = File(...),
    languages: str = Form("french,arabic,german,english,greek"),
    sign_languages: str = Form("lsf,lsa,dgs,bsl,gsl"),
    manual_text: Optional[str] = Form(None),
    avatar_provider_name: str = Form("cwasa_multilang"),
):
    extension = video.filename.split(".")[-1].lower()
    session_id = str(uuid.uuid4())

    session_dir = Path("outputs") / session_id
    video_dir = session_dir / "video"
    subtitle_dir = session_dir / "subtitles"
    avatar_dir = session_dir / "avatars"
    rendered_dir = session_dir / "rendered"

    video_dir.mkdir(parents=True, exist_ok=True)
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    avatar_dir.mkdir(parents=True, exist_ok=True)
    rendered_dir.mkdir(parents=True, exist_ok=True)

    input_path = video_dir / f"original.{extension}"

    with open(input_path, "wb") as f:
        f.write(video.file.read())

    audio_extensions = ["mp3", "wav", "m4a", "aac", "ogg"]
    is_audio_only = extension in audio_extensions

    clean_manual_text = manual_text.strip() if manual_text else ""

    if clean_manual_text and clean_manual_text.lower() != "string":
        original_text = clean_manual_text
        transcription = {
            "language": "manual",
            "text": original_text,
            "segments": [{"start": 0.0, "end": 10.0, "text": original_text}],
        }
    else:
        try:
            transcription = transcribe_video(str(input_path))
            original_text = transcription["text"]
        except Exception as e:
            return {
                "error": "Transcription failed",
                "details": str(e),
            }

    duration = (
        max(seg["end"] for seg in transcription.get("segments", []))
        if transcription.get("segments")
        else 10.0
    )

    requested_languages = [x.strip().lower() for x in languages.split(",") if x.strip()]
    requested_sign_languages = [x.strip().lower() for x in sign_languages.split(",") if x.strip()]

    subtitle_assets = {}
    avatar_assets = {}
    translations = {}
    avatar_debug = {}
    rendered_videos = {}

    SIGN_TO_SUBTITLE = {
        "lsf": "french",
        "lsa": "arabic",
        "dgs": "german",
        "bsl": "english",
        "gsl": "greek",
        "isl": "italian",
        "esl": "spanish",
    }

    def to_vtt_timestamp(seconds: float) -> str:
        milliseconds = int((seconds - int(seconds)) * 1000)
        total_seconds = int(seconds)
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}.{milliseconds:03d}"

    def create_vtt(path: Path, text: str, duration_seconds: float):
        words = text.split()
        chunk_size = 6
        chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
        chunk_duration = duration_seconds / max(len(chunks), 1)

        content = "WEBVTT\n\n"

        for i, chunk in enumerate(chunks):
            start = i * chunk_duration
            end = min((i + 1) * chunk_duration, duration_seconds)
            content += f"{to_vtt_timestamp(start)} --> {to_vtt_timestamp(end)}\n"
            content += f"{chunk}\n\n"

        path.write_text(content, encoding="utf-8")

    for lang in requested_languages:
        try:
            translated_text = original_text if lang in ["same", "original"] else translate_text(original_text, lang)
            translations[lang] = translated_text

            vtt_path = subtitle_dir / f"{lang}.vtt"
            create_vtt(vtt_path, translated_text, duration)

            subtitle_assets[lang] = f"/outputs/{session_id}/subtitles/{lang}.vtt"

        except Exception as e:
            translations[lang] = None
            subtitle_assets[lang] = None
            print(f"[WARN] Subtitle generation failed for {lang}: {e}")

    provider = get_avatar_provider(avatar_provider_name)

    for sign_lang in requested_sign_languages:
        text_for_lang = ""
        glosses = []

        try:
            target_sub_lang = SIGN_TO_SUBTITLE.get(sign_lang)

            if target_sub_lang:
                text_for_lang = translations.get(target_sub_lang) or translate_text(original_text, target_sub_lang)
            else:
                text_for_lang = original_text

            glosses = generate_gloss(text_for_lang, language=sign_lang)

            avatar_debug[sign_lang] = {
                "input_text_for_avatar": text_for_lang,
                "glosses_found": glosses,
                "avatar_url": None,
                "error": None,
            }

            if not glosses:
                avatar_assets[sign_lang] = None
                avatar_debug[sign_lang]["error"] = "No glosses found in available dictionary."
                continue

            avatar_html_or_video = provider.generate(
                text=" ".join(glosses),
                language=sign_lang,
                output_path=str(avatar_dir / f"{sign_lang}.mp4"),
            )

            html_path = Path(avatar_html_or_video)
            recorded_path = avatar_dir / f"{sign_lang}.mp4"

            if html_path.suffix.lower() == ".html":
                cwasa_url = (
                    f"http://127.0.0.1:8000/outputs/"
                    f"{session_id}/avatars/{html_path.parent.name}/index.html"
                )

                record_cwasa_page(
                    page_url=cwasa_url,
                    output_path=str(recorded_path),
                    duration_ms=15000,
                    trim_start_seconds=5.0,
                )

                avatar_assets[sign_lang] = f"/outputs/{session_id}/avatars/{sign_lang}.mp4"
                avatar_debug[sign_lang]["avatar_url"] = avatar_assets[sign_lang]
                avatar_debug[sign_lang]["cwasa_url"] = cwasa_url
            else:
                avatar_assets[sign_lang] = f"/outputs/{session_id}/avatars/{sign_lang}.mp4"
                avatar_debug[sign_lang]["avatar_url"] = avatar_assets[sign_lang]

        except Exception as e:
            avatar_assets[sign_lang] = None
            avatar_debug[sign_lang] = {
                "input_text_for_avatar": text_for_lang,
                "glosses_found": glosses,
                "avatar_url": None,
                "error": str(e),
            }
            print(f"[WARN] Avatar generation failed for {sign_lang}: {e}")

    render_pairs = {}

    for sign_lang in requested_sign_languages:
        sub_lang = SIGN_TO_SUBTITLE.get(sign_lang)

        if not sub_lang:
            continue

        if not translations.get(sub_lang):
            print(f"[WARN] No translation for {sub_lang}, skipping {sign_lang}")
            continue

        if not avatar_assets.get(sign_lang):
            print(f"[WARN] No avatar for {sign_lang}, skipping render")
            continue

        render_pairs[f"{sub_lang}_{sign_lang}"] = (sub_lang, sign_lang)

    for key, (sub_lang, sign_lang) in render_pairs.items():
        try:
            avatar_relative_path = avatar_assets[sign_lang].replace(
                f"/outputs/{session_id}/",
                "",
            )
            avatar_local_path = session_dir / avatar_relative_path
            rendered_output = rendered_dir / f"{key}.mp4"

            words = translations[sub_lang].split()
            chunk_size = 6
            chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
            chunk_duration = duration / max(len(chunks), 1)

            subtitle_segments = []
            for i, chunk in enumerate(chunks):
                subtitle_segments.append({
                    "start": i * chunk_duration,
                    "end": min((i + 1) * chunk_duration, duration),
                    "text": chunk,
                })

            compose_final_video(
                original_media_path=str(input_path),
                avatar_video_path=str(avatar_local_path),
                translated_text=translations[sub_lang],
                output_path=str(rendered_output),
                is_audio_only=is_audio_only,
                subtitle_segments=subtitle_segments,
                subtitle_language=sub_lang,
            )

            rendered_videos[key] = f"/outputs/{session_id}/rendered/{key}.mp4"

        except Exception as e:
            print(f"[WARN] Rendered video failed for {key}: {e}")

    video_url = f"/outputs/{session_id}/video/original.{extension}"
    statistics = compute_language_statistics(avatar_debug)

    manifest, manifest_path = save_manifest(
        session_dir=session_dir,
        session_id=session_id,
        video_url=video_url,
        original_language=transcription.get("language"),
        original_text=original_text,
        translations=translations,
        subtitles=subtitle_assets,
        avatars=avatar_assets,
        avatar_debug=avatar_debug,
        rendered_videos=rendered_videos,
    )

    try:
        build_player(
            session_dir=session_dir,
            video_url=video_url,
            subtitles=subtitle_assets,
            avatars=avatar_assets,
        )
    except Exception as e:
        print(f"[WARN] Player generation failed: {e}")

    return {
        "status": "success",
        "session_id": session_id,
        "original_language": transcription.get("language"),
        "original_text": original_text,
        "player_url": f"/outputs/{session_id}/player.html",
        "manifest_url": f"/outputs/{session_id}/manifest.json",
        "rendered_videos": rendered_videos,
        "statistics": statistics,
        "geo_ready": True,
        "iframe": f'<iframe src="http://127.0.0.1:8000/outputs/{session_id}/player.html" width="100%" height="650"></iframe>',
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