from unittest.mock import Mock

from app import transcribe


def test_transcribe_video_uses_whisper_result(
    monkeypatch,
    tmp_path,
):
    media_path = tmp_path / "sample.mp3"
    media_path.write_bytes(b"test media placeholder")

    whisper_result = {
        "text": "Hello world",
        "language": "en",
        "segments": [
            {
                "start": 0.0,
                "end": 1.5,
                "text": "Hello world",
            }
        ],
    }

    model = Mock()
    model.transcribe.return_value = whisper_result

    monkeypatch.setattr(
        transcribe,
        "load_whisper_model",
        lambda model_name="small": model,
    )

    result = transcribe.transcribe_video(
        str(media_path)
    )

    assert result["text"] == "Hello world"
    assert result["language"] == "en"
    assert result["segments"] == whisper_result["segments"]

    model.transcribe.assert_called_once_with(
        str(media_path)
    )


def test_whisper_model_is_cached(
    monkeypatch,
):
    fake_model = Mock()
    load_model = Mock(return_value=fake_model)

    monkeypatch.setattr(
        transcribe.whisper,
        "load_model",
        load_model,
    )

    monkeypatch.setattr(
        transcribe,
        "_model",
        None,
    )

    first = transcribe.load_whisper_model("small")
    second = transcribe.load_whisper_model("small")

    assert first is fake_model
    assert second is fake_model
    load_model.assert_called_once_with("small")