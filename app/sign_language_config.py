from pathlib import Path
import json
from functools import lru_cache
CONFIG_PATH=Path("data/sign_languages/eu_sign_languages.json")
@lru_cache(maxsize=1)
def load_sign_language_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
def list_countries(): return load_sign_language_config()["countries"]
def get_country_config(country_code):
    c=load_sign_language_config()
    if not country_code: return c["fallback"]
    for x in c["countries"]:
        if x["country_code"]==country_code.upper().strip(): return x
    f=dict(c["fallback"]); f["warning"]=f"Unsupported country {country_code}"; return f
def get_always_available_lsa(): return load_sign_language_config()["always_available"]
