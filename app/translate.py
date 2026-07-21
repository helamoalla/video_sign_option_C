import logging
import os
import unicodedata

from dotenv import load_dotenv
from groq import Groq


load_dotenv()

logger = logging.getLogger(__name__)


LANG_MAP = {
    "french": "French",
    "arabic": "Arabic",
    "english": "English",
    "german": "German",
    "greek": "Greek",
    "italian": "Italian",
    "spanish": "Spanish",
}

LANGUAGE_ALIASES = {
    "fr": "french",
    "ar": "arabic",
    "en": "english",
    "de": "german",
    "el": "greek",
    "it": "italian",
    "es": "spanish",
}

TARGET_SCRIPT = {
    "french": "LATIN",
    "arabic": "ARABIC",
    "english": "LATIN",
    "german": "LATIN",
    "greek": "GREEK",
    "italian": "LATIN",
    "spanish": "LATIN",
}


class TranslationValidationError(RuntimeError):
    """Raised when translation output uses the wrong script."""


def normalize_target_language(
    target_language: str,
) -> str:
    normalized = str(
        target_language or ""
    ).lower().strip()

    normalized = LANGUAGE_ALIASES.get(
        normalized,
        normalized,
    )

    if normalized not in LANG_MAP:
        raise ValueError(
            "Unsupported target language: "
            f"{target_language}. Supported languages: "
            f"{sorted(LANG_MAP)}"
        )

    return normalized


def character_script(
    character: str,
) -> str | None:
    """Return the Unicode script relevant to supported languages."""

    if not character.isalpha():
        return None

    unicode_name = unicodedata.name(
        character,
        "",
    )

    if "ARABIC" in unicode_name:
        return "ARABIC"

    if "GREEK" in unicode_name:
        return "GREEK"

    if "LATIN" in unicode_name:
        return "LATIN"

    return "OTHER"


def count_scripts(
    text: str,
) -> dict[str, int]:
    counts = {
        "ARABIC": 0,
        "GREEK": 0,
        "LATIN": 0,
        "OTHER": 0,
    }

    for character in str(text or ""):
        script = character_script(character)

        if script is not None:
            counts[script] += 1

    return counts


def validate_translation_script(
    source_text: str,
    translated_text: str,
    target_language: str,
) -> tuple[bool, str | None]:
    """
    Validate that translated words use the target writing system.

    This intentionally validates script rather than attempting full
    semantic language detection. It reliably prevents Arabic text from
    entering French/German/English tracks and equivalent script leaks.
    """

    normalized_language = normalize_target_language(
        target_language
    )

    candidate = str(
        translated_text or ""
    ).strip()

    if not candidate:
        return False, "translation_is_empty"

    source_counts = count_scripts(source_text)
    candidate_counts = count_scripts(candidate)

    source_letter_count = sum(
        source_counts.values()
    )

    candidate_letter_count = sum(
        candidate_counts.values()
    )

    # Numeric/punctuation-only source segments do not require a script.
    if source_letter_count == 0:
        return True, None

    if candidate_letter_count == 0:
        return False, "translation_contains_no_letters"

    expected_script = TARGET_SCRIPT[
        normalized_language
    ]

    expected_count = candidate_counts[
        expected_script
    ]

    forbidden_count = sum(
        count
        for script, count in candidate_counts.items()
        if (
            script != expected_script
            and script != "OTHER"
        )
    )

    if expected_count == 0:
        return (
            False,
            f"expected_{expected_script.lower()}_script",
        )

    if forbidden_count > 0:
        return (
            False,
            "translation_contains_foreign_script",
        )

    return True, None


def get_groq_client() -> Groq:
    api_key = os.getenv(
        "GROQ_API_KEY",
        "",
    ).strip()

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not configured."
        )

    return Groq(api_key=api_key)


def request_translation(
    text: str,
    target_language: str,
    *,
    strict: bool,
) -> str:
    normalized_language = normalize_target_language(
        target_language
    )

    target_name = LANG_MAP[
        normalized_language
    ]

    if strict:
        system_prompt = (
            "You are a professional subtitle translator. "
            f"Translate every word into {target_name}. "
            "Do not leave words or sentences in the source "
            "writing system. Transliterate proper names when "
            "necessary. Preserve the meaning and return only "
            "the translated text, without labels, quotation "
            "marks, notes, or explanations."
        )
    else:
        system_prompt = (
            "You are a professional subtitle translator. "
            f"Translate the complete input into {target_name}. "
            "Return only the translated text with no explanation."
        )

    response = get_groq_client().chat.completions.create(
        model=os.getenv(
            "GROQ_TRANSLATION_MODEL",
            "llama-3.1-8b-instant",
        ),
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": str(text),
            },
        ],
        temperature=0,
    )

    return str(
        response.choices[0].message.content
        or ""
    ).strip()


def translate_text(
    text: str,
    target_language: str,
) -> str:
    """
    Translate and validate one complete timed-subtitle segment.

    One normal attempt and one strict retry are allowed. Invalid text is
    never returned to the subtitle pipeline.
    """

    source_text = str(
        text or ""
    ).strip()

    if not source_text:
        raise ValueError(
            "Text to translate cannot be empty."
        )

    normalized_language = normalize_target_language(
        target_language
    )

    last_reason = "translation_validation_failed"

    for attempt in range(2):
        translated_text = request_translation(
            source_text,
            normalized_language,
            strict=(attempt == 1),
        )

        is_valid, reason = validate_translation_script(
            source_text=source_text,
            translated_text=translated_text,
            target_language=normalized_language,
        )

        if is_valid:
            return translated_text

        last_reason = reason or last_reason

        logger.warning(
            "Translation validation failed. "
            "target_language=%s attempt=%s reason=%s",
            normalized_language,
            attempt + 1,
            last_reason,
        )

    raise TranslationValidationError(
        "Translation output failed target-language "
        f"validation for {normalized_language}: {last_reason}."
    )