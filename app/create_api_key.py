import argparse
import secrets
import uuid
from datetime import (
    datetime,
    timedelta,
    timezone,
)

from app.auth import hash_api_key
from app.database import SessionLocal
from app.models import ApiCredential


def valid_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid UUID: {value}"
        ) from exc


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Create a Cyrkil API key. "
            "The raw key is displayed only once."
        )
    )

    parser.add_argument(
        "--user-id",
        required=True,
        type=valid_uuid,
    )

    parser.add_argument(
        "--tenant-id",
        required=True,
        type=valid_uuid,
    )

    parser.add_argument(
        "--role",
        default="user",
        choices=[
            "user",
            "developer",
            "admin",
        ],
    )

    parser.add_argument(
        "--plan",
        default="standard",
    )

    parser.add_argument(
        "--expires-days",
        type=int,
        default=90,
    )

    return parser.parse_args()


def create_api_key():
    arguments = parse_arguments()

    if arguments.expires_days <= 0:
        raise ValueError(
            "--expires-days must be greater than zero."
        )

    raw_key = (
        "cyrkil_dev_"
        + secrets.token_urlsafe(32)
    )

    credential = ApiCredential(
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:24],
        user_id=arguments.user_id,
        tenant_id=arguments.tenant_id,
        role=arguments.role,
        plan=arguments.plan,
        enabled=True,
        expires_at=(
            datetime.now(timezone.utc)
            + timedelta(
                days=arguments.expires_days
            )
        ),
    )

    with SessionLocal() as db:
        db.add(credential)
        db.commit()
        db.refresh(credential)

    print()
    print("API key created successfully.")
    print()
    print(f"Credential ID: {credential.id}")
    print(f"User ID:       {credential.user_id}")
    print(f"Tenant ID:     {credential.tenant_id}")
    print(f"Role:          {credential.role}")
    print(f"Plan:          {credential.plan}")
    print(f"Expires at:    {credential.expires_at}")
    print()
    print("Copy this API key now.")
    print("It will not be displayed again:")
    print()
    print(raw_key)
    print()


if __name__ == "__main__":
    create_api_key()