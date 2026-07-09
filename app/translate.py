import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

LANG_MAP = {
    "french": "French",
    "arabic": "Arabic",
    "english": "English",
    "german": "German",
    "greek": "Greek",
    "italian": "Italian",
    "spanish": "Spanish",
}


def translate_text(text: str, target_language: str) -> str:
    target_language = target_language.lower().strip()

    if target_language not in LANG_MAP:
        raise ValueError(
            f"Unsupported language '{target_language}'. Use: {list(LANG_MAP.keys())}"
        )

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "system",
                "content": "You are a professional translator. Return only the translated text. No explanation."
            },
            {
                "role": "user",
                "content": f"Translate this text to {LANG_MAP[target_language]}:\n\n{text}"
            }
        ],
        temperature=0
    )

    return response.choices[0].message.content.strip()