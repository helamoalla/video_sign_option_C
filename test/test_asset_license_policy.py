import pytest

from app.avatar.license_policy import (
    ProviderNotApprovedForProductionError,
    ensure_provider_is_approved,
)


@pytest.mark.parametrize(
    "provider",
    [
        "cwasa_arabic",
        "cwasa_multilang",
    ],
)
def test_production_rejects_prototype_provider(
    provider,
    monkeypatch,
):
    monkeypatch.setenv(
        "APP_ENV",
        "production",
    )
    monkeypatch.setenv(
        "ALLOW_RESEARCH_ASSETS",
        "false",
    )

    with pytest.raises(
        ProviderNotApprovedForProductionError
    ):
        ensure_provider_is_approved(
            provider
        )


def test_development_allows_prototype_provider(
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

    ensure_provider_is_approved(
        "cwasa_multilang"
    )


def test_unknown_environment_fails_closed(
    monkeypatch,
):
    monkeypatch.setenv(
        "APP_ENV",
        "staging",
    )
    monkeypatch.setenv(
        "ALLOW_RESEARCH_ASSETS",
        "false",
    )

    with pytest.raises(
        ProviderNotApprovedForProductionError
    ):
        ensure_provider_is_approved(
            "cwasa_multilang"
        )


def test_future_licensed_provider_is_not_blocked(
    monkeypatch,
):
    monkeypatch.setenv(
        "APP_ENV",
        "production",
    )
    monkeypatch.setenv(
        "ALLOW_RESEARCH_ASSETS",
        "false",
    )

    ensure_provider_is_approved(
        "licensed_video"
    )