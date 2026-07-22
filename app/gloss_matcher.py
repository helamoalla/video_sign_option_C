from app.gloss_dictionary import (
    load_dictionary,
    normalize_language,
    normalize_token,
)


STOPWORDS = {
    # English
    "a",
    "an",
    "the",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "and",
    "or",

    # French
    "à",
    "de",
    "du",
    "la",
    "le",
    "les",
    "des",
    "un",
    "une",
    "et",
    "ou",
    "en",

    # German
    "der",
    "die",
    "das",
    "und",
    "mit",
    "für",
    "von",
    "zu",
    "ein",
    "eine",

    # Arabic
    "في",
    "من",
    "على",
    "الى",
    "إلى",
    "عن",
    "و",
    "مع",
    "هذا",
    "هذه",
    "كم",
}


SYNONYMS = {
    "welcome": [
        "hello",
        "hi",
        "greet",
        "greeting",
    ],
    "accueille": [
        "bonjour",
        "bienvenue",
        "salut",
    ],
    "مرحبا": [
        "اهلا",
        "أهلا",
        "سلام",
    ],

    "food": [
        "meal",
        "dish",
        "cuisine",
        "restaurant",
    ],
    "repas": [
        "manger",
        "plat",
        "nourriture",
    ],
    "وجبة": [
        "اكل",
        "أكل",
        "طعام",
    ],

    "tunisia": [
        "tunis",
        "tunisian",
    ],
    "tunisie": [
        "tunis",
        "tunisien",
    ],
    "تونس": [
        "تونسي",
        "تونسية",
    ],

    "paris": [
        "france",
    ],
    "باريس": [
        "بباريس",
        "وباريس",
    ],

    "heart": [
        "love",
        "centre",
        "center",
    ],
    "coeur": [
        "amour",
        "centre",
    ],
    "قلب": [
        "حب",
        "وسط",
    ],

    "come": [
        "visit",
        "join",
        "go",
    ],
    "venez": [
        "venir",
        "visiter",
    ],
    "تعالوا": [
        "زوروا",
        "زيارة",
    ],

    "journey": [
        "travel",
        "trip",
    ],
    "voyage": [
        "visite",
        "trajet",
    ],
    "رحلة": [
        "سفر",
        "زيارة",
    ],

    "authentic": [
        "traditional",
        "real",
        "original",
    ],
    "authentique": [
        "tradition",
        "original",
    ],
    "أصيل": [
        "تقليدي",
        "اصلي",
        "أصلي",
    ],
}


ARABIC_PREFIXES = {
    "و",  # and
    "ف",  # then/so
    "ب",  # in/with/at
    "ك",  # like/as
    "ل",  # to/for
}


def is_arabic_language(
    language: str,
) -> bool:
    try:
        return (
            normalize_language(language)
            == "lsa"
        )
    except ValueError:
        return (
            language
            or ""
        ).lower().strip() in {
            "lsa",
            "arabic",
            "ar",
        }


def get_arabic_token_variants(
    token: str,
) -> list[str]:
    """
    Generate possible dictionary forms after removing common
    attached Arabic prefixes.

    Examples:
        بباريس -> باريس
        وباريس -> باريس
        بالبيت -> البيت -> بيت

    A maximum depth prevents excessive or unsafe stripping.
    """

    normalized = normalize_token(token)

    if not normalized:
        return []

    variants = [normalized]
    queue = [
        (normalized, 0),
    ]
    seen = {
        normalized,
    }

    while queue:
        current, depth = queue.pop(0)

        if depth >= 3:
            continue

        candidates = []

        if (
            len(current) >= 4
            and current[0]
            in ARABIC_PREFIXES
        ):
            candidates.append(
                current[1:]
            )

        if (
            len(current) >= 5
            and current.startswith("ال")
        ):
            candidates.append(
                current[2:]
            )

        for candidate in candidates:
            if (
                not candidate
                or candidate in seen
            ):
                continue

            seen.add(candidate)
            variants.append(candidate)
            queue.append(
                (
                    candidate,
                    depth + 1,
                )
            )

    return variants


def expand_token(
    token: str,
) -> list[str]:
    normalized_token = normalize_token(
        token
    )

    if not normalized_token:
        return []

    expanded = [
        normalized_token,
    ]

    for key, values in SYNONYMS.items():
        normalized_key = normalize_token(
            key
        )

        normalized_values = [
            normalize_token(value)
            for value in values
        ]

        if normalized_token == normalized_key:
            expanded.extend(
                normalized_values
            )

        if normalized_token in normalized_values:
            expanded.append(
                normalized_key
            )
            expanded.extend(
                normalized_values
            )

    return list(
        dict.fromkeys(expanded)
    )


def clean_tokens(
    text: str,
    language: str | None = None,
) -> list[str]:
    tokens = []
    arabic = bool(
        language
        and is_arabic_language(language)
    )

    for word in (text or "").split():
        normalized_word = normalize_token(
            word
        )

        if not normalized_word:
            continue

        variants = [
            normalized_word,
        ]

        if arabic:
            variants = (
                get_arabic_token_variants(
                    normalized_word
                )
            )

        for variant in variants:
            if (
                len(variant) >= 3
                and variant not in STOPWORDS
            ):
                tokens.extend(
                    expand_token(variant)
                )

    return list(
        dict.fromkeys(tokens)
    )


def get_high_confidence_gloss_matches(
    text: str,
    language: str,
) -> list[str]:
    """
    Return deterministic exact dictionary matches.

    For Arabic, common attached prefixes are removed, but a
    result is accepted only when it exists in the requested
    sign-language dictionary.
    """

    dictionary = load_dictionary(
        language
    )

    normalized_dictionary = {
        normalize_token(gloss): gloss
        for gloss in dictionary
        if normalize_token(gloss)
    }

    matches = []
    arabic = is_arabic_language(
        language
    )

    for word in (text or "").split():
        normalized_word = normalize_token(
            word
        )

        if not normalized_word:
            continue

        variants = [
            normalized_word,
        ]

        if arabic:
            variants = (
                get_arabic_token_variants(
                    normalized_word
                )
            )

        for variant in variants:
            gloss = (
                normalized_dictionary.get(
                    variant
                )
            )

            if gloss is None:
                continue

            if gloss not in matches:
                matches.append(gloss)

            # Prefer the first, least-stripped valid form.
            break

    return matches


def get_best_gloss_matches(
    text: str,
    language: str,
    max_results: int = 20,
) -> list[str]:
    words = clean_tokens(
        text,
        language,
    )

    dictionary = load_dictionary(
        language
    )

    scored = []

    for gloss in dictionary:
        normalized_gloss = normalize_token(
            gloss
        )

        if (
            len(normalized_gloss) < 3
            or normalized_gloss
            in STOPWORDS
        ):
            continue

        score = 0

        for word in words:
            if word == normalized_gloss:
                score += 30

            elif (
                len(word) >= 4
                and word in normalized_gloss
            ):
                score += 10

            elif (
                len(normalized_gloss) >= 4
                and normalized_gloss in word
            ):
                score += 8

        if score > 0:
            scored.append(
                (
                    score,
                    gloss,
                )
            )

    scored.sort(
        reverse=True,
        key=lambda item: item[0],
    )

    results = []
    seen = set()

    for _, gloss in scored:
        normalized_gloss = normalize_token(
            gloss
        )

        if normalized_gloss in seen:
            continue

        seen.add(normalized_gloss)
        results.append(gloss)

        if len(results) >= max_results:
            break

    return results