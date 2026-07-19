import traceback

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import JobStatus, VideoJob
from app.pipelines.video_assets import (
    run_video_assets_pipeline,
)

import logging
import uuid

logger = logging.getLogger(__name__)

@celery_app.task(name="app.tasks.test_task")
def test_task(value: str) -> dict:
    return {
        "status": "completed",
        "value": value,
    }


@celery_app.task(name="app.tasks.process_video")
def process_video_task(job_id: str):
    # We will move the pipeline here in the next step.
    return {
        "job_id": job_id,
        "status": "received",
    }


def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    stage: str | None = None,
    progress: int | None = None,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    with SessionLocal() as db:
        job = db.get(VideoJob, job_id)

        if job is None:
            raise RuntimeError(f"Job not found: {job_id}")

        if status is not None:
            job.status = status

        if stage is not None:
            job.stage = stage

        if progress is not None:
            job.progress = progress

        if result is not None:
            job.result = result

        if error is not None:
            job.error = error

        db.commit()


@celery_app.task(
    bind=True,
    name="app.tasks.process_video_assets",
)
def process_video_assets_task(self, job_id: str):
    with SessionLocal() as db:
        job = db.get(VideoJob, job_id)

        if job is None:
            raise RuntimeError(f"Job not found: {job_id}")

        input_path = job.input_path
        parameters = job.parameters

    update_job(
        job_id,
        status=JobStatus.PROCESSING,
        stage="starting",
        progress=1,
    )

    def report_progress(stage: str, progress: int):
        update_job(
            job_id,
            status=JobStatus.PROCESSING,
            stage=stage,
            progress=progress,
        )

    try:
        result = run_video_assets_pipeline(
            job_id=job_id,
            input_path=input_path,
            parameters=parameters,
            update_progress=report_progress,
        )

        update_job(
            job_id,
            status=JobStatus.COMPLETED,
            stage="completed",
            progress=100,
            result=result,
        )

        return result

    except Exception as exc:
        error_id = str(uuid.uuid4())

        logger.exception(
            "Video processing failed. "
            "job_id=%s error_id=%s",
            job_id,
            error_id,
        )

        update_job(
            job_id,
            status=JobStatus.FAILED,
            stage="failed",
            error=(
                "Video processing failed. "
                f"Reference: {error_id}"
            ),
        )

        raise