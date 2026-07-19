import logging
import shutil
from pathlib import Path
from typing import Callable

from app.avatar.cwasa_recorder import record_cwasa_page
from app.avatar.provider_factory import get_avatar_provider
from app.config import INTERNAL_BASE_URL, PUBLIC_BASE_URL
from app.gloss_generator import generate_gloss
from app.player_builder import build_player
from app.session_manifest import save_manifest
from app.statistics import compute_language_statistics
from app.transcribe import transcribe_video
from app.translate import translate_text
from app.video_editor import compose_final_video


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "outputs"

ProgressCallback = Callable[[str, int], None]

AUDIO_EXTENSIONS = {
    "mp3",
    "wav",
    "m4a",
    "aac",
    "ogg",
}

SIGN_TO_SUBTITLE = {
    # Currently implemented
    "lsf": "french",
    "lsa": "arabic",
    "dgs": "german",
    "bsl": "english",
    "gsl": "greek",

    # Future languages
    "lis": "italian",
    "lse": "spanish",
    "ngt": "dutch",
    "pjm": "polish",
    "vgt": "dutch",
    "lsfb": "french",
}


def parse_csv_values(
    value: str,
) -> list[str]:
    return [
        item.strip().lower()
        for item in value.split(",")
        if item.strip()
    ]


def to_vtt_timestamp(
    seconds: float,
) -> str:
    milliseconds = int(
        (seconds - int(seconds)) * 1000
    )

    total_seconds = int(seconds)

    hours = total_seconds // 3600
    minutes = (
        total_seconds % 3600
    ) // 60
    remaining_seconds = (
        total_seconds % 60
    )

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{remaining_seconds:02d}."
        f"{milliseconds:03d}"
    )


def normalize_source_segments(
    transcription: dict,
    original_text: str,
    duration: float,
) -> list[dict]:
    """
    Normalize Whisper segments while preserving their original
    start and end timestamps.
    """

    source_segments = []

    for segment in transcription.get(
        "segments",
        [],
    ):
        text = str(
            segment.get("text", "")
        ).strip()

        if not text:
            continue

        try:
            start = float(
                segment.get("start", 0.0)
            )

            end = float(
                segment.get("end", duration)
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        if start < 0:
            start = 0.0

        if end > duration:
            end = duration

        if end <= start:
            continue

        source_segments.append(
            {
                "start": start,
                "end": end,
                "text": text,
            }
        )

    if not source_segments:
        source_segments = [
            {
                "start": 0.0,
                "end": duration,
                "text": original_text,
            }
        ]

    return source_segments


def translate_timed_segments(
    source_segments: list[dict],
    target_language: str,
) -> list[dict]:
    """
    Translate each subtitle segment independently while keeping
    its original timestamp.
    """

    translated_segments = []

    normalized_language = (
        target_language
        or "original"
    ).lower().strip()

    for segment in source_segments:
        if normalized_language in {
            "same",
            "original",
        }:
            translated_text = segment["text"]

        else:
            translated_text = translate_text(
                segment["text"],
                normalized_language,
            )

        translated_text = str(
            translated_text
            or ""
        ).strip()

        if not translated_text:
            raise RuntimeError(
                "Segment translation returned empty text "
                f"for language={normalized_language}."
            )

        translated_segments.append(
            {
                "start": segment["start"],
                "end": segment["end"],
                "text": translated_text,
            }
        )

    if not translated_segments:
        raise RuntimeError(
            "No translated subtitle segments were created "
            f"for language={normalized_language}."
        )

    return translated_segments


def write_vtt_segments(
    path: Path,
    segments: list[dict],
) -> None:
    """
    Write already timed subtitle segments to a WebVTT file.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    lines = [
        "WEBVTT",
        "",
    ]

    for segment in segments:
        lines.append(
            f"{to_vtt_timestamp(segment['start'])} "
            "--> "
            f"{to_vtt_timestamp(segment['end'])}"
        )

        lines.append(
            str(segment["text"])
        )

        lines.append("")

    path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def join_segment_text(
    segments: list[dict],
) -> str:
    return " ".join(
        str(segment["text"]).strip()
        for segment in segments
        if str(
            segment.get("text", "")
        ).strip()
    ).strip()


def run_video_assets_pipeline(
    job_id: str,
    input_path: str,
    parameters: dict,
    update_progress: ProgressCallback,
) -> dict:
    session_id = job_id
    source_input_path = Path(input_path)

    if not source_input_path.is_file():
        raise FileNotFoundError(
            "Uploaded media was not found: "
            f"{source_input_path}"
        )

    languages = parameters.get(
        "languages",
        "french,arabic,german,english,greek",
    )

    sign_languages = parameters.get(
        "sign_languages",
        "lsf,lsa,dgs,bsl,gsl",
    )

    manual_text = parameters.get(
        "manual_text"
    )

    avatar_provider_name = parameters.get(
        "avatar_provider_name",
        "cwasa_multilang",
    )

    extension = parameters.get(
        "extension"
    )

    media_metadata = parameters.get(
        "media_metadata",
        {},
    )

    if extension:
        extension = (
            extension
            .lstrip(".")
            .lower()
        )

    else:
        extension = (
            source_input_path
            .suffix
            .lstrip(".")
            .lower()
        )

    requested_languages = parse_csv_values(
        languages
    )

    requested_sign_languages = parse_csv_values(
        sign_languages
    )

    if not requested_languages:
        raise ValueError(
            "At least one subtitle language "
            "must be requested."
        )

    if not requested_sign_languages:
        raise ValueError(
            "At least one sign language "
            "must be requested."
        )

    invalid_sign_languages = [
        language
        for language in requested_sign_languages
        if language not in SIGN_TO_SUBTITLE
    ]

    if invalid_sign_languages:
        raise ValueError(
            "Invalid sign-language codes: "
            f"{invalid_sign_languages}."
        )

    session_dir = (
        OUTPUT_DIR / session_id
    )

    video_dir = (
        session_dir / "video"
    )

    subtitle_dir = (
        session_dir / "subtitles"
    )

    avatar_dir = (
        session_dir / "avatars"
    )

    rendered_dir = (
        session_dir / "rendered"
    )

    for directory in (
        video_dir,
        subtitle_dir,
        avatar_dir,
        rendered_dir,
    ):
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    pipeline_input_path = (
        video_dir
        / f"original.{extension}"
    )

    if (
        source_input_path.resolve()
        != pipeline_input_path.resolve()
    ):
        shutil.copy2(
            source_input_path,
            pipeline_input_path,
        )

    if not pipeline_input_path.is_file():
        raise RuntimeError(
            "The uploaded media could not be copied "
            "into the output session directory."
        )

    is_audio_only = (
        extension in AUDIO_EXTENSIONS
    )

    # ---------------------------------------------------------
    # Duration
    # ---------------------------------------------------------

    probed_duration = (
        media_metadata.get(
            "duration_seconds"
        )
        if isinstance(
            media_metadata,
            dict,
        )
        else None
    )

    try:
        probed_duration = float(
            probed_duration
        )

    except (
        TypeError,
        ValueError,
    ):
        probed_duration = None

    if (
        probed_duration is not None
        and probed_duration <= 0
    ):
        probed_duration = None

    # ---------------------------------------------------------
    # Transcription
    # ---------------------------------------------------------

    update_progress(
        "transcription",
        10,
    )

    clean_manual_text = (
        manual_text.strip()
        if manual_text
        else ""
    )

    if (
        clean_manual_text
        and clean_manual_text.lower()
        != "string"
    ):
        original_text = (
            clean_manual_text
        )

        manual_duration = (
            probed_duration
            or 10.0
        )

        transcription = {
            "language": "manual",
            "text": original_text,
            "segments": [
                {
                    "start": 0.0,
                    "end": manual_duration,
                    "text": original_text,
                }
            ],
        }

    else:
        transcription = transcribe_video(
            str(pipeline_input_path)
        )

        original_text = str(
            transcription.get(
                "text",
                "",
            )
        ).strip()

        if not original_text:
            raise RuntimeError(
                "Transcription completed but "
                "returned empty text."
            )

    transcription_segments = (
        transcription.get(
            "segments",
            [],
        )
    )

    segment_duration = (
        max(
            float(segment["end"])
            for segment
            in transcription_segments
            if segment.get("end") is not None
        )
        if transcription_segments
        else 0.0
    )

    duration = (
        probed_duration
        or segment_duration
        or 10.0
    )

    if duration <= 0:
        duration = 10.0

    source_segments = (
        normalize_source_segments(
            transcription=transcription,
            original_text=original_text,
            duration=duration,
        )
    )

    # ---------------------------------------------------------
    # Translations and timed subtitles
    # ---------------------------------------------------------

    update_progress(
        "translation",
        25,
    )

    subtitle_assets: dict[
        str,
        str | None,
    ] = {}

    avatar_assets: dict[
        str,
        str | None,
    ] = {}

    translations: dict[
        str,
        str | None,
    ] = {}

    translated_segments_by_language: dict[
        str,
        list[dict],
    ] = {}

    avatar_debug: dict[
        str,
        dict,
    ] = {}

    rendered_videos: dict[
        str,
        str,
    ] = {}

    translation_errors: dict[
        str,
        str,
    ] = {}

    rendering_errors: dict[
        str,
        str,
    ] = {}

    source_vtt_path = (
        subtitle_dir / "source.vtt"
    )

    write_vtt_segments(
        path=source_vtt_path,
        segments=source_segments,
    )

    subtitle_assets["source"] = (
        f"/outputs/{session_id}/subtitles/"
        "source.vtt"
    )

    for language in requested_languages:
        try:
            translated_segments = (
                translate_timed_segments(
                    source_segments=(
                        source_segments
                    ),
                    target_language=language,
                )
            )

            translated_text = (
                join_segment_text(
                    translated_segments
                )
            )

            if not translated_text:
                raise RuntimeError(
                    "Translated subtitle track "
                    f"is empty for {language}."
                )

            translations[language] = (
                translated_text
            )

            translated_segments_by_language[
                language
            ] = translated_segments

            vtt_path = (
                subtitle_dir
                / f"{language}.vtt"
            )

            write_vtt_segments(
                path=vtt_path,
                segments=translated_segments,
            )

            subtitle_assets[language] = (
                f"/outputs/{session_id}/subtitles/"
                f"{language}.vtt"
            )

        except Exception as exc:
            translations[language] = None

            translated_segments_by_language[
                language
            ] = []

            subtitle_assets[language] = None

            translation_errors[language] = (
                str(exc)
            )

            logger.exception(
                "Timed subtitle generation "
                "failed for %s",
                language,
            )

    if not any(
        translations.values()
    ):
        raise RuntimeError(
            "Translation and timed subtitle "
            "generation failed for every requested "
            f"language: {translation_errors}"
        )

    # ---------------------------------------------------------
    # Glosses and avatars
    # ---------------------------------------------------------

    update_progress(
        "gloss_generation",
        40,
    )

    total_sign_languages = len(
        requested_sign_languages
    )

    for index, sign_language in enumerate(
        requested_sign_languages
    ):
        text_for_language = ""
        glosses = []

        try:
            provider = get_avatar_provider(
                avatar_provider_name,
                language=sign_language,
            )

            subtitle_language = (
                SIGN_TO_SUBTITLE.get(
                    sign_language
                )
            )

            if not subtitle_language:
                raise ValueError(
                    "No subtitle-language mapping "
                    f"exists for {sign_language}."
                )

            text_for_language = (
                translations.get(
                    subtitle_language
                )
            )

            if not text_for_language:
                translated_segments = (
                    translate_timed_segments(
                        source_segments=(
                            source_segments
                        ),
                        target_language=(
                            subtitle_language
                        ),
                    )
                )

                text_for_language = (
                    join_segment_text(
                        translated_segments
                    )
                )

                if not text_for_language:
                    raise RuntimeError(
                        "Translation returned empty "
                        f"text for {subtitle_language}."
                    )

                translations[
                    subtitle_language
                ] = text_for_language

                translated_segments_by_language[
                    subtitle_language
                ] = translated_segments

                vtt_path = (
                    subtitle_dir
                    / f"{subtitle_language}.vtt"
                )

                write_vtt_segments(
                    path=vtt_path,
                    segments=translated_segments,
                )

                subtitle_assets[
                    subtitle_language
                ] = (
                    f"/outputs/{session_id}/subtitles/"
                    f"{subtitle_language}.vtt"
                )

                translation_errors.pop(
                    subtitle_language,
                    None,
                )

            glosses = generate_gloss(
                text_for_language,
                language=sign_language,
            )

            avatar_debug[
                sign_language
            ] = {
                "input_text_for_avatar": (
                    text_for_language
                ),
                "glosses_found": glosses,
                "avatar_url": None,
                "error": None,
            }

            if not glosses:
                avatar_assets[
                    sign_language
                ] = None

                avatar_debug[
                    sign_language
                ]["error"] = (
                    "No glosses found in the "
                    "available dictionary."
                )

                continue

            avatar_progress = 40 + int(
                (
                    (index + 1)
                    / total_sign_languages
                )
                * 10
            )

            update_progress(
                (
                    "avatar_generation:"
                    f"{sign_language}"
                ),
                min(
                    avatar_progress,
                    50,
                ),
            )

            avatar_html_or_video = (
                provider.generate(
                    text=text_for_language,
                    language=sign_language,
                    output_path=str(
                        avatar_dir
                        / f"{sign_language}.mp4"
                    ),
                    glosses=glosses,
                )
            )

            if not avatar_html_or_video:
                raise RuntimeError(
                    "Avatar provider returned "
                    "no output path."
                )

            generated_path = Path(
                avatar_html_or_video
            )

            recorded_path = (
                avatar_dir
                / f"{sign_language}.mp4"
            )

            if (
                generated_path
                .suffix
                .lower()
                == ".html"
            ):
                try:
                    relative_html_path = (
                        generated_path
                        .resolve()
                        .relative_to(
                            OUTPUT_DIR.resolve()
                        )
                    )

                except ValueError as exc:
                    raise RuntimeError(
                        "Generated CWASA HTML must "
                        f"be inside {OUTPUT_DIR}. "
                        f"Received: {generated_path}"
                    ) from exc

                cwasa_url = (
                    f"{INTERNAL_BASE_URL}/outputs/"
                    f"{relative_html_path.as_posix()}"
                )

                update_progress(
                    (
                        "avatar_recording:"
                        f"{sign_language}"
                    ),
                    60,
                )

                record_cwasa_page(
                    page_url=cwasa_url,
                    output_path=str(
                        recorded_path
                    ),
                    duration_ms=15000,
                    trim_start_seconds=5.0,
                )

                avatar_debug[
                    sign_language
                ]["cwasa_url"] = cwasa_url

            else:
                if not generated_path.is_file():
                    raise FileNotFoundError(
                        "Avatar provider returned "
                        "a path that does not exist: "
                        f"{generated_path}"
                    )

                if (
                    generated_path.resolve()
                    != recorded_path.resolve()
                ):
                    shutil.copy2(
                        generated_path,
                        recorded_path,
                    )

            if not recorded_path.is_file():
                raise RuntimeError(
                    "Avatar generation completed "
                    "but did not create: "
                    f"{recorded_path}"
                )

            if (
                recorded_path.stat().st_size
                == 0
            ):
                raise RuntimeError(
                    "Avatar video is empty: "
                    f"{recorded_path}"
                )

            avatar_url = (
                f"/outputs/{session_id}/avatars/"
                f"{sign_language}.mp4"
            )

            avatar_assets[
                sign_language
            ] = avatar_url

            avatar_debug[
                sign_language
            ]["avatar_url"] = avatar_url

        except Exception as exc:
            avatar_assets[
                sign_language
            ] = None

            avatar_debug[
                sign_language
            ] = {
                "input_text_for_avatar": (
                    text_for_language
                ),
                "glosses_found": glosses,
                "avatar_url": None,
                "error": str(exc),
            }

            logger.exception(
                "Avatar generation failed "
                "for %s",
                sign_language,
            )

    successful_avatars = {
        language: url
        for language, url
        in avatar_assets.items()
        if url is not None
    }

    if not successful_avatars:
        avatar_errors = {
            language: information.get(
                "error"
            )
            for language, information
            in avatar_debug.items()
        }

        raise RuntimeError(
            "Avatar generation failed for "
            "every requested sign language. "
            f"Errors: {avatar_errors}"
        )

    # ---------------------------------------------------------
    # Final video composition
    # ---------------------------------------------------------

    update_progress(
        "video_composition",
        75,
    )

    render_pairs = {}

    for sign_language in (
        requested_sign_languages
    ):
        subtitle_language = (
            SIGN_TO_SUBTITLE.get(
                sign_language
            )
        )

        if not subtitle_language:
            logger.warning(
                "No subtitle mapping for %s",
                sign_language,
            )
            continue

        if not translations.get(
            subtitle_language
        ):
            logger.warning(
                "No translation for %s; "
                "skipping %s",
                subtitle_language,
                sign_language,
            )
            continue

        if not avatar_assets.get(
            sign_language
        ):
            logger.warning(
                "No avatar for %s; "
                "skipping render",
                sign_language,
            )
            continue

        if not (
            translated_segments_by_language
            .get(subtitle_language)
        ):
            logger.warning(
                "No timed subtitles for %s; "
                "skipping %s",
                subtitle_language,
                sign_language,
            )
            continue

        key = (
            f"{subtitle_language}_"
            f"{sign_language}"
        )

        render_pairs[key] = (
            subtitle_language,
            sign_language,
        )

    if not render_pairs:
        raise RuntimeError(
            "No valid timed-subtitle and avatar "
            "combinations were available for "
            "video composition."
        )

    total_render_pairs = len(
        render_pairs
    )

    for index, (
        key,
        pair,
    ) in enumerate(
        render_pairs.items()
    ):
        subtitle_language, sign_language = pair

        try:
            progress = 75 + int(
                (
                    (index + 1)
                    / total_render_pairs
                )
                * 15
            )

            update_progress(
                (
                    "video_composition:"
                    f"{sign_language}"
                ),
                min(
                    progress,
                    90,
                ),
            )

            avatar_url = avatar_assets[
                sign_language
            ]

            avatar_relative_path = (
                avatar_url.replace(
                    f"/outputs/{session_id}/",
                    "",
                )
            )

            avatar_local_path = (
                session_dir
                / avatar_relative_path
            )

            if not avatar_local_path.is_file():
                raise FileNotFoundError(
                    "Avatar video was not found: "
                    f"{avatar_local_path}"
                )

            rendered_output = (
                rendered_dir
                / f"{key}.mp4"
            )

            translated_text = translations[
                subtitle_language
            ]

            subtitle_segments = (
                translated_segments_by_language
                .get(
                    subtitle_language,
                    [],
                )
            )

            if not subtitle_segments:
                raise RuntimeError(
                    "No timed translated subtitle "
                    "segments exist for "
                    f"{subtitle_language}."
                )

            compose_final_video(
                original_media_path=str(
                    pipeline_input_path
                ),
                avatar_video_path=str(
                    avatar_local_path
                ),
                translated_text=translated_text,
                output_path=str(
                    rendered_output
                ),
                is_audio_only=is_audio_only,
                subtitle_segments=(
                    subtitle_segments
                ),
                subtitle_language=(
                    subtitle_language
                ),
            )

            if not rendered_output.is_file():
                raise RuntimeError(
                    "Video composition returned "
                    "without creating: "
                    f"{rendered_output}"
                )

            if (
                rendered_output.stat().st_size
                == 0
            ):
                raise RuntimeError(
                    "Rendered video is empty: "
                    f"{rendered_output}"
                )

            rendered_videos[key] = (
                f"/outputs/{session_id}/rendered/"
                f"{key}.mp4"
            )

        except Exception as exc:
            rendering_errors[key] = (
                str(exc)
            )

            logger.exception(
                "Rendered video failed "
                "for %s",
                key,
            )

    if not rendered_videos:
        raise RuntimeError(
            "Video composition failed for "
            "every requested language. "
            f"Errors: {rendering_errors}"
        )

    # ---------------------------------------------------------
    # Manifest and player
    # ---------------------------------------------------------

    update_progress(
        "manifest",
        92,
    )

    video_url = (
        f"/outputs/{session_id}/video/"
        f"original.{extension}"
    )

    statistics = (
        compute_language_statistics(
            avatar_debug
        )
    )

    try:
        save_manifest(
            session_dir=session_dir,
            session_id=session_id,
            video_url=video_url,
            original_language=(
                transcription.get(
                    "language"
                )
            ),
            original_text=original_text,
            translations=translations,
            subtitles=subtitle_assets,
            avatars=avatar_assets,
            avatar_debug=avatar_debug,
            rendered_videos=rendered_videos,
        )

    except Exception as exc:
        raise RuntimeError(
            "Manifest generation failed: "
            f"{exc}"
        ) from exc

    update_progress(
        "player_generation",
        96,
    )

    try:
        build_player(
            session_dir=session_dir,
            video_url=video_url,
            subtitles=subtitle_assets,
            avatars=avatar_assets,
        )

    except Exception as exc:
        raise RuntimeError(
            "Player generation failed: "
            f"{exc}"
        ) from exc

    player_path = (
        session_dir / "player.html"
    )

    manifest_path = (
        session_dir / "manifest.json"
    )

    if not player_path.is_file():
        raise RuntimeError(
            "Player file was not created: "
            f"{player_path}"
        )

    if not manifest_path.is_file():
        raise RuntimeError(
            "Manifest file was not created: "
            f"{manifest_path}"
        )

    failed_avatar_languages = {
        language: information.get(
            "error"
        )
        for language, information
        in avatar_debug.items()
        if information.get("error")
    }

    fallbacks = {}

    for language, information in (
        avatar_debug.items()
    ):
        if not information.get("error"):
            continue

        fallback_language = "lsa"

        fallback_avatar_url = (
            avatar_assets.get(
                fallback_language
            )
        )

        fallbacks[language] = {
            "requested_language": language,
            "status": "unavailable",
            "reason": information["error"],
            "fallback_language": (
                fallback_language
            ),
            "fallback_available": bool(
                fallback_avatar_url
            ),
            "fallback_avatar_url": (
                fallback_avatar_url
            ),
            "requires_user_confirmation": True,
        }

    result_status = (
        "partial_success"
        if (
            failed_avatar_languages
            or rendering_errors
            or translation_errors
        )
        else "success"
    )

    result = {
        "status": result_status,
        "session_id": session_id,
        "original_language": (
            transcription.get(
                "language"
            )
        ),
        "original_text": original_text,
        "source_subtitle_segments": (
            source_segments
        ),
        "translated_subtitle_segments": (
            translated_segments_by_language
        ),
        "translations": translations,
        "subtitles": subtitle_assets,
        "avatars": avatar_assets,
        "avatar_debug": avatar_debug,
        "player_url": (
            f"/outputs/{session_id}/"
            "player.html"
        ),
        "manifest_url": (
            f"/outputs/{session_id}/"
            "manifest.json"
        ),
        "rendered_videos": (
            rendered_videos
        ),
        "statistics": statistics,
        "translation_errors": (
            translation_errors
        ),
        "failed_avatar_languages": (
            failed_avatar_languages
        ),
        "fallbacks": fallbacks,
        "rendering_errors": (
            rendering_errors
        ),
        "geo_ready": True,
        "iframe": (
            f'<iframe src="{PUBLIC_BASE_URL}/'
            f'outputs/{session_id}/player.html" '
            'width="100%" height="650"></iframe>'
        ),
    }

    update_progress(
        "completed",
        100,
    )

    return result