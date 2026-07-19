from pathlib import Path

from moviepy import (
    VideoFileClip,
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    ColorClip,
    concatenate_videoclips,
)

import arabic_reshaper
from bidi.algorithm import get_display


DEFAULT_FONT = (
    "/usr/share/fonts/truetype/dejavu/"
    "DejaVuSans.ttf"
)

ARABIC_FONT = (
    "/usr/share/fonts/truetype/dejavu/"
    "DejaVuSans.ttf"
)

def get_font(language: str) -> str:
    normalized_language = (
        language
        or "english"
    ).lower().strip()

    if normalized_language in {
        "arabic",
        "ar",
        "lsa",
    }:
        font_path = ARABIC_FONT
    else:
        font_path = DEFAULT_FONT

    if not Path(font_path).is_file():
        raise RuntimeError(
            f"Required subtitle font was not found: "
            f"{font_path}"
        )

    return font_path

def prepare_text(text: str, language: str = "english") -> str:
    if not text:
        return ""

    if language in ["arabic", "ar", "lsa"]:
        reshaped_text = arabic_reshaper.reshape(text)
        return get_display(reshaped_text)

    return text


def create_subtitle_clips(segments, video_width, language="english"):
    clips = []

    for seg in segments:
        text = prepare_text(seg["text"].strip(), language)
        start = seg["start"]
        end = seg["end"]
        duration = end - start

        if not text or duration <= 0:
            continue

        clip = (
            TextClip(
                text=text,
                font=get_font(language),
                font_size=46,
                color="white",
                method="caption",
                size=(int(video_width * 0.85), None),
                bg_color=None,
                stroke_color="black",
                stroke_width=3,
            )
            .with_start(start)
            .with_duration(duration)
            .with_position(("center", 0.82), relative=True)
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

    avatar = VideoFileClip(avatar_video_path)

    avatar = avatar.resized(width=int(original.w * 0.30))
    avatar = avatar.with_position(("right", "bottom"))
    avatar = avatar.with_duration(original.duration)

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

    final = CompositeVideoClip(clips)

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