from app.gloss_dictionary import (
    get_language_asset_count,
    has_language_assets,
    normalize_language,
)


PROVIDER_CAPABILITIES = {
    "cwasa_multilang": {
        "output_type": "cwasa_sigml",
        "languages": {
            "lsf": {
                "implemented": True,
                "production_ready": False,
                "validated": False,
                "licence_verified": False,
            },
            "lsa": {
                "implemented": True,
                "production_ready": False,
                "validated": False,
                "licence_verified": False,
            },
            "dgs": {
                "implemented": True,
                "production_ready": False,
                "validated": False,
                "licence_verified": False,
            },
            "bsl": {
                "implemented": True,
                "production_ready": False,
                "validated": False,
                "licence_verified": False,
            },
            "gsl": {
                "implemented": True,
                "production_ready": False,
                "validated": False,
                "licence_verified": False,
            },
        },
    },
}


def provider_supports_language(
    provider_name: str,
    language: str,
) -> bool:
    provider = PROVIDER_CAPABILITIES.get(
        provider_name
    )

    if provider is None:
        return False

    canonical_language = normalize_language(
        language
    )

    return (
        canonical_language
        in provider["languages"]
        and has_language_assets(
            canonical_language
        )
    )


def get_language_capability(
    provider_name: str,
    language: str,
) -> dict:
    canonical_language = normalize_language(
        language
    )

    return {
        "provider": provider_name,
        "language": canonical_language,
        "supported": provider_supports_language(
            provider_name,
            canonical_language,
        ),
        "asset_count": get_language_asset_count(
            canonical_language
        ),
    }