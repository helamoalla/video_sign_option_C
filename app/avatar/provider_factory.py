from app.avatar.capabilities import (
    get_language_capability,
    provider_supports_language,
)
from app.avatar.cwasa_arabic_provider import (
    CwasaArabicProvider,
)
from app.avatar.cwasa_multilang_provider import (
    CwasaMultilangProvider,
)
from app.avatar.placeholder_provider import (
    PlaceholderAvatarProvider,
)
from app.avatar.license_policy import (
    ensure_provider_is_approved,
)


PROVIDER_ALIASES = {
    "placeholder": "placeholder",

    "cwasa": "cwasa_arabic",
    "cwasa_arabic": "cwasa_arabic",

    "cwasa_multilang": "cwasa_multilang",
    "cwasa_multilingual": "cwasa_multilang",
}


def normalize_provider_name(
    provider_name: str,
) -> str:
    normalized_name = (
        provider_name
        or "placeholder"
    ).lower().strip()

    canonical_name = PROVIDER_ALIASES.get(
        normalized_name
    )

    if canonical_name is None:
        supported = ", ".join(
            sorted(PROVIDER_ALIASES)
        )

        raise ValueError(
            f"Unknown avatar provider: {provider_name}. "
            f"Supported providers: {supported}"
        )

    return canonical_name


def get_avatar_provider(
    provider_name: str = "placeholder",
    language: str | None = None,
):
    canonical_name = normalize_provider_name(
        provider_name
    )
    ensure_provider_is_approved(
        canonical_name
    )

    if language is not None:
        if not provider_supports_language(
            canonical_name,
            language,
        ):
            capability = get_language_capability(
                canonical_name,
                language,
            )

            raise ValueError(
                "Avatar provider does not support the "
                "requested sign language or has no assets. "
                f"Capability: {capability}"
            )

    if canonical_name == "placeholder":
        return PlaceholderAvatarProvider()

    if canonical_name == "cwasa_arabic":
        return CwasaArabicProvider()

    if canonical_name == "cwasa_multilang":
        return CwasaMultilangProvider()

    # Defensive protection if a provider is added to aliases
    # but not implemented above.
    raise RuntimeError(
        f"Provider is registered but not implemented: "
        f"{canonical_name}"
    )