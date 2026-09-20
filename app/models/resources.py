"""Danh mục nguồn lực Planning: Capacity Definition, Machine Capacity, yêu cầu máy theo mã hàng, lao động theo ngày."""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow


class CapacityDefinition(Base):
    """Năng suất chuẩn (pcs/ngày) do IE/LEAN/CI quản lý. Sửa = tạo phiên bản mới, bản cũ RETIRED (không ghi đè lịch sử)."""

    __tablename__ = "capacity_definitions"
    __table_args__ = (Index("ix_capdef_lookup", "factory_code", "line", "style_cc", "model_code", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_code: Mapped[str] = mapped_column(String(20), default="", index=True)  # '' = mọi xí nghiệp
    line: Mapped[str] = mapped_column(String(20), default="")  # '' = mọi chuyền
    style_cc: Mapped[str] = mapped_column(String(60), default="")  # '' = mọi mã
    model_code: Mapped[str] = mapped_column(String(60), default="")
    process: Mapped[str] = mapped_column(String(60), default="")  # CUT&SEW ...
    worker_count: Mapped[float | None] = mapped_column(Float, nullable=True)
    working_minutes: Mapped[float | None] = mapped_column(Float, nullable=True, default=540)
    capacity_per_day: Mapped[float] = mapped_column(Float)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(12), default="MANUAL")  # IE | LEAN | CI | WORKBOOK | MANUAL
    owner: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", index=True)  # ACTIVE | RETIRED
    version: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MachineType(Base):
    __tablename__ = "machine_types"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    source: Mapped[str] = mapped_column(String(10), default="EGMF")  # EGMF | MANUAL


class MachineCapacity(Base):
    """Số lượng/công suất máy của một chuyền theo nhóm máy."""

    __tablename__ = "machine_capacities"

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_code: Mapped[str] = mapped_column(String(20), index=True)
    line: Mapped[str] = mapped_column(String(20), index=True)
    machine_type: Mapped[str] = mapped_column(String(20), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    nominal_output_per_day: Mapped[float | None] = mapped_column(Float, nullable=True)  # công suất danh định của nhóm máy này (pcs/ngày)
    efficiency: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1 (OEE)
    changeover_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    planned_downtime_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    maintenance_status: Mapped[str] = mapped_column(String(12), default="OK")  # OK | MAINTENANCE | DOWN
    is_bottleneck: Mapped[bool] = mapped_column(Boolean, default=False)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MachineRequirement(Base):
    """Mã hàng cần bao nhiêu máy loại nào (từ Quy trình công nghệ của eGMF hoặc nhập tay)."""

    __tablename__ = "machine_requirements"
    __table_args__ = (UniqueConstraint("style_cc", "machine_type", name="uq_machine_req"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    style_cc: Mapped[str] = mapped_column(String(60), index=True)
    machine_type: Mapped[str] = mapped_column(String(20))
    machine_name: Mapped[str] = mapped_column(String(100), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(10), default="QTCN")  # QTCN | MANUAL
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LaborDaily(Base):
    """Lao động theo chuyền/ngày (eGMF LCD_Truc_Quan_ChuyenMay_LaoDong): nguồn cho kiểm tra nhân lực khả dụng."""

    __tablename__ = "labor_daily"
    __table_args__ = (UniqueConstraint("factory_code", "line", "day", name="uq_labor_daily"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_code: Mapped[str] = mapped_column(String(20), index=True)
    line: Mapped[str] = mapped_column(String(20), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    present: Mapped[int] = mapped_column(Integer, default=0)
    sync_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
