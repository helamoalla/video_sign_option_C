import json
from pathlib import Path

from app.asset_readiness import (
    calculate_bundle_sha256,
    list_sigml_files,
    validate_sign_asset_bundle,
)


def create_test_bundle(tmp_path: Path) -> tuple[Path, Path]:
    asset_root = tmp_path / "sigml"
    lsf_directory = asset_root / "lsf"
    lsf_directory.mkdir(parents=True)

    (lsf_directory / "bonjour.sigml").write_text(
        "<sigml>bonjour</sigml>",
        encoding="utf-8",
    )

    files = list_sigml_files(asset_root)
    manifest = {
        "bundle_version": "test-bundle-v1",
        "bundle_sha256": calculate_bundle_sha256(
            asset_root,
            files,
        ),
        "languages": {
            "lsf": {
                "folder": "lsf",
                "expected_files": 1,
            }
        },
    }

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    return asset_root, manifest_path


def test_valid_pinned_bundle_is_ready(tmp_path: Path):
    asset_root, manifest_path = create_test_bundle(tmp_path)

    report = validate_sign_asset_bundle(
        asset_root=asset_root,
        manifest_path=manifest_path,
    )

    assert report["ready"] is True
    assert report["code"] == "SIGN_ASSETS_READY"


def test_missing_asset_directory_is_not_ready(tmp_path: Path):
    _, manifest_path = create_test_bundle(tmp_path)

    report = validate_sign_asset_bundle(
        asset_root=tmp_path / "missing",
        manifest_path=manifest_path,
    )

    assert report["ready"] is False
    assert report["code"] == "SIGN_ASSETS_NOT_READY"


def test_modified_asset_fails_checksum(tmp_path: Path):
    asset_root, manifest_path = create_test_bundle(tmp_path)

    (asset_root / "lsf" / "bonjour.sigml").write_text(
        "<sigml>modified</sigml>",
        encoding="utf-8",
    )

    report = validate_sign_asset_bundle(
        asset_root=asset_root,
        manifest_path=manifest_path,
    )

    assert report["ready"] is False
    assert any(
        "checksum" in problem.lower()
        for problem in report["problems"]
    )