from datetime import (
    datetime,
    timedelta,
    timezone,
)
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.auth import (
    ArtifactAccess,
    AuthenticatedPrincipal,
    get_current_principal,
)
from app.main import (
    download_output_artifact,
)


class FakeDatabase:
    def __init__(self, result=None):
        self.result = result

    def scalar(self, statement):
        return self.result


@pytest.fixture
def principal():
    return AuthenticatedPrincipal(
        credential_id=(
            "22222222-2222-2222-2222-222222222222"
        ),
        user_id=(
            "33333333-3333-3333-3333-333333333333"
        ),
        tenant_id=(
            "44444444-4444-4444-4444-444444444444"
        ),
        role="user",
        plan="standard",
    )


def test_missing_api_key_returns_401():
    with pytest.raises(
        HTTPException
    ) as error:
        get_current_principal(
            raw_api_key=None,
            db=FakeDatabase(),
        )

    assert error.value.status_code == 401
    assert (
        error.value.detail["code"]
        == "AUTHENTICATION_REQUIRED"
    )


def test_invalid_api_key_returns_401(
    monkeypatch,
):
    monkeypatch.setenv(
        "API_KEY_PEPPER",
        "a" * 48,
    )

    with pytest.raises(
        HTTPException
    ) as error:
        get_current_principal(
            raw_api_key="invalid-key",
            db=FakeDatabase(result=None),
        )

    assert error.value.status_code == 401


def test_disabled_api_key_returns_401(
    monkeypatch,
):
    monkeypatch.setenv(
        "API_KEY_PEPPER",
        "a" * 48,
    )

    credential = SimpleNamespace(
        enabled=False,
        expires_at=None,
    )

    with pytest.raises(
        HTTPException
    ) as error:
        get_current_principal(
            raw_api_key="disabled-key",
            db=FakeDatabase(credential),
        )

    assert error.value.status_code == 401


def test_expired_api_key_returns_401(
    monkeypatch,
):
    monkeypatch.setenv(
        "API_KEY_PEPPER",
        "a" * 48,
    )

    credential = SimpleNamespace(
        enabled=True,
        expires_at=(
            datetime.now(timezone.utc)
            - timedelta(days=1)
        ),
    )

    with pytest.raises(
        HTTPException
    ) as error:
        get_current_principal(
            raw_api_key="expired-key",
            db=FakeDatabase(credential),
        )

    assert error.value.status_code == 401


def test_other_users_artifact_returns_404(
    principal,
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.main.OUTPUT_DIR",
        tmp_path,
    )

    with pytest.raises(
        HTTPException
    ) as error:
        download_output_artifact(
            job_id=(
                "55555555-5555-5555-5555-555555555555"
            ),
            artifact_path="rendered/video.mp4",
            access=ArtifactAccess(
                principal=principal,
                is_internal_worker=False,
                playback_job_id=None,
            ),
            db=FakeDatabase(result=None),
        )

    assert error.value.status_code == 404
    assert (
        error.value.detail["code"]
        == "ARTIFACT_NOT_FOUND"
    )


def test_owner_can_access_artifact(
    principal,
    tmp_path: Path,
    monkeypatch,
):
    job_id = (
        "55555555-5555-5555-5555-555555555555"
    )

    artifact = (
        tmp_path
        / job_id
        / "rendered"
        / "video.mp4"
    )

    artifact.parent.mkdir(
        parents=True
    )

    artifact.write_bytes(
        b"test video"
    )

    monkeypatch.setattr(
        "app.main.OUTPUT_DIR",
        tmp_path,
    )

    response = download_output_artifact(
        job_id=job_id,
        artifact_path="rendered/video.mp4",
        access=ArtifactAccess(
            principal=principal,
            is_internal_worker=False,
            playback_job_id=None,
        ),
        db=FakeDatabase(
            result=SimpleNamespace(id=job_id)
        ),
    )

    assert isinstance(
        response,
        FileResponse,
    )

    assert Path(response.path) == artifact


def test_path_traversal_is_rejected(
    principal,
    tmp_path: Path,
    monkeypatch,
):
    job_id = (
        "55555555-5555-5555-5555-555555555555"
    )

    monkeypatch.setattr(
        "app.main.OUTPUT_DIR",
        tmp_path,
    )

    with pytest.raises(
        HTTPException
    ) as error:
        download_output_artifact(
            job_id=job_id,
            artifact_path="../../secret.txt",
            access=ArtifactAccess(
                principal=principal,
                is_internal_worker=False,
                playback_job_id=None,
            ),
            db=FakeDatabase(
                result=SimpleNamespace(id=job_id)
            ),
        )

    assert error.value.status_code == 404