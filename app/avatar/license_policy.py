import os


PROTOTYPE_PROVIDERS = {
    "cwasa_arabic",
    "cwasa_multilang",
}


class ProviderNotApprovedForProductionError(
    ValueError
):
    pass


def get_app_environment() -> str:
    return os.getenv(
        "APP_ENV",
        "production",
    ).strip().lower()


def research_assets_are_allowed() -> bool:
    value = os.getenv(
        "ALLOW_RESEARCH_ASSETS",
        "false",
    ).strip().lower()

    return value in {
        "1",
        "true",
        "yes",
        "on",
    }


def ensure_provider_is_approved(
    provider_name: str,
) -> None:
    environment = get_app_environment()

    if provider_name not in PROTOTYPE_PROVIDERS:
        return

    if (
        environment != "production"
        and research_assets_are_allowed()
    ):
        return

    raise ProviderNotApprovedForProductionError(
        "The requested avatar provider is approved "
        "only for prototype development. Production "
        "must use Cyrkil-owned or commercially licensed "
        "avatar videos."
    )