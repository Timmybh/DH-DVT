from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class KpiConfig(Base):
    """Cấu hình KPI - chỉnh qua nút 'Cấu hình KPI' trên dashboard."""

    __tablename__ = "kpi_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(50), default="")
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    warning_threshold_pct: Mapped[float] = mapped_column(Float, default=90.0)
    gauge_slot: Mapped[int | None] = mapped_column(nullable=True)  # 1..10, null = chưa gán gauge
    display_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GaugeMetric(Base):
    """Giá trị hàng ngày đổ vào 1 trong 10 gauge trên dashboard."""

    __tablename__ = "gauge_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    kpi_config_id: Mapped[int | None] = mapped_column(ForeignKey("kpi_configs.id"), nullable=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    value: Mapped[float] = mapped_column(Float, default=0)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)
