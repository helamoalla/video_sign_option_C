import re
import unicodedata
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

SIGML_ROOT = (
    PROJECT_ROOT
    / "external"
    / "alsl_avatar"
    / "data"
    / "sigml"
)


# Convert accepted names and aliases to one canonical code.
LANGUAGE_ALIASES = {
    # French Sign Language
    "lsf": "lsf",
    "fr": "lsf",
    "french": "lsf",
    "france": "lsf",

    # German Sign Language
    "dgs": "dgs",
    "de": "dgs",
    "german": "dgs",
    "germany": "dgs",

    # British Sign Language
    "bsl": "bsl",
    "en": "bsl",
    "english": "bsl",
    "uk": "bsl",

    # Greek Sign Language
    "gsl": "gsl",
    "el": "gsl",
    "greek": "gsl",
    "greece": "gsl",

    # Arabic Sign Language
    "lsa": "lsa",
    "ar": "lsa",
    "arabic": "lsa",
}


# Canonical language code to its exact asset directory.
LANGUAGE_FOLDER_MAP = {
    "lsf": "LSF",
    "dgs": "DGS",
    "bsl": "BSL",
    "gsl": "GSL",
    "lsa": "lsa",
}


def normalize_language(language: str) -> str:
    """
    Convert a language name or alias to a canonical sign-language code.

    Examples:
        french -> lsf
        fr     -> lsf
        arabic -> lsa
    """

    normalized = (language or "").lower().strip()

    if not normalized:
        raise ValueError(
            "Sign language cannot be empty."
        )

    canonical_language = LANGUAGE_ALIASES.get(
        normalized
    )

    if canonical_language is None:
        supported = ", ".join(
            sorted(LANGUAGE_FOLDER_MAP)
        )

        raise ValueError(
            f"Unsupported sign language: {language}. "
            f"Supported languages: {supported}"
        )

    return canonical_language


def get_supported_sign_languages() -> list[str]:
    """Return the sign languages supported by the code."""

    return sorted(LANGUAGE_FOLDER_MAP.keys())


def get_sigml_dir(language: str) -> Path:
    """
    Return the exact SiGML directory for a language.

    It never falls back to the global SiGML directory because
    that could mix assets belonging to different languages.
    """

    canonical_language = normalize_language(
        language
    )

    folder_name = LANGUAGE_FOLDER_MAP[
        canonical_language
    ]

    language_directory = (
        SIGML_ROOT / folder_name
    )

    if not SIGML_ROOT.is_dir():
        raise FileNotFoundError(
            f"SiGML root directory does not exist: "
            f"{SIGML_ROOT}"
        )

    if not language_directory.is_dir():
        raise FileNotFoundError(
            "No SiGML asset directory exists for "
            f"{canonical_language}: {language_directory}"
        )

    return language_directory


def get_sigml_files(
    language: str,
) -> list[Path]:
    """
    Return all SiGML files for one language.

    Raise an explicit error when the language directory exists
    but contains no usable assets.
    """

    language_directory = get_sigml_dir(
        language
    )

    sigml_files = sorted(
        language_directory.rglob("*.sigml")
    )

    if not sigml_files:
        canonical_language = normalize_language(
            language
        )

        raise FileNotFoundError(
            "The SiGML directory for "
            f"{canonical_language} contains no .sigml files: "
            f"{language_directory}"
        )

    return sigml_files


def has_language_assets(language: str) -> bool:
    """
    Return True only when the requested language has at least
    one SiGML asset in its own isolated directory.
    """

    try:
        return bool(get_sigml_files(language))
    except (
        ValueError,
        FileNotFoundError,
    ):
        return False


def get_language_asset_count(
    language: str,
) -> int:
    """Return the number of SiGML files for a language."""

    try:
        return len(get_sigml_files(language))
    except (
        ValueError,
        FileNotFoundError,
    ):
        return 0


def decode_unicode_sigml_name(
    name: str,
) -> str:
    """
    Decode filenames that contain #U hexadecimal Unicode
    sequences.
    """

    if "#U" not in name:
        return name

    characters = []

    for part in name.split("#U"):
        if not part:
            continue

        try:
            characters.append(
                chr(int(part[:4], 16))
            )
        except (
            ValueError,
            TypeError,
        ):
            continue

    return "".join(characters)


def normalize_token(text: str) -> str:
    """
    Normalize a gloss or SiGML filename for matching.
    """

    decoded_text = decode_unicode_sigml_name(
        str(text)
    )

    normalized_text = (
        decoded_text
        .lower()
        .strip()
    )

    normalized_text = unicodedata.normalize(
        "NFKD",
        normalized_text,
    )

    normalized_text = "".join(
        character
        for character in normalized_text
        if not unicodedata.combining(character)
    )

    normalized_text = (
        normalized_text
        .replace("-", "_")
        .replace(" ", "_")
    )

    normalized_text = re.sub(
        r"[^a-z0-9_\u0370-\u03FF\u0600-\u06FF]",
        "",
        normalized_text,
    )

    return normalized_text


def load_dictionary(
    language: str,
) -> list[str]:
    """
    Load gloss candidates only from the requested language's
    isolated SiGML directory.
    """

    dictionary = []

    for path in get_sigml_files(language):
        decoded_stem = decode_unicode_sigml_name(
            path.stem
        )

        if decoded_stem:
            dictionary.append(decoded_stem)

        parts = re.split(
            r"[_\-\s]+",
            decoded_stem,
        )

        dictionary.extend(
            part
            for part in parts
            if len(part) > 1
        )

        if "_" in decoded_stem:
            first_part = decoded_stem.split(
                "_"
            )[0]

            last_part = decoded_stem.split(
                "_"
            )[-1]

            if first_part:
                dictionary.append(first_part)

            if last_part:
                dictionary.append(last_part)

    # Remove duplicates while preserving insertion order.
    return list(dict.fromkeys(dictionary))