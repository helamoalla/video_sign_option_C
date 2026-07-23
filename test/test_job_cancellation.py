from types import SimpleNamespace

import pytest

import app.job_control as job_control
import app.tasks as tasks
from app.models import JobStatus


class FakeDatabase:
    def flush(self):
        pass


def make_job(
    status: JobStatus,
):
    return SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        status=status,
        stage=status.value,
        celery_task_id="celery-task-id",
        cancel_requested_at=None,
        cancelled_at=None,
        error=None,
        last_error_code=None,
        dead_lettered_at=None,
    )


def test_queued_job_is_cancelled_immediately(
    monkeypatch,
):
    job = make_job(
        JobStatus.QUEUED
    )

    monkeypatch.setattr(
        job_control,
        "delete_all_media_for_job",
        lambda *args, **kwargs: SimpleNamespace(
            id="audit-id"
        ),
    )

    result = (
        job_control.request_job_cancellation(
            FakeDatabase(),
            job,
            requested_by="user-id",
        )
    )

    assert job.status == JobStatus.CANCELLED
    assert job.stage == "cancelled"
    assert job.cancel_requested_at is not None
    assert job.cancelled_at is not None

    assert result.cancellation_pending is False
    assert result.revoke_task is True
    assert result.audit_id == "audit-id"


def test_retrying_job_is_cancelled_immediately(
    monkeypatch,
):
    job = make_job(
        JobStatus.RETRYING
    )

    monkeypatch.setattr(
        job_control,
        "delete_all_media_for_job",
        lambda *args, **kwargs: SimpleNamespace(
            id="audit-id"
        ),
    )

    result = (
        job_control.request_job_cancellation(
            FakeDatabase(),
            job,
            requested_by="user-id",
        )
    )

    assert job.status == JobStatus.CANCELLED
    assert result.revoke_task is True


def test_processing_job_requests_cooperative_cancellation():
    job = make_job(
        JobStatus.PROCESSING
    )

    result = (
        job_control.request_job_cancellation(
            FakeDatabase(),
            job,
            requested_by="user-id",
        )
    )

    assert job.status == JobStatus.PROCESSING
    assert job.stage == "cancellation_requested"
    assert job.cancel_requested_at is not None
    assert job.cancelled_at is None

    assert result.cancellation_pending is True
    assert result.revoke_task is False


@pytest.mark.parametrize(
    "terminal_status",
    [
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    ],
)
def test_terminal_job_cannot_be_cancelled(
    terminal_status,
):
    job = make_job(
        terminal_status
    )

    with pytest.raises(
        job_control.JobCannotBeCancelledError
    ):
        job_control.request_job_cancellation(
            FakeDatabase(),
            job,
            requested_by="user-id",
        )


def test_cancelled_job_is_idempotent():
    job = make_job(
        JobStatus.CANCELLED
    )

    result = (
        job_control.request_job_cancellation(
            FakeDatabase(),
            job,
            requested_by="user-id",
        )
    )

    assert result.status == JobStatus.CANCELLED
    assert result.cancellation_pending is False
    assert result.revoke_task is False


def test_task_never_completes_after_cancellation(
    monkeypatch,
):
    checks = 0

    monkeypatch.setattr(
        tasks,
        "start_job_attempt",
        lambda job_id: (
            "/tmp/input.mp4",
            {},
            1,
            3,
        ),
    )

    def check_cancellation(job_id):
        nonlocal checks
        checks += 1

        # First check happens before the pipeline.
        # Second happens before marking it completed.
        if checks >= 2:
            raise tasks.JobCancellationRequested()

    monkeypatch.setattr(
        tasks,
        "raise_if_cancellation_requested",
        check_cancellation,
    )

    monkeypatch.setattr(
        tasks,
        "run_video_assets_pipeline",
        lambda **kwargs: {
            "status": "success"
        },
    )

    monkeypatch.setattr(
        tasks,
        "finalize_cancelled_job",
        lambda job_id: {
            "job_id": job_id,
            "status": "cancelled",
        },
    )

    def fail_if_completed(*args, **kwargs):
        if (
            kwargs.get("status")
            == JobStatus.COMPLETED
        ):
            pytest.fail(
                "A cancelled job became completed."
            )

    monkeypatch.setattr(
        tasks,
        "update_job",
        fail_if_completed,
    )

    result = (
        tasks.process_video_assets_task.run(
            "11111111-1111-1111-1111-111111111111"
        )
    )

    assert result["status"] == "cancelled"