import json
from pathlib import Path

from app.subtitles import (
    format_srt_time,
    format_vtt_time,
    generate_subtitles,
)


def test_format_srt_time():
    assert (
        format_srt_time(3661.250)
        == "01:01:01,250"
    )


def test_format_vtt_time():
    assert (
        format_vtt_time(3661.250)
        == "01:01:01.250"
    )


def test_generate_subtitles(
    tmp_path: Path,
):
    transcription = {
        "language": "en",
        "text": "Hello world",
        "segments": [
            {
                "start": 0.0,
                "end": 1.25,
                "text": " Hello ",
            },
            {
                "start": 1.25,
                "end": 2.5,
                "text": " world ",
            },
        ],
    }

    output_dir = tmp_path / "subtitles"

    result = generate_subtitles(
        result=transcription,
        output_dir=output_dir,
        file_id="test-video",
    )

    json_path = Path(result["json_path"])
    srt_path = Path(result["srt_path"])
    vtt_path = Path(result["vtt_path"])

    assert json_path.is_file()
    assert srt_path.is_file()
    assert vtt_path.is_file()

    data = json.loads(
        json_path.read_text(
            encoding="utf-8"
        )
    )

    assert data["language"] == "en"
    assert data["text"] == "Hello world"
    assert (
        data["video_path"]
        == "videos/test-video.mp4"
    )

    assert len(data["segments"]) == 2
    assert data["segments"][0] == {
        "id": 1,
        "start": 0.0,
        "end": 1.25,
        "text": "Hello",
    }

    srt_content = srt_path.read_text(
        encoding="utf-8"
    )

    assert "00:00:00,000 --> 00:00:01,250" in srt_content
    assert "00:00:01,250 --> 00:00:02,500" in srt_content
    assert "Hello" in srt_content
    assert "world" in srt_content

    vtt_content = vtt_path.read_text(
        encoding="utf-8"
    )

    assert vtt_content.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:01.250" in vtt_content
    assert "00:00:01.250 --> 00:00:02.500" in vtt_content


def test_generate_subtitles_with_no_segments(
    tmp_path: Path,
):
    transcription = {
        "language": "en",
        "text": "",
        "segments": [],
    }

    result = generate_subtitles(
        result=transcription,
        output_dir=tmp_path / "empty",
        file_id="empty-video",
    )

    assert result["data"]["segments"] == []

    srt_content = Path(
        result["srt_path"]
    ).read_text(encoding="utf-8")

    vtt_content = Path(
        result["vtt_path"]
    ).read_text(encoding="utf-8")

    assert srt_content == ""
    assert vtt_content == "WEBVTT\n\n"