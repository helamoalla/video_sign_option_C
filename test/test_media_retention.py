from datetime import (
    datetime,
    timedelta,
    timezone,
)
from types import SimpleNamespace

import pytest

import app.media_retention as retention
from app.media_retention import (
    ActiveJobDeletionError,
    cleanup_expired_media,
    delete_all_media_for_job,
    delete_job_directory,
)
from app.models import JobStatus


class FakeDatabase:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)


class FakeCleanupDatabase(FakeDatabase):
    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs

    def scalars(self, statement):
        return self.jobs


def make_job(
    *,
    status: JobStatus,
):
    return SimpleNamespace(
        id=(
            "11111111-1111-1111-"
            "1111-111111111111"
        ),
        owner_id=(
            "22222222-2222-2222-"
            "2222-222222222222"
        ),
        tenant_id=(
            "33333333-3333-3333-"
            "3333-333333333333"
        ),
        status=status,
        result={
            "media_available": True,
        },
        media_deleted_at=None,
        media_expires_at=None,
        updated_at=datetime.now(
            timezone.utc
        ),
    )


def test_delete_job_directory_is_isolated(
    tmp_path,
):
    job_id = (
        "11111111-1111-1111-"
        "1111-111111111111"
    )
    other_job_id = (
        "22222222-2222-2222-"
        "2222-222222222222"
    )

    job_directory = tmp_path / job_id
    other_directory = (
        tmp_path / other_job_id
    )

    job_directory.mkdir()
    other_directory.mkdir()

    (
        job_directory / "private.mp4"
    ).write_bytes(b"private")

    (
        other_directory / "other.mp4"
    ).write_bytes(b"other")

    assert (
        delete_job_directory(
            tmp_path,
            job_id,
        )
        is True
    )

    assert not job_directory.exists()
    assert other_directory.is_dir()

    assert (
        other_directory / "other.mp4"
    ).is_file()


def test_missing_job_directory_is_idempotent(
    tmp_path,
):
    deleted = delete_job_directory(
        tmp_path,
        (
            "11111111-1111-1111-"
            "1111-111111111111"
        ),
    )

    assert deleted is False


def test_active_job_media_cannot_be_deleted():
    database = FakeDatabase()

    job = make_job(
        status=JobStatus.PROCESSING
    )

    with pytest.raises(
        ActiveJobDeletionError
    ):
        delete_all_media_for_job(
            database,
            job,
            reason="user_requested",
            requested_by=job.owner_id,
        )

    assert database.added == []


def test_terminal_job_deletion_is_audited(
    tmp_path,
    monkeypatch,
):
    upload_root = tmp_path / "uploads"
    output_root = tmp_path / "outputs"

    upload_root.mkdir()
    output_root.mkdir()

    job = make_job(
        status=JobStatus.COMPLETED
    )

    (upload_root / job.id).mkdir()
    (output_root / job.id).mkdir()

    monkeypatch.setattr(
        retention,
        "UPLOAD_ROOT",
        upload_root,
    )
    monkeypatch.setattr(
        retention,
        "OUTPUT_ROOT",
        output_root,
    )

    database = FakeDatabase()

    audit = delete_all_media_for_job(
        database,
        job,
        reason="user_requested",
        requested_by=job.owner_id,
    )

    assert audit.upload_deleted is True
    assert audit.output_deleted is True
    assert audit.reason == "user_requested"

    assert job.media_deleted_at is not None

    assert (
        job.result["media_available"]
        is False
    )

    assert database.added == [audit]

    assert not (
        upload_root / job.id
    ).exists()

    assert not (
        output_root / job.id
    ).exists()


def test_expired_media_is_deleted_and_audited(
    tmp_path,
    monkeypatch,
):
    upload_root = tmp_path / "uploads"
    output_root = tmp_path / "outputs"

    upload_root.mkdir()
    output_root.mkdir()

    job = make_job(
        status=JobStatus.COMPLETED
    )

    now = datetime.now(timezone.utc)

    job.updated_at = (
        now - timedelta(days=8)
    )
    job.media_expires_at = (
        now - timedelta(minutes=1)
    )

    upload_directory = (
        upload_root / job.id
    )
    output_directory = (
        output_root / job.id
    )

    upload_directory.mkdir()
    output_directory.mkdir()

    (
        upload_directory
        / "original.mp4"
    ).write_bytes(b"upload")

    (
        output_directory
        / "player.html"
    ).write_text(
        "player",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        retention,
        "UPLOAD_ROOT",
        upload_root,
    )
    monkeypatch.setattr(
        retention,
        "OUTPUT_ROOT",
        output_root,
    )

    database = FakeCleanupDatabase(
        [job]
    )

    deleted_job_ids = (
        cleanup_expired_media(
            database,
            now=now,
        )
    )

    assert deleted_job_ids == [job.id]

    assert not upload_directory.exists()
    assert not output_directory.exists()

    assert job.media_deleted_at == now
    assert job.media_expires_at is None

    assert (
        job.result["media_available"]
        is False
    )

    assert len(database.added) == 1

    audit = database.added[0]

    assert (
        audit.reason
        == "retention_expired"
    )
    assert audit.requested_by == "system"
    assert audit.upload_deleted is True
    assert audit.output_deleted is True