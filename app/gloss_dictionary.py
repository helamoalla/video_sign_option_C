from pathlib import Path
import re
import unicodedata

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SIGML_ROOT = PROJECT_ROOT / "external" / "alsl_avatar" / "data" / "sigml"
LANGUAGE_FOLDER_MAP = {
    "lsf": "LSF", "fr": "LSF", "french": "LSF",
    "dgs": "DGS", "de": "DGS", "german": "DGS",
    "bsl": "BSL", "en": "BSL", "english": "BSL",
    "gsl": "GSL", "el": "GSL", "greek": "GSL",
    "lsa": "lsa", "ar": "lsa", "arabic": "lsa",
}


def normalize_language(language: str) -> str:
    return (language or "lsa").lower().strip()


def get_sigml_dir(language: str) -> Path:
    folder = SIGML_ROOT / LANGUAGE_FOLDER_MAP.get(normalize_language(language), normalize_language(language))
    return folder if folder.exists() else SIGML_ROOT


def decode_unicode_sigml_name(name: str) -> str:
    if "#U" not in name:
        return name

    chars = []
    for part in name.split("#U"):
        if part:
            try:
                chars.append(chr(int(part[:4], 16)))
            except ValueError:
                pass
    return "".join(chars)


def normalize_token(text: str) -> str:
    text = decode_unicode_sigml_name(str(text))
    text = text.lower().strip()

    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))

    text = text.replace("-", "_").replace(" ", "_")
    text = re.sub(r"[^a-z0-9_\u0370-\u03FF\u0600-\u06FF]", "", text)

    return text


def load_dictionary(language: str):
    sigml_dir = get_sigml_dir(language)
    dictionary = []

    for path in sigml_dir.rglob("*.sigml"):
        stem = decode_unicode_sigml_name(path.stem)
        dictionary.append(stem)

        parts = re.split(r"[_\-\s]+", stem)
        dictionary.extend([p for p in parts if len(p) > 1])

        if "_" in stem:
            dictionary.append(stem.split("_")[0])
            dictionary.append(stem.split("_")[-1])

    return list(dict.fromkeys(dictionary))