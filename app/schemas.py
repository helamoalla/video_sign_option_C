from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models import JobStatus

class JobCreatedResponse(BaseModel):
    job_id: str
    status: JobStatus
    status_url: str
    idempotency_key: str
    idempotent_replay: bool = False


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: JobStatus
    stage: str
    progress: int
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime