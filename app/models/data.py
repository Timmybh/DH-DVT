from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_code: Mapped[str] = mapped_column(String(30), unique=True, index=True)  # SYNC-20260920-0031
    source: Mapped[str] = mapped_column(String(30), index=True)  # EGMF_REVENUE | PLAN_EXCEL
    trigger_type: Mapped[str] = mapped_column(String(20), default="MANUAL")  # MANUAL | SCHEDULED | RETRY
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")  # RUNNING|SUCCEEDED|PARTIAL|FAILED
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    total_records: Mapped[int] = mapped_column(Integer, default=0)
    matched: Mapped[int] = mapped_column(Integer, default=0)
    unmatched: Mapped[int] = mapped_column(Integer, default=0)
    ambiguous: Mapped[int] = mapped_column(Integer, default=0)
    updated_rows: Mapped[int] = mapped_column(Integer, default=0)
    trace_id: Mapped[str] = mapped_column(String(40), default="")
    triggered_by: Mapped[str] = mapped_column(String(100), default="")
    retry_of: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class SyncRunItem(Base):
    __tablename__ = "sync_run_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("sync_runs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # UNMATCHED | AMBIGUOUS | ERROR | INFO
    source_object: Mapped[str] = mapped_column(String(120), default="")
    source_key: Mapped[str] = mapped_column(String(200), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class RevenueDaily(Base):
    __tablename__ = "revenue_daily"
    __table_args__ = (UniqueConstraint("factory_id", "report_date", name="uq_revenue_daily"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_id: Mapped[int] = mapped_column(ForeignKey("factories.id"), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    plan: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    remaining: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="EGMF")  # EGMF | DEMO
    sync_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RevenueMonthly(Base):
    __tablename__ = "revenue_monthly"
    __table_args__ = (UniqueConstraint("factory_id", "year", "month", name="uq_revenue_monthly"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_id: Mapped[int] = mapped_column(ForeignKey("factories.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    plan: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    remaining: Mapped[float | None] = mapped_column(Float, nullable=True)
    declared_by: Mapped[str] = mapped_column(String(200), default="")
    declared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="EGMF")
    sync_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RevenueYearly(Base):
    __tablename__ = "revenue_yearly"
    __table_args__ = (UniqueConstraint("factory_id", "year", name="uq_revenue_yearly"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_id: Mapped[int] = mapped_column(ForeignKey("factories.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    plan: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    remaining: Mapped[float | None] = mapped_column(Float, nullable=True)
    declared_by: Mapped[str] = mapped_column(String(200), default="")
    declared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="EGMF")
    sync_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PlanImportBatch(Base):
    """Mỗi lần nhập file kế hoạch SX. Chỉ batch mới nhất (is_current) được dùng cho dashboard."""

    __tablename__ = "plan_import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    imported_by: Mapped[str] = mapped_column(String(100), default="")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sync_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class PlanRow(Base):
    __tablename__ = "plan_rows"
    __table_args__ = (Index("ix_plan_rows_batch_pstatus", "batch_id", "planning_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("plan_import_batches.id", ondelete="CASCADE"), index=True)
    # Ba chiều ĐỘC LẬP — không gộp thành một phân loại "chưa khớp/chưa lên KH":
    planning_status: Mapped[str] = mapped_column(String(10))  # UNPLANNED (Chưa lên KH) | PLANNED
    factory_assignment: Mapped[str] = mapped_column(String(12), default="KNOWN")  # KNOWN | UNASSIGNED (chưa xác định XN)
    mapping_status: Mapped[str] = mapped_column(String(8), default="OK")  # OK | WARNING
    mapping_note: Mapped[str] = mapped_column(String(200), default="")
    fac_raw: Mapped[str] = mapped_column(String(20), default="")  # giá trị FAC/XN gốc trong file
    factory_id: Mapped[int | None] = mapped_column(ForeignKey("factories.id"), nullable=True, index=True)
    line_raw: Mapped[str] = mapped_column(String(60), default="")
    po_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sport: Mapped[str] = mapped_column(String(60), default="")
    season: Mapped[str] = mapped_column(String(30), default="")
    po_number: Mapped[str] = mapped_column(String(60), default="")
    style_cc: Mapped[str] = mapped_column(String(60), default="")
    model_code: Mapped[str] = mapped_column(String(60), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    customer: Mapped[str] = mapped_column(String(100), default="")
    quantity: Mapped[float] = mapped_column(Float, default=0)
    worker: Mapped[float | None] = mapped_column(Float, nullable=True)
    capacity: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    begin_prod_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_prod_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    warehouse_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    chd: Mapped[date | None] = mapped_column(Date, nullable=True)
    ehd_etd: Mapped[date | None] = mapped_column(Date, nullable=True)
    gap_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    status_text: Mapped[str] = mapped_column(String(40), default="")
    note: Mapped[str] = mapped_column(String(400), default="")
    destination: Mapped[str] = mapped_column(String(100), default="")
    process: Mapped[str] = mapped_column(String(60), default="")
    risk: Mapped[str] = mapped_column(String(12), default="OK", index=True)  # OK|ADVANCE|LATE|MATERIAL
    risk_reason: Mapped[str] = mapped_column(String(200), default="")
    grid: Mapped[dict] = mapped_column(JSON, default=dict)  # các cột Excel hiển thị trong lưới Planning (không dùng để tính)
    so_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # SO (danh tính nghiệp vụ) — cấp ngay từ Unplanned


class LaborHeadcount(Base):
    __tablename__ = "labor_headcount"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("plan_import_batches.id", ondelete="CASCADE"), index=True)
    factory_id: Mapped[int | None] = mapped_column(ForeignKey("factories.id"), nullable=True, index=True)
    team: Mapped[str] = mapped_column(String(20), default="")
    headcount: Mapped[int] = mapped_column(Integer, default=0)
    as_of_text: Mapped[str] = mapped_column(String(100), default="")


class QaDefectDaily(Base):
    """Tổng số lỗi theo ngày / xí nghiệp / nhóm kiểm tra (Total Defect Count = số lần xuất hiện lỗi, không phải tỷ lệ sản phẩm lỗi)."""

    __tablename__ = "qa_defect_daily"
    __table_args__ = (UniqueConstraint("factory_id", "category", "day", name="uq_qa_defect_daily"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_id: Mapped[int] = mapped_column(ForeignKey("factories.id"), index=True)
    category: Mapped[str] = mapped_column(String(12), index=True)  # DAU_CHUYEN | INLINE | ENDLINE | PREFINAL
    day: Mapped[date] = mapped_column(Date, index=True)
    defect_count: Mapped[int] = mapped_column(Integer, default=0)
    sync_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PoProgress(Base):
    """Tiến độ thực tế theo PO/chuyền (snapshot mới nhất từ eGMF Report_BaoCaoMayRa): may xong, nhập kho TP, hạn giao."""

    __tablename__ = "po_progress"
    __table_args__ = (UniqueConstraint("po", "line", "factory_id", name="uq_po_progress"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    po: Mapped[str] = mapped_column(String(80), index=True)
    line: Mapped[str] = mapped_column(String(20), default="")
    factory_id: Mapped[int] = mapped_column(ForeignKey("factories.id"), index=True)
    customer: Mapped[str] = mapped_column(String(100), default="")
    style: Mapped[str] = mapped_column(String(60), default="")
    qty: Mapped[int] = mapped_column(Integer, default=0)
    sewn_qty: Mapped[int] = mapped_column(Integer, default=0)
    fg_qty: Mapped[int] = mapped_column(Integer, default=0)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # NgayXuatHang
    sewn_done_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    fg_done_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    last_seen: Mapped[date | None] = mapped_column(Date, nullable=True)
    sync_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PoPackDaily(Base):
    """Số lượng đóng gói đã xác nhận theo PO / ngày (eGMF Lib_XacNhanTemDongGoi: mỗi dòng = một thùng được quét xác nhận tem)."""

    __tablename__ = "po_pack_daily"
    __table_args__ = (UniqueConstraint("po", "day", name="uq_po_pack_daily"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    po: Mapped[str] = mapped_column(String(80), index=True)
    day: Mapped[date] = mapped_column(Date)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    sync_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
