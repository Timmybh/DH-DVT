from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class IndicatorStatus(Base):
    """5 chỉ số sidebar: SX, DONGGOI, GIAOHANG, QA, VUONGMAC - trạng thái Xanh/Đỏ theo ngày."""

    __tablename__ = "indicator_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    indicator_key: Mapped[str] = mapped_column(String(50), index=True)  # SX|DONGGOI|GIAOHANG|QA|VUONGMAC
    factory_id: Mapped[int | None] = mapped_column(ForeignKey("factories.id"), nullable=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(10), default="GREEN")  # GREEN | RED
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class IssueItem(Base):
    """Chi tiết vướng mắc, hiện khi drill-down từ sidebar/chart."""

    __tablename__ = "issue_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_id: Mapped[int | None] = mapped_column(ForeignKey("factories.id"), nullable=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(20), default="MEDIUM")  # LOW|MEDIUM|HIGH
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN|RESOLVED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    factory = relationship("Factory")
