import os

from celery import Celery


celery_app = Celery(
    "videosign",
    broker=os.environ["CELERY_BROKER_URL"],
    backend=os.environ["CELERY_RESULT_BACKEND"],
    include=["app.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

celery_app.conf.beat_schedule = {
    "cleanup-expired-media-hourly": {
        "task": (
            "app.tasks.cleanup_expired_media"
        ),
        "schedule": 3600.0,
    },
}

celery_app.conf.timezone = "UTC"