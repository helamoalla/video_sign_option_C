from app.gloss_dictionary import load_dictionary, normalize_token

STOPWORDS = {
    "a", "an", "the", "to", "of", "in", "on", "for", "with", "and", "or",
    "à", "de", "du", "la", "le", "les", "des", "un", "une", "et", "ou", "en",
    "der", "die", "das", "und", "mit", "für", "von", "zu", "ein", "eine",
    "في", "من", "على", "الى", "إلى", "عن", "و", "مع", "هذا", "هذه", "كم",
}

SYNONYMS = {
    "welcome": ["hello", "hi", "greet", "greeting"],
    "accueille": ["bonjour", "bienvenue", "salut"],
    "مرحبا": ["اهلا", "أهلا", "سلام"],

    "food": ["meal", "dish", "cuisine", "restaurant"],
    "repas": ["manger", "plat", "nourriture"],
    "وجبة": ["اكل", "أكل", "طعام"],

    "tunisia": ["tunis", "tunisian"],
    "tunisie": ["tunis", "tunisien"],
    "تونس": ["تونسي", "تونسية"],

    "paris": ["france"],
    "heart": ["love", "centre", "center"],
    "coeur": ["amour", "centre"],
    "قلب": ["حب", "وسط"],

    "come": ["visit", "join", "go"],
    "venez": ["venir", "visiter"],
    "تعالوا": ["زوروا", "زيارة"],

    "journey": ["travel", "trip"],
    "voyage": ["visite", "trajet"],
    "رحلة": ["سفر", "زيارة"],

    "authentic": ["traditional", "real", "original"],
    "authentique": ["tradition", "original"],
    "أصيل": ["تقليدي", "اصلي", "أصلي"],
}


def expand_token(token):
    token = normalize_token(token)
    expanded = [token]

    for key, values in SYNONYMS.items():
        norm_key = normalize_token(key)
        norm_values = [normalize_token(v) for v in values]

        if token == norm_key:
            expanded.extend(norm_values)

        if token in norm_values:
            expanded.append(norm_key)
            expanded.extend(norm_values)

    return list(dict.fromkeys(expanded))


def clean_tokens(text: str):
    tokens = []

    for w in text.split():
        t = normalize_token(w)

        if len(t) >= 3 and t not in STOPWORDS:
            tokens.extend(expand_token(t))

    return list(dict.fromkeys(tokens))


def get_best_gloss_matches(text: str, language: str, max_results: int = 20):
    words = clean_tokens(text)
    dictionary = load_dictionary(language)

    scored = []

    for gloss in dictionary:
        norm_gloss = normalize_token(gloss)

        if len(norm_gloss) < 3 or norm_gloss in STOPWORDS:
            continue

        score = 0

        for word in words:
            if word == norm_gloss:
                score += 30
            elif len(word) >= 4 and word in norm_gloss:
                score += 10
            elif len(norm_gloss) >= 4 and norm_gloss in word:
                score += 8

        if score > 0:
            scored.append((score, gloss))

    scored.sort(reverse=True, key=lambda x: x[0])

    result = []
    seen = set()

    for score, gloss in scored:
        key = normalize_token(gloss)

        if key not in seen:
            seen.add(key)
            result.append(gloss)

        if len(result) >= max_results:
            break

    return result