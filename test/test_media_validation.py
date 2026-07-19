import shutil
import subprocess
from pathlib import Path

import pytest

from app.media_validation import (
    MediaValidationError,
    sanitize_media,
    validate_media,
)


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def require_ffmpeg():
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not installed")

    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe is not installed")


@pytest.fixture
def valid_mp4(tmp_path: Path) -> Path:
    output = tmp_path / "valid.mp4"

    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-metadata",
            "title=Private upload title",
            "-shortest",
            str(output),
        ],
        check=True,
    )

    return output


def test_rejects_fake_mp4(
    tmp_path: Path,
):
    fake_video = tmp_path / "fake.mp4"
    fake_video.write_bytes(
        b"This is not a real video."
    )

    with pytest.raises(
        MediaValidationError
    ) as error:
        validate_media(
            path=fake_video,
            extension=".mp4",
            declared_content_type="video/mp4",
            require_audio=False,
        )

    assert error.value.code == "INVALID_MEDIA"


def test_rejects_extension_mismatch(
    tmp_path: Path,
):
    webm_path = tmp_path / "original.webm"

    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=1",
            "-c:v",
            "libvpx",
            str(webm_path),
        ],
        check=True,
    )

    disguised_path = tmp_path / "disguised.mp4"
    webm_path.rename(disguised_path)

    with pytest.raises(
        MediaValidationError
    ) as error:
        validate_media(
            path=disguised_path,
            extension=".mp4",
            declared_content_type="video/mp4",
            require_audio=False,
        )

    assert (
        error.value.code
        == "MEDIA_TYPE_MISMATCH"
    )


def test_valid_media_is_accepted(
    valid_mp4: Path,
):
    result = validate_media(
        path=valid_mp4,
        extension=".mp4",
        declared_content_type="video/mp4",
        require_audio=True,
    )

    assert result["has_video"] is True
    assert result["has_audio"] is True
    assert result["duration_seconds"] > 0


def test_sanitized_media_remains_valid(
    valid_mp4: Path,
):
    sanitize_media(valid_mp4)

    result = validate_media(
        path=valid_mp4,
        extension=".mp4",
        declared_content_type="video/mp4",
        require_audio=True,
    )

    assert result["has_video"] is True
    assert result["has_audio"] is True