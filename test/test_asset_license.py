import pytest

from app.asset_license import (
    LicenseDecision,
    assess_license,
    require_production_license,
)


def test_owned_asset_with_evidence_is_allowed():
    assessment = assess_license(
        "own-recording",
        evidence="cyrkil-release-001",
    )

    assert (
        assessment.decision
        == LicenseDecision.ALLOWED
    )


def test_ofl_font_with_evidence_is_allowed():
    assessment = assess_license(
        "ofl-1.1",
        evidence=(
            "licenses/IBM-Plex-OFL-1.1.txt"
        ),
    )

    assert (
        assessment.decision
        == LicenseDecision.ALLOWED
    )


@pytest.mark.parametrize(
    "license_id",
    [
        "research-only",
        "cc-by-nc-4.0",
        "non-commercial",
    ],
)
def test_noncommercial_assets_are_denied(
    license_id,
):
    assessment = assess_license(
        license_id,
        evidence="docs/DATA_SOURCES.md",
    )

    assert (
        assessment.decision
        == LicenseDecision.DENIED
    )


def test_missing_license_is_denied():
    assessment = assess_license(
        "",
        evidence=None,
    )

    assert (
        assessment.decision
        == LicenseDecision.DENIED
    )


def test_missing_evidence_is_denied():
    assessment = assess_license(
        "proprietary",
        evidence=None,
    )

    assert (
        assessment.decision
        == LicenseDecision.DENIED
    )


def test_unknown_license_requires_review():
    assessment = assess_license(
        "unknown-license",
        evidence="some-document",
    )

    assert (
        assessment.decision
        == LicenseDecision.REVIEW_REQUIRED
    )


def test_requirement_raises_for_invalid_asset():
    with pytest.raises(ValueError):
        require_production_license(
            "cc-by-nc-4.0",
            evidence="upstream-readme",
        )