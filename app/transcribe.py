from pathlib import Path
import whisper

_model = None


def load_whisper_model(model_name: str = "small"):
    global _model
    if _model is None:
        _model = whisper.load_model(model_name)
    return _model


def transcribe_video(media_path: str, model_name: str = "small"):
    model = load_whisper_model(model_name)
    result = model.transcribe(str(media_path))

    return {
        "text": result["text"],
        "language": result["language"],
        "segments": result["segments"]
    }