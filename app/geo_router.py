from app.sign_language_config import get_country_config, get_always_available_lsa

SIGN_TO_COUNTRY = {
    "LSF": "FR",
    "DGS": "DE",
    "BSL": "GB",
    "GSL": "GR",
    "LIS": "IT",
    "LSE": "ES",
    "NGT": "NL",
    "PJM": "PL",
}


def resolve_sign_route(
    country_code=None,
    manual_sign_language=None,
    browser_language=None,
    ip_geolocation_consent=False,
):
    # 1. LSA always has priority if selected manually
    if manual_sign_language:
        sign = manual_sign_language.upper().strip()

        if sign == "LSA":
            return {
                "source": "manual_lsa_button",
                "route": get_always_available_lsa(),
                "lsa_available": True,
            }

        if sign in SIGN_TO_COUNTRY:
            return {
                "source": "manual_sign_language",
                "route": get_country_config(SIGN_TO_COUNTRY[sign]),
                "lsa_available": True,
            }

    # 2. Manual country selector
    if country_code:
        return {
            "source": "manual_country",
            "route": get_country_config(country_code.upper().strip()),
            "lsa_available": True,
        }

    # 3. Browser language fallback
    if browser_language:
        b = browser_language.lower()

        if b.startswith("fr"):
            country = "FR"
        elif b.startswith("de"):
            country = "DE"
        elif b.startswith("en"):
            country = "GB"
        elif b.startswith("el") or b.startswith("gr"):
            country = "GR"
        elif b.startswith("ar"):
            return {
                "source": "browser_language_arabic",
                "route": get_always_available_lsa(),
                "lsa_available": True,
            }
        else:
            country = None

        if country:
            return {
                "source": "browser_language",
                "route": get_country_config(country),
                "lsa_available": True,
            }

    # 4. IP geolocation placeholder
    if ip_geolocation_consent:
        return {
            "source": "ip_geolocation_stub",
            "route": get_country_config("FR"),
            "lsa_available": True,
        }

    # 5. Final fallback
    return {
        "source": "fallback",
        "route": get_always_available_lsa(),
        "lsa_available": True,
    }