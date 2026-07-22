import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_ASSET_ROOT = (
    PROJECT_ROOT
    / "external"
    / "alsl_avatar"
    / "data"
    / "sigml"
)

DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "data"
    / "sign_languages"
    / "sign_asset_bundle.json"
)


def list_sigml_files(asset_root: Path) -> list[Path]:
    if not asset_root.is_dir():
        return []

    return sorted(
        (
            path
            for path in asset_root.rglob("*")
            if (
                path.is_file()
                and path.suffix.lower() == ".sigml"
            )
        ),
        key=lambda path: (
            path.relative_to(asset_root).as_posix()
        ),
    )


def calculate_bundle_sha256(
    asset_root: Path,
    files: list[Path],
) -> str:
    digest = hashlib.sha256()

    for path in files:
        relative_path = (
            path.relative_to(
                asset_root
            ).as_posix()
        )

        # Git can use CRLF on Windows and LF in Linux.
        # Normalize line endings to produce the same checksum.
        canonical_content = (
            path.read_bytes()
            .replace(b"\r\n", b"\n")
            .replace(b"\r", b"\n")
        )

        digest.update(
            relative_path.encode("utf-8")
        )
        digest.update(b"\0")
        digest.update(canonical_content)
        digest.update(b"\0")

    return digest.hexdigest()


def validate_sign_asset_bundle(
    *,
    asset_root: Path = DEFAULT_ASSET_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict:
    """
    Validate the pinned SiGML bundle without modifying files.

    This function never raises for missing or invalid assets. It
    returns a readiness report so application import and startup can
    remain safe while the readiness endpoint reports 503.
    """

    problems: list[str] = []

    if not manifest_path.is_file():
        return {
            "ready": False,
            "code": "SIGN_ASSET_MANIFEST_MISSING",
            "bundle_version": None,
            "languages": {},
            "problems": [
                "The pinned sign-asset manifest is missing."
            ],
        }

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {
            "ready": False,
            "code": "SIGN_ASSET_MANIFEST_INVALID",
            "bundle_version": None,
            "languages": {},
            "problems": [
                "The pinned sign-asset manifest is invalid."
            ],
        }

    bundle_version = manifest.get("bundle_version")
    expected_languages = manifest.get("languages", {})
    expected_sha256 = manifest.get("bundle_sha256")

    if not isinstance(bundle_version, str) or not bundle_version:
        problems.append("The bundle version is missing.")

    if not isinstance(expected_languages, dict):
        expected_languages = {}
        problems.append("The language manifest is invalid.")

    files = list_sigml_files(asset_root)
    language_results: dict[str, dict] = {}

    for language, configuration in expected_languages.items():
        if not isinstance(configuration, dict):
            problems.append(
                f"The manifest entry for {language} is invalid."
            )
            continue

        folder_name = configuration.get("folder")
        expected_count = configuration.get("expected_files")

        if not isinstance(folder_name, str):
            problems.append(
                f"The folder for {language} is invalid."
            )
            continue

        language_directory = asset_root / folder_name
        actual_count = len(
            list_sigml_files(language_directory)
        )
        count_matches = (
            isinstance(expected_count, int)
            and actual_count == expected_count
        )

        language_results[language] = {
            "expected_files": expected_count,
            "actual_files": actual_count,
            "ready": count_matches,
        }

        if not count_matches:
            problems.append(
                f"The {language} asset count does not match "
                "the pinned manifest."
            )

    actual_sha256 = (
        calculate_bundle_sha256(asset_root, files)
        if files
        else None
    )

    if actual_sha256 != expected_sha256:
        problems.append(
            "The sign-asset bundle checksum does not match "
            "the pinned manifest."
        )

    ready = not problems

    return {
        "ready": ready,
        "code": (
            "SIGN_ASSETS_READY"
            if ready
            else "SIGN_ASSETS_NOT_READY"
        ),
        "bundle_version": bundle_version,
        "languages": language_results,
        "problems": problems,
    }


def main() -> int:
    report = validate_sign_asset_bundle()
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())