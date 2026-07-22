import json
import re

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from app.gloss_dictionary import (
    load_dictionary,
)
from app.gloss_matcher import (
    get_best_gloss_matches,
    get_high_confidence_gloss_matches,
)


load_dotenv()


def get_llm():
    return ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0,
    )


def extract_json(
    content: str,
) -> dict:
    clean_content = (
        content
        or ""
    ).strip()

    clean_content = (
        clean_content
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    match = re.search(
        r"\{.*?\}",
        clean_content,
        re.DOTALL,
    )

    if not match:
        return {
            "glosses": [],
        }

    try:
        result = json.loads(
            match.group(0)
        )

    except json.JSONDecodeError:
        return {
            "glosses": [],
        }

    if not isinstance(result, dict):
        return {
            "glosses": [],
        }

    return result


def merge_unique_glosses(
    *gloss_groups: list[str],
    maximum: int = 20,
) -> list[str]:
    merged = []

    for gloss_group in gloss_groups:
        for gloss in gloss_group:
            clean_gloss = str(
                gloss
            ).strip()

            if (
                clean_gloss
                and clean_gloss not in merged
            ):
                merged.append(
                    clean_gloss
                )

            if len(merged) >= maximum:
                return merged

    return merged


def generate_gloss(
    text: str,
    language: str = "lsa",
) -> list[str]:
    available = load_dictionary(
        language
    )

    if not available:
        return []

    # These matches are deterministic and must not be discarded
    # by the LLM. This includes Arabic words with prefixes such
    # as بباريس -> باريس.
    required_glosses = (
        get_high_confidence_gloss_matches(
            text,
            language,
        )
    )

    candidates = get_best_gloss_matches(
        text,
        language,
        max_results=80,
    )

    if not candidates:
        candidates = available[:500]

    prompt = f"""
You are a sign-language gloss selector.

Your task:
1. Understand the meaning of the input sentence.
2. If some words do not exist in the dictionary, simplify or
   rephrase the meaning using available dictionary words.
3. Select the maximum number of useful glosses that preserve
   the main meaning.
4. Prefer important concepts: people, place, action, food,
   emotion, invitation, time and object.
5. Remove useless filler words.
6. Use ONLY glosses that exist exactly in the dictionary list.
7. Never invent a gloss.
8. Return ONLY valid JSON.

Important:
- Do NOT translate word by word.
- Do NOT keep only exact matches.
- Preserve places and proper names when they exist in the
  dictionary.
- Arabic words may contain attached prefixes. If باريس is in
  the dictionary and the sentence contains بباريس, preserve
  the باريس gloss.
- If "authentic Tunisian food" is missing, choose available
  related glosses such as "tunisia", "food", "meal", "good"
  and "love".
- If "come and visit us" is missing, choose available related
  glosses such as "come", "visit", "you" and "welcome".
- Preserve the meaning as much as possible with available
  glosses.

Output format:
{{"glosses":["gloss1","gloss2","gloss3"]}}

Maximum glosses: 20

Input sentence:
{text}

Required exact dictionary matches:
{required_glosses}

Available dictionary glosses:
{candidates}
"""

    try:
        response = get_llm().invoke(
            prompt
        )

        data = extract_json(
            response.content
        )

        returned_glosses = data.get(
            "glosses",
            [],
        )

        if not isinstance(
            returned_glosses,
            list,
        ):
            returned_glosses = []

        valid_available = set(
            available
        )

        valid_candidates = set(
            candidates
        )

        valid = []

        for gloss in returned_glosses:
            clean_gloss = str(
                gloss
            ).strip()

            if (
                clean_gloss in valid_available
                or clean_gloss in valid_candidates
            ):
                if clean_gloss not in valid:
                    valid.append(
                        clean_gloss
                    )

        # Required exact matches are placed first so the LLM
        # cannot accidentally remove باريس from بباريس.
        combined = merge_unique_glosses(
            required_glosses,
            valid,
            maximum=20,
        )

        if combined:
            return combined

        return candidates[:20]

    except Exception:
        # External LLM failure must not remove deterministic
        # dictionary matches.
        return merge_unique_glosses(
            required_glosses,
            candidates,
            maximum=20,
        )