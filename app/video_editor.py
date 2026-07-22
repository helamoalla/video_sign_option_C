import os
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)
from PIL import features

FONT_DIRECTORY = (
    Path(__file__).resolve().parent
    / "assets"
    / "fonts"
)

BUNDLED_ARABIC_FONT = (
    FONT_DIRECTORY
    / "IBMPlexSansArabic-SemiBold.ttf"
)

DEFAULT_FONT = os.getenv(
    "DEFAULT_SUBTITLE_FONT",
    (
        "/usr/share/fonts/truetype/"
        "dejavu/DejaVuSans.ttf"
    ),
)

ARABIC_FONT = os.getenv(
    "ARABIC_SUBTITLE_FONT",
    str(BUNDLED_ARABIC_FONT),
)

ARABIC_LANGUAGES = {
    "arabic",
    "ar",
    "lsa",
}


def normalize_subtitle_language(
    language: str,
) -> str:
    return (
        language
        or "english"
    ).lower().strip()


def get_font(language: str) -> str:
    normalized_language = (
        normalize_subtitle_language(language)
    )

    if normalized_language in ARABIC_LANGUAGES:
        font_path = ARABIC_FONT
    else:
        font_path = DEFAULT_FONT

    if not Path(font_path).is_file():
        raise RuntimeError(
            "Required subtitle font is unavailable "
            f"for language={normalized_language}."
        )

    return font_path


def prepare_text(
    text: str,
    language: str = "english",
) -> str:
    clean_text = (text or "").strip()

    if not clean_text:
        return ""

    normalized_language = (
        normalize_subtitle_language(language)
    )

    if (
        normalized_language
        not in ARABIC_LANGUAGES
    ):
        return clean_text

    # Pillow with RAQM already performs Arabic shaping,
    # ligatures and right-to-left ordering. Applying
    # arabic_reshaper/python-bidi as well would corrupt text.
    if features.check("raqm"):
        return clean_text

    # Fallback for minimal Pillow installations without RAQM.
    reshaped_text = arabic_reshaper.reshape(
        clean_text
    )

    return get_display(
        reshaped_text
    )


def create_subtitle_clips(
    segments,
    video_width,
    language="english",
):
    clips = []

    normalized_language = (
        normalize_subtitle_language(language)
    )

    is_arabic = (
        normalized_language
        in ARABIC_LANGUAGES
    )

    for segment in segments:
        text = prepare_text(
            segment["text"],
            normalized_language,
        )

        start = float(segment["start"])
        end = float(segment["end"])
        duration = end - start

        if not text or duration <= 0:
            continue

        clip = (
            TextClip(
                text=text,
                font=get_font(
                    normalized_language
                ),
                font_size=(
                    40 if is_arabic else 44
                ),
                color="white",
                method="caption",
                size=(
                    int(video_width * 0.78),
                    None,
                ),
                text_align=(
                    "right"
                    if is_arabic
                    else "center"
                ),
                horizontal_align=(
                    "right"
                    if is_arabic
                    else "center"
                ),
                interline=8,
                bg_color=None,
                stroke_color="black",
                stroke_width=2,
            )
            .with_start(start)
            .with_duration(duration)
            .with_position(
                ("center", 0.80),
                relative=True,
            )
        )

        clips.append(clip)

    return clips


def build_avatar_video(words, videos_dir, output_path):
    videos_dir = Path(videos_dir)
    clips = []
    missing = []

    for word in words:
        video_path = videos_dir / f"{word.strip().lower()}.mp4"

        if video_path.exists():
            clips.append(VideoFileClip(str(video_path)))
        else:
            missing.append(word)

    if not clips:
        raise ValueError(f"No matching MP4 videos found. Missing: {missing}")

    final = concatenate_videoclips(clips, method="compose")
    final.write_videofile(
        str(output_path),
        codec="libx264",
        audio=False,
        fps=25,
    )

    for clip in clips:
        clip.close()

    final.close()

    return str(output_path), missing


def compose_final_video(
    original_media_path: str,
    avatar_video_path: str,
    translated_text: str,
    output_path: str,
    is_audio_only: bool = False,
    subtitle_segments=None,
    subtitle_language: str = "english",
):
    if is_audio_only:
        audio = AudioFileClip(original_media_path)

        original = (
            ColorClip(
                size=(1280, 720),
                color=(20, 20, 20),
                duration=audio.duration,
            )
            .with_audio(audio)
        )
    else:
        original = VideoFileClip(original_media_path)

        avatar = VideoFileClip(
            avatar_video_path
        )

        avatar = avatar.resized(
            width=int(original.w * 0.30)
        )

        avatar = avatar.with_position(
            ("right", "bottom")
        )

        # Do not extend the declared duration beyond the frames that
        # physically exist in the avatar file. Once the signing
        # animation finishes, the overlay disappears naturally.
        if avatar.duration > original.duration:
            avatar = avatar.subclipped(
                0,
                original.duration,
            )

        clips = [original, avatar]

    if subtitle_segments:
        clips.extend(
            create_subtitle_clips(
                subtitle_segments,
                original.w,
                subtitle_language,
            )
        )
    else:
        subtitle_text = prepare_text(translated_text, subtitle_language)

        subtitle = (
            TextClip(
                text=subtitle_text,
                font=get_font(subtitle_language),
                font_size=46,
                color="white",
                method="caption",
                size=(int(original.w * 0.85), None),
                bg_color=None,
                stroke_color="black",
                stroke_width=3,
            )
            .with_position(("center", 0.82), relative=True)
            .with_duration(original.duration)
        )

        clips.append(subtitle)

    final = CompositeVideoClip(
        clips
    ).with_duration(
        original.duration
    )

    final.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        fps=25,
    )

    original.close()
    avatar.close()
    final.close()

    return output_path