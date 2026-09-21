"""Danh mục nguồn lực Planning: Capacity Definition, Machine Capacity, yêu cầu máy theo mã hàng, lao động theo ngày."""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    # Cấp 1 — Danh mục loại máy (spec §6.1): phần bổ sung do người dùng quản lý, đồng bộ eGMF chỉ cập nhật `name`
    model: Mapped[str] = mapped_column(String(60), default="")
    machine_group: Mapped[str] = mapped_column(String(60), default="")
    process: Mapped[str] = mapped_column(String(60), default="")
    nominal_output_per_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    default_efficiency: Mapped[float | None] = mapped_column(Float, nullable=True)  # OEE mặc định 0..1
    changeover_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_bottleneck_capable: Mapped[bool] = mapped_column(Boolean, default=False)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")  # ACTIVE | INACTIVE (không xóa)
    note: Mapped[str] = mapped_column(String(300), default="")
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MachineCapacity(Base):
    """Số lượng/công suất máy của một chuyền theo nhóm máy."""

    __tablename__ = "machine_capacities"

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_code: Mapped[str] = mapped_column(String(20), index=True)
    line: Mapped[str] = mapped_column(String(20), index=True)
    machine_type: Mapped[str] = mapped_column(String(20), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)  # tổng máy được phân bổ cho chuyền (cấp 2)
    maintenance_quantity: Mapped[int] = mapped_column(Integer, default=0)  # đang bảo trì kéo dài (cố định); bảo trì theo lịch khai ở MachineMaintenance
    down_quantity: Mapped[int] = mapped_column(Integer, default=0)
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


class MachineSharing(Base):
    """Cấp 3a — Đăng ký mượn máy: xí nghiệp cho mượn máy sang chuyền/xí nghiệp khác trong một khoảng ngày. Không xóa, chỉ Ngưng áp dụng."""

    __tablename__ = "machine_sharing"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_type: Mapped[str] = mapped_column(String(20), index=True)
    from_factory: Mapped[str] = mapped_column(String(20), index=True)
    from_line: Mapped[str] = mapped_column(String(20), default="")  # trống = không trừ vào chuyền cụ thể của bên cho mượn
    to_factory: Mapped[str] = mapped_column(String(20), index=True)
    to_line: Mapped[str] = mapped_column(String(20), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", index=True)  # ACTIVE | INACTIVE
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status_changed_by: Mapped[str] = mapped_column(String(100), default="")
    status_reason: Mapped[str] = mapped_column(String(200), default="")


class MachineMaintenance(Base):
    """Cấp 3b — Lịch bảo trì máy theo xí nghiệp/chuyền: trong khoảng ngày số máy này không sẵn sàng."""

    __tablename__ = "machine_maintenance"

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_code: Mapped[str] = mapped_column(String(20), index=True)
    line: Mapped[str] = mapped_column(String(20), default="")
    machine_type: Mapped[str] = mapped_column(String(20), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(12), default="PLANNED")  # PLANNED | BREAKDOWN | OTHER
    reason: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", index=True)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status_changed_by: Mapped[str] = mapped_column(String(100), default="")
    status_reason: Mapped[str] = mapped_column(String(200), default="")


class ProductivityGrade(Base):
    """Cấp 1 — Danh mục bậc năng suất lao động 1..10; hệ số theo hiệu lực ngày, không xóa (spec §4)."""

    __tablename__ = "productivity_grades"
    __table_args__ = (Index("ix_pg_grade", "grade", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    grade: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(60), default="")
    productivity_factor: Mapped[float] = mapped_column(Float)  # 0.85 = 85%
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")  # ACTIVE | INACTIVE
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LaborStandard(Base):
    """Cấp 2 — Cơ cấu lao động chuẩn của một XN (hoặc một chuyền) và số người theo từng bậc. `line` trống = áp cho cả XN."""

    __tablename__ = "labor_standards"
    __table_args__ = (Index("ix_labstd_lookup", "factory_code", "line", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_code: Mapped[str] = mapped_column(String(20))
    line: Mapped[str] = mapped_column(String(20), default="")
    total_labor: Mapped[int] = mapped_column(Integer)  # Standard Labor — không bị ghi đè bởi hệ số
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")  # ACTIVE | RETIRED (bị thay bởi phiên bản mới) | INACTIVE
    version: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    details: Mapped[list["LaborStandardGradeDetail"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class LaborStandardGradeDetail(Base):
    __tablename__ = "labor_standard_grade_details"

    id: Mapped[int] = mapped_column(primary_key=True)
    labor_standard_id: Mapped[int] = mapped_column(ForeignKey("labor_standards.id"), index=True)
    grade: Mapped[int] = mapped_column(Integer)
    headcount: Mapped[int] = mapped_column(Integer, default=0)


class MachineStyleOutput(Base):
    """Năng suất đăng ký của một loại máy theo mã hàng (style): pcs/ngày một máy loại này làm ra khi chạy mã hàng đó. Chỉ khai báo; chưa dùng trong kiểm tra Recheck."""

    __tablename__ = "machine_style_outputs"
    __table_args__ = (Index("ix_msout_lookup", "machine_type", "style_cc", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_type: Mapped[str] = mapped_column(String(20))
    style_cc: Mapped[str] = mapped_column(String(60))
    output_per_day: Mapped[float | None] = mapped_column(Float, nullable=True)  # công suất; có thể chưa khai báo (mới có số máy cần)
    required_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)  # số máy loại này cần khi chạy mã hàng (từ QTCN hoặc nhập tay)
    source: Mapped[str] = mapped_column(String(10), default="MANUAL")  # MANUAL | QTCN
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")  # ACTIVE | INACTIVE (không xóa)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status_changed_by: Mapped[str] = mapped_column(String(100), default="")
    status_reason: Mapped[str] = mapped_column(String(200), default="")


class MachineSharedPool(Base):
    """Đăng ký dùng chung: N máy của một loại (thuộc một XN) dùng chung cho NHIỀU chuyền, không thuộc riêng chuyền nào. Không xóa, chỉ Ngưng áp dụng."""

    __tablename__ = "machine_shared_pools"

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_code: Mapped[str] = mapped_column(String(20), index=True)
    machine_type: Mapped[str] = mapped_column(String(20), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    lines: Mapped[list] = mapped_column(JSON, default=list)  # các chuyền cùng sử dụng
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", index=True)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status_changed_by: Mapped[str] = mapped_column(String(100), default="")
    status_reason: Mapped[str] = mapped_column(String(200), default="")
