import pytest

import app.translate as translate_module
from app.translate import (
    TranslationValidationError,
    validate_translation_script,
)


def test_rejects_arabic_text_in_french_translation():
    valid, reason = validate_translation_script(
        source_text="نقدم لكم أطباق تونسية",
        translated_text="نقدم لكم أطباق تونسية",
        target_language="french",
    )

    assert valid is False
    assert reason == "expected_latin_script"


def test_accepts_french_translation_of_arabic_text():
    valid, reason = validate_translation_script(
        source_text="مرحبا بكم في باريس",
        translated_text="Bienvenue à Paris",
        target_language="french",
    )

    assert valid is True
    assert reason is None


def test_accepts_arabic_translation():
    valid, reason = validate_translation_script(
        source_text="Welcome to Paris",
        translated_text="مرحبا بكم في باريس",
        target_language="arabic",
    )

    assert valid is True
    assert reason is None


def test_retries_invalid_translation_once(
    monkeypatch,
):
    responses = iter(
        [
            "نقدم لكم أطباق تونسية",
            "Nous vous proposons des plats tunisiens",
        ]
    )

    calls = []

    def fake_request_translation(
        text,
        target_language,
        *,
        strict,
    ):
        calls.append(strict)
        return next(responses)

    monkeypatch.setattr(
        translate_module,
        "request_translation",
        fake_request_translation,
    )

    result = translate_module.translate_text(
        "نقدم لكم أطباق تونسية",
        "french",
    )

    assert result == (
        "Nous vous proposons des plats tunisiens"
    )
    assert calls == [False, True]


def test_rejects_after_two_invalid_attempts(
    monkeypatch,
):
    monkeypatch.setattr(
        translate_module,
        "request_translation",
        lambda *args, **kwargs: "مرحبا",
    )

    with pytest.raises(
        TranslationValidationError
    ):
        translate_module.translate_text(
            "مرحبا",
            "french",
        )