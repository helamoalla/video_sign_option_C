import json
import re
from app.gloss_dictionary import load_dictionary
from langchain_groq import ChatGroq
from dotenv import load_dotenv
from app.gloss_matcher import get_best_gloss_matches

load_dotenv()


def get_llm():
    return ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0
    )


def extract_json(content: str):
    content = content.strip()
    content = content.replace("```json", "").replace("```", "").strip()

    match = re.search(r"\{.*?\}", content, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    return {"glosses": []}


def generate_gloss(text: str, language: str = "lsa"):
    available = load_dictionary(language)

    if not available:
        return []

    candidates = get_best_gloss_matches(text, language, max_results=80)

    if not candidates:
        candidates = available[:500]

    prompt = f"""
You are a sign-language gloss selector.

Your task:
1. Understand the meaning of the input sentence.
2. If some words do not exist in the dictionary, simplify or rephrase the meaning using available dictionary words.
3. Select the maximum number of useful glosses that preserve the main meaning.
4. Prefer important concepts: people, place, action, food, emotion, invitation, time, object.
5. Remove useless filler words.
6. Use ONLY glosses that exist exactly in the dictionary list.
7. Never invent a gloss.
8. Return ONLY valid JSON.

Important:
- Do NOT translate word by word.
- Do NOT keep only exact matches.
- If "authentic Tunisian food" is missing, choose available related glosses like "tunisia", "food", "meal", "good", "love".
- If "come and visit us" is missing, choose available related glosses like "come", "visit", "you", "welcome".
- Preserve the meaning as much as possible with available glosses.

Output format:
{{"glosses":["gloss1","gloss2","gloss3"]}}

Maximum glosses: 20

Input sentence:
{text}

Available dictionary glosses:
{candidates}
"""

    try:
        response = get_llm().invoke(prompt)
        data = extract_json(response.content)
        glosses = data.get("glosses", [])

        valid_available = set(available)
        valid_candidates = set(candidates)

        valid = []
        for g in glosses:
            if g in valid_available or g in valid_candidates:
                if g not in valid:
                    valid.append(g)

        if valid:
            return valid[:20]

        return candidates[:20]

    except Exception:
        return candidates[:20]