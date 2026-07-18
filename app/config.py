import os
from urllib.parse import urlparse


def get_required_url(name: str) -> str:
    value = os.getenv(name, "").strip().rstrip("/")

    parsed = urlparse(value)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(
            f"{name} must be configured with a valid HTTP/HTTPS URL"
        )

    return value


INTERNAL_BASE_URL = get_required_url("INTERNAL_BASE_URL")
PUBLIC_BASE_URL = get_required_url("PUBLIC_BASE_URL")