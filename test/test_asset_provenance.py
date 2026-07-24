import json
from pathlib import Path

from app.asset_license import (
    LicenseDecision,
    assess_license,
)


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

MANIFEST_PATH = (
    PROJECT_ROOT
    / "data"
    / "sign_languages"
    / "asset_provenance.json"
)


def load_manifest() -> dict:
    return json.loads(
        MANIFEST_PATH.read_text(
            encoding="utf-8"
        )
    )


def test_provenance_manifest_exists():
    assert MANIFEST_PATH.is_file()


def test_every_asset_has_required_metadata():
    manifest = load_manifest()

    assert manifest["schema_version"] == 1
    assert manifest["assets"]

    for asset_name, metadata in (
        manifest["assets"].items()
    ):
        assert metadata.get("license"), (
            f"{asset_name} has no licence"
        )

        assert metadata.get("evidence"), (
            f"{asset_name} has no evidence"
        )

        assert isinstance(
            metadata.get(
                "production_allowed"
            ),
            bool,
        )


def test_local_evidence_files_exist():
    manifest = load_manifest()

    for asset_name, metadata in (
        manifest["assets"].items()
    ):
        evidence = metadata["evidence"]

        if evidence.startswith(
            ("http://", "https://")
        ):
            continue

        evidence_path = (
            PROJECT_ROOT / evidence
        )

        assert evidence_path.is_file(), (
            f"Evidence file is missing for "
            f"{asset_name}: {evidence}"
        )


def test_production_flag_matches_licence_decision():
    manifest = load_manifest()

    for asset_name, metadata in (
        manifest["assets"].items()
    ):
        assessment = assess_license(
            metadata["license"],
            evidence=metadata["evidence"],
        )

        expected_allowed = (
            assessment.decision
            == LicenseDecision.ALLOWED
        )

        assert (
            metadata["production_allowed"]
            == expected_allowed
        ), (
            f"{asset_name} has an inconsistent "
            "production_allowed value"
        )


def test_prototype_provider_is_documented():
    manifest = load_manifest()

    assert (
        manifest["prototype_provider"]
        == "cwasa_multilang"
    )

    assert (
        manifest["assets"][
            "cwasa_multilang"
        ]["production_allowed"]
        is False
    )


def test_cyrkil_replacement_is_documented():
    manifest = load_manifest()

    assert (
        manifest["production_provider"]
        == "licensed_video"
    )

    assert "Cyrkil" in (
        manifest["production_replacement"]
    )