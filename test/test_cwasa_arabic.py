from pathlib import Path

from app.avatar.cwasa_arabic_provider import (
    CwasaArabicProvider,
)
from app.avatar.cwasa_multilang_provider import (
    CwasaMultilangProvider,
)
from app.avatar.provider_factory import (
    get_avatar_provider,
)


def test_arabic_provider_uses_multilang_provider():
    provider = CwasaArabicProvider()

    assert isinstance(
        provider,
        CwasaMultilangProvider,
    )


def test_factory_returns_arabic_provider(
    monkeypatch,
):
    monkeypatch.setenv(
        "APP_ENV",
        "development",
    )
    monkeypatch.setenv(
        "ALLOW_RESEARCH_ASSETS",
        "true",
    )

    provider = get_avatar_provider(
        "cwasa_arabic"
    )

    assert isinstance(
        provider,
        CwasaArabicProvider,
    )


def test_arabic_provider_accepts_validated_glosses(
    monkeypatch,
    tmp_path: Path,
):
    captured = {}

    def fake_generate(
        self,
        text: str,
        language: str,
        output_path: str,
        glosses: list[str] | None = None,
    ):
        captured["text"] = text
        captured["language"] = language
        captured["output_path"] = output_path
        captured["glosses"] = glosses

        return output_path

    monkeypatch.setattr(
        CwasaMultilangProvider,
        "generate",
        fake_generate,
    )

    provider = CwasaArabicProvider()

    output_path = (
        tmp_path / "arabic-avatar.mp4"
    )

    result = provider.generate(
        text="مرحبا",
        language="lsa",
        output_path=str(output_path),
        glosses=["مرحبا"],
    )

    assert result == str(output_path)
    assert captured == {
        "text": "مرحبا",
        "language": "lsa",
        "output_path": str(output_path),
        "glosses": ["مرحبا"],
    }