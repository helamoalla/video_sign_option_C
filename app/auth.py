import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import (
    Depends,
    HTTPException,
    Query,
    status,
)
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApiCredential
import base64
import json
import time

# User/developer authentication.
API_KEY_HEADER = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
)

# Internal API-to-worker authentication.
INTERNAL_WORKER_HEADER = APIKeyHeader(
    name="X-Internal-Worker-Token",
    auto_error=False,
)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    credential_id: str
    user_id: str
    tenant_id: str
    role: str
    plan: str


@dataclass(frozen=True)
class ArtifactAccess:
    principal: AuthenticatedPrincipal | None
    is_internal_worker: bool
    playback_job_id: str | None = None


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


def get_internal_worker_token() -> str:
    token = os.getenv(
        "INTERNAL_WORKER_TOKEN",
        "",
    ).strip()

    if len(token) < 32:
        raise RuntimeError(
            "INTERNAL_WORKER_TOKEN must contain "
            "at least 32 characters."
        )

    return token


def hash_api_key(
    raw_api_key: str,
) -> str:
    """
    Hash a user API key with the server-side pepper.

    Only the resulting hash is stored in Postgres.
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
    """
    Authenticate a Cyrkil user or developer API key.
    """

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

def get_playback_signing_secret() -> str:
    secret = os.getenv(
        "PLAYBACK_SIGNING_SECRET",
        "",
    ).strip()

    if len(secret) < 32:
        raise RuntimeError(
            "PLAYBACK_SIGNING_SECRET must contain "
            "at least 32 characters."
        )

    return secret


def encode_urlsafe(
    value: bytes,
) -> str:
    return base64.urlsafe_b64encode(
        value
    ).decode("ascii").rstrip("=")


def decode_urlsafe(
    value: str,
) -> bytes:
    padding = "=" * (
        (-len(value)) % 4
    )

    return base64.urlsafe_b64decode(
        value + padding
    )


def create_playback_token(
    job_id: str,
    expires_at_timestamp: int,
) -> str:
    payload = {
        "job_id": job_id,
        "exp": expires_at_timestamp,
        "purpose": "playback",
    }

    encoded_payload = encode_urlsafe(
        json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )

    signature = hmac.new(
        key=(
            get_playback_signing_secret()
            .encode("utf-8")
        ),
        msg=encoded_payload.encode(
            "ascii"
        ),
        digestmod=hashlib.sha256,
    ).digest()

    return (
        encoded_payload
        + "."
        + encode_urlsafe(signature)
    )


def verify_playback_token(
    token: str,
) -> str:
    try:
        encoded_payload, encoded_signature = (
            token.split(".", 1)
        )

        provided_signature = decode_urlsafe(
            encoded_signature
        )

        expected_signature = hmac.new(
            key=(
                get_playback_signing_secret()
                .encode("utf-8")
            ),
            msg=encoded_payload.encode(
                "ascii"
            ),
            digestmod=hashlib.sha256,
        ).digest()

        if not hmac.compare_digest(
            provided_signature,
            expected_signature,
        ):
            raise ValueError(
                "Invalid playback signature."
            )

        payload = json.loads(
            decode_urlsafe(
                encoded_payload
            ).decode("utf-8")
        )

        if payload.get("purpose") != "playback":
            raise ValueError(
                "Invalid token purpose."
            )

        job_id = payload.get("job_id")
        expires_at = int(
            payload.get("exp", 0)
        )

        if not job_id:
            raise ValueError(
                "Missing job ID."
            )

        if expires_at <= int(time.time()):
            raise ValueError(
                "Playback token expired."
            )

        return str(job_id)

    except (
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_PLAYBACK_TOKEN",
                "message": (
                    "The playback URL is invalid "
                    "or expired."
                ),
            },
        ) from exc


def get_artifact_access(
    raw_api_key: str | None = Depends(
        API_KEY_HEADER
    ),
    raw_internal_token: str | None = Depends(
        INTERNAL_WORKER_HEADER
    ),
    playback_token: str | None = Query(
        default=None,
        alias="token",
    ),
    db: Session = Depends(get_db),
) -> ArtifactAccess:
    # Internal worker access for CWASA.
    if raw_internal_token:
        expected_internal_token = (
            get_internal_worker_token()
        )

        if not hmac.compare_digest(
            raw_internal_token.strip(),
            expected_internal_token,
        ):
            raise credentials_exception()

        return ArtifactAccess(
            principal=None,
            is_internal_worker=True,
            playback_job_id=None,
        )

    # Browser playback access.
    if playback_token:
        playback_job_id = (
            verify_playback_token(
                playback_token
            )
        )

        return ArtifactAccess(
            principal=None,
            is_internal_worker=False,
            playback_job_id=playback_job_id,
        )

    # Normal user API-key access.
    principal = get_current_principal(
        raw_api_key=raw_api_key,
        db=db,
    )

    return ArtifactAccess(
        principal=principal,
        is_internal_worker=False,
        playback_job_id=None,
    )