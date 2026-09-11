from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class PlanProgress(Base):
    """Kế hoạch vs thực hiện theo ngày, theo từng xí nghiệp (và hàng TONG cho tổng công ty)."""

    __tablename__ = "plan_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_id: Mapped[int] = mapped_column(ForeignKey("factories.id"), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    plan_qty: Mapped[float] = mapped_column(Float, default=0)
    actual_qty: Mapped[float] = mapped_column(Float, default=0)
    completion_pct: Mapped[float] = mapped_column(Float, default=0)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
