import json
import os
import subprocess
from pathlib import Path


MAX_MEDIA_DURATION_SECONDS = float(
    os.getenv(
        "MAX_MEDIA_DURATION_SECONDS",
        "600",
    )
)

MAX_VIDEO_WIDTH = int(
    os.getenv(
        "MAX_VIDEO_WIDTH",
        "3840",
    )
)

MAX_VIDEO_HEIGHT = int(
    os.getenv(
        "MAX_VIDEO_HEIGHT",
        "2160",
    )
)

MAX_VIDEO_PIXELS = int(
    os.getenv(
        "MAX_VIDEO_PIXELS",
        str(3840 * 2160),
    )
)


ALLOWED_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/webm",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
    "application/ogg",
    "application/octet-stream",
}


EXTENSION_FORMATS = {
    ".mp4": {
        "mov",
        "mp4",
        "m4a",
        "3gp",
        "3g2",
        "mj2",
    },
    ".mov": {
        "mov",
        "mp4",
        "m4a",
        "3gp",
        "3g2",
        "mj2",
    },
    ".m4a": {
        "mov",
        "mp4",
        "m4a",
        "3gp",
        "3g2",
        "mj2",
    },
    ".avi": {
        "avi",
    },
    ".mkv": {
        "matroska",
        "webm",
    },
    ".webm": {
        "matroska",
        "webm",
    },
    ".mp3": {
        "mp3",
    },
    ".wav": {
        "wav",
    },
    ".aac": {
        "aac",
    },
    ".ogg": {
        "ogg",
    },
}


class MediaValidationError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
    ):
        self.code = code
        self.message = message

        super().__init__(message)


def parse_float(value) -> float | None:
    try:
        parsed = float(value)

        if parsed < 0:
            return None

        return parsed

    except (
        TypeError,
        ValueError,
    ):
        return None


def probe_media(path: Path) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    except subprocess.TimeoutExpired as exc:
        raise MediaValidationError(
            code="MEDIA_PROBE_TIMEOUT",
            message=(
                "Media validation exceeded the "
                "allowed time."
            ),
        ) from exc

    except OSError as exc:
        raise RuntimeError(
            "ffprobe could not be executed."
        ) from exc

    if completed.returncode != 0:
        raise MediaValidationError(
            code="INVALID_MEDIA",
            message=(
                "The uploaded file is not valid "
                "or cannot be decoded."
            ),
        )

    try:
        result = json.loads(
            completed.stdout
        )

    except json.JSONDecodeError as exc:
        raise MediaValidationError(
            code="INVALID_PROBE_RESULT",
            message=(
                "The uploaded media could not "
                "be validated."
            ),
        ) from exc

    if not result.get("streams"):
        raise MediaValidationError(
            code="NO_MEDIA_STREAMS",
            message=(
                "The uploaded file contains no "
                "audio or video stream."
            ),
        )

    return result


def get_media_duration(
    probe: dict,
) -> float:
    durations = []

    format_duration = parse_float(
        probe.get("format", {}).get("duration")
    )

    if format_duration is not None:
        durations.append(format_duration)

    for stream in probe.get("streams", []):
        stream_duration = parse_float(
            stream.get("duration")
        )

        if stream_duration is not None:
            durations.append(stream_duration)

    if not durations:
        raise MediaValidationError(
            code="MISSING_MEDIA_DURATION",
            message=(
                "The media duration could not "
                "be determined."
            ),
        )

    duration = max(durations)

    if duration <= 0:
        raise MediaValidationError(
            code="INVALID_MEDIA_DURATION",
            message=(
                "The uploaded media has an "
                "invalid duration."
            ),
        )

    return duration


def validate_media(
    path: Path,
    extension: str,
    declared_content_type: str | None,
    require_audio: bool,
) -> dict:
    if not path.is_file():
        raise MediaValidationError(
            code="MEDIA_NOT_FOUND",
            message=(
                "The uploaded media could not "
                "be found."
            ),
        )

    normalized_extension = (
        extension.lower().strip()
    )

    normalized_content_type = (
        declared_content_type
        or "application/octet-stream"
    ).lower().split(";")[0].strip()

    if (
        normalized_content_type
        not in ALLOWED_CONTENT_TYPES
    ):
        raise MediaValidationError(
            code="UNSUPPORTED_CONTENT_TYPE",
            message=(
                "The declared media content type "
                "is not supported."
            ),
        )

    probe = probe_media(path)

    format_name = (
        probe
        .get("format", {})
        .get("format_name", "")
    )

    detected_formats = {
        value.strip().lower()
        for value in format_name.split(",")
        if value.strip()
    }

    allowed_formats = EXTENSION_FORMATS.get(
        normalized_extension,
        set(),
    )

    if not detected_formats.intersection(
        allowed_formats
    ):
        raise MediaValidationError(
            code="MEDIA_TYPE_MISMATCH",
            message=(
                "The file extension does not match "
                "the detected media format."
            ),
        )

    duration = get_media_duration(probe)

    if duration > MAX_MEDIA_DURATION_SECONDS:
        raise MediaValidationError(
            code="MEDIA_TOO_LONG",
            message=(
                "The media duration exceeds the "
                "maximum allowed duration."
            ),
        )

    audio_streams = [
        stream
        for stream in probe["streams"]
        if stream.get("codec_type") == "audio"
    ]

    video_streams = [
        stream
        for stream in probe["streams"]
        if stream.get("codec_type") == "video"
    ]

    if require_audio and not audio_streams:
        raise MediaValidationError(
            code="MISSING_AUDIO_STREAM",
            message=(
                "The uploaded media requires an "
                "audio stream when manual_text "
                "is not provided."
            ),
        )

    for stream in video_streams:
        width = int(
            stream.get("width") or 0
        )

        height = int(
            stream.get("height") or 0
        )

        if width <= 0 or height <= 0:
            raise MediaValidationError(
                code="INVALID_VIDEO_DIMENSIONS",
                message=(
                    "The video dimensions could "
                    "not be validated."
                ),
            )

        if (
            width > MAX_VIDEO_WIDTH
            or height > MAX_VIDEO_HEIGHT
            or width * height > MAX_VIDEO_PIXELS
        ):
            raise MediaValidationError(
                code="VIDEO_RESOLUTION_TOO_LARGE",
                message=(
                    "The video resolution exceeds "
                    "the maximum allowed resolution."
                ),
            )

    return {
        "duration_seconds": duration,
        "detected_formats": sorted(
            detected_formats
        ),
        "content_type": normalized_content_type,
        "has_audio": bool(audio_streams),
        "has_video": bool(video_streams),
        "video_streams": [
            {
                "codec": stream.get(
                    "codec_name"
                ),
                "width": stream.get("width"),
                "height": stream.get("height"),
            }
            for stream in video_streams
        ],
        "audio_streams": [
            {
                "codec": stream.get(
                    "codec_name"
                ),
                "channels": stream.get(
                    "channels"
                ),
                "sample_rate": stream.get(
                    "sample_rate"
                ),
            }
            for stream in audio_streams
        ],
    }