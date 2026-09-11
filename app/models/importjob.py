from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ImportJob(Base):
    """Log mỗi lần đồng bộ SQL Server -> Postgres (thủ công hoặc theo lịch)."""

    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(20))  # MANUAL | SCHEDULED
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")  # RUNNING|SUCCESS|FAILED
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    triggered_by: Mapped[str] = mapped_column(String(100), default="")


class ImportJobConfig(Base):
    """Cấu hình lịch tự động chạy ETL hàng ngày (singleton row)."""

    __tablename__ = "import_job_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    scheduled_time: Mapped[str] = mapped_column(String(5), default="05:00")  # HH:MM
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Ho_Chi_Minh")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
