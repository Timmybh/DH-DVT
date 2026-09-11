from datetime import datetime

from pydantic import BaseModel


class ImportJobOut(BaseModel):
    id: int
    job_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    rows_imported: int
    rows_skipped: int
    error_message: str
    triggered_by: str


class ImportJobConfigOut(BaseModel):
    is_enabled: bool
    scheduled_time: str
    timezone: str
    last_run_at: datetime | None


class ImportJobConfigUpdate(BaseModel):
    is_enabled: bool
    scheduled_time: str
