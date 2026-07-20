import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import (
    Depends,
    HTTPException,
    status,
)
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApiCredential


API_KEY_HEADER = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    credential_id: str
    user_id: str
    tenant_id: str
    role: str
    plan: str


def get_api_key_pepper() -> str:
    pepper = os.getenv(
        "API_KEY_PEPPER",
        "",
    ).strip()

    if len(pepper) < 32:
        raise RuntimeError(
            "API_KEY_PEPPER must contain at least "
            "32 characters."
        )

    return pepper


def hash_api_key(
    raw_api_key: str,
) -> str:
    """
    Hash an API key with a server-side secret pepper.

    Only this hash is persisted in Postgres.
    """

    normalized_key = raw_api_key.strip()

    if not normalized_key:
        raise ValueError(
            "API key cannot be empty."
        )

    return hmac.new(
        key=get_api_key_pepper().encode(
            "utf-8"
        ),
        msg=normalized_key.encode(
            "utf-8"
        ),
        digestmod=hashlib.sha256,
    ).hexdigest()


def credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "AUTHENTICATION_REQUIRED",
            "message": (
                "A valid API key is required."
            ),
        },
        headers={
            "WWW-Authenticate": "ApiKey",
        },
    )


def get_current_principal(
    raw_api_key: str | None = Depends(
        API_KEY_HEADER
    ),
    db: Session = Depends(get_db),
) -> AuthenticatedPrincipal:
    if not raw_api_key:
        raise credentials_exception()

    try:
        key_hash = hash_api_key(
            raw_api_key
        )
    except ValueError:
        raise credentials_exception()

    credential = db.scalar(
        select(ApiCredential).where(
            ApiCredential.key_hash
            == key_hash
        )
    )

    if credential is None:
        raise credentials_exception()

    if not credential.enabled:
        raise credentials_exception()

    if credential.expires_at is not None:
        expires_at = credential.expires_at

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(
                tzinfo=timezone.utc
            )

        if expires_at <= datetime.now(
            timezone.utc
        ):
            raise credentials_exception()

    return AuthenticatedPrincipal(
        credential_id=credential.id,
        user_id=credential.user_id,
        tenant_id=credential.tenant_id,
        role=credential.role,
        plan=credential.plan,
    )