from dataclasses import dataclass
from enum import Enum


class LicenseDecision(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    REVIEW_REQUIRED = "review_required"

COMMERCIAL_OK = {
    "proprietary",
    "own-recording",
    "cc0-1.0",
    "cc-by-4.0",
    "mit",
    "apache-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "ofl-1.1",
    "elra-commercial",
}

COMMERCIAL_WITH_OBLIGATIONS = {
    "cc-by-sa-4.0",
    "gpl-3.0-only",
    "gpl-3.0-or-later",
    "agpl-3.0-only",
    "agpl-3.0-or-later",
}

NON_COMMERCIAL = {
    "cc-by-nc-4.0",
    "cc-by-nc-sa-4.0",
    "cc-by-nc-nd-4.0",
    "research",
    "research-only",
    "academic",
    "non-commercial",
}

ALIASES = {
    "own_recording": "own-recording",
    "cc0": "cc0-1.0",
    "cc-by": "cc-by-4.0",
    "cc-by-sa": "cc-by-sa-4.0",
    "cc-by-nc": "cc-by-nc-4.0",
    "sil-ofl": "ofl-1.1",
    "ofl": "ofl-1.1",
    "gplv3": "gpl-3.0-only",
}


@dataclass(frozen=True)
class LicenseAssessment:
    decision: LicenseDecision
    license_id: str
    message: str


def normalize_license(
    license_string: str | None,
) -> str:
    license_id = (
        license_string or ""
    ).strip().lower()

    return ALIASES.get(
        license_id,
        license_id,
    )


def assess_license(
    license_string: str | None,
    *,
    evidence: str | None,
) -> LicenseAssessment:
    license_id = normalize_license(
        license_string
    )

    if not license_id:
        return LicenseAssessment(
            decision=LicenseDecision.DENIED,
            license_id="",
            message="The asset has no documented licence.",
        )

    if license_id in NON_COMMERCIAL:
        return LicenseAssessment(
            decision=LicenseDecision.DENIED,
            license_id=license_id,
            message=(
                f"{license_id} is not approved for "
                "commercial production."
            ),
        )

    if license_id in COMMERCIAL_WITH_OBLIGATIONS:
        return LicenseAssessment(
            decision=LicenseDecision.REVIEW_REQUIRED,
            license_id=license_id,
            message=(
                f"{license_id} requires a legal and "
                "distribution-obligation review."
            ),
        )

    if license_id not in COMMERCIAL_OK:
        return LicenseAssessment(
            decision=LicenseDecision.REVIEW_REQUIRED,
            license_id=license_id,
            message=(
                f"Unknown licence: {license_id}."
            ),
        )

    if not evidence or not evidence.strip():
        return LicenseAssessment(
            decision=LicenseDecision.DENIED,
            license_id=license_id,
            message=(
                "The licence is acceptable, but evidence "
                "or a contract reference is missing."
            ),
        )

    return LicenseAssessment(
        decision=LicenseDecision.ALLOWED,
        license_id=license_id,
        message="Approved for production.",
    )


def require_production_license(
    license_string: str | None,
    *,
    evidence: str | None,
) -> None:
    assessment = assess_license(
        license_string,
        evidence=evidence,
    )

    if (
        assessment.decision
        != LicenseDecision.ALLOWED
    ):
        raise ValueError(
            assessment.message
        )