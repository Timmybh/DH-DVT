from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow


class YearCarryForward(Base):
    """Kết chuyển cuối năm (handoff §27): các mục chưa hoàn tất + số lượng còn lại + trạng thái chuyển chuyền/mapping cần để tiếp tục theo dõi sang năm sau."""

    __tablename__ = "year_carry_forwards"

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, index=True)  # năm khép sổ
    status: Mapped[str] = mapped_column(String(12), default="DRAFT", index=True)  # DRAFT | VALIDATED | FAILED | APPLIED
    source_version_id: Mapped[int] = mapped_column(Integer)
    target_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    report: Mapped[list] = mapped_column(JSON, default=list)  # danh sách kiểm tra: {code, ok, blocking, message}


class CarryForwardItem(Base):
    __tablename__ = "year_carry_forward_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    cf_id: Mapped[int] = mapped_column(ForeignKey("year_carry_forwards.id", ondelete="CASCADE"), index=True)
    row_uid: Mapped[str] = mapped_column(String(40), index=True)
    source_key: Mapped[str] = mapped_column(String(300), default="")
    factory_code: Mapped[str] = mapped_column(String(20), default="")
    line_raw: Mapped[str] = mapped_column(String(60), default="")
    po_number: Mapped[str] = mapped_column(String(60), default="")
    style_cc: Mapped[str] = mapped_column(String(60), default="")
    customer: Mapped[str] = mapped_column(String(100), default="")
    planned_qty: Mapped[float] = mapped_column(Float, default=0)
    sewn_qty: Mapped[float] = mapped_column(Float, default=0)
    fg_qty: Mapped[float] = mapped_column(Float, default=0)
    remaining_qty: Mapped[float] = mapped_column(Float, default=0)
    planned_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    has_transfer: Mapped[bool] = mapped_column(default=False)
    mapping_count: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN (đang dở) | NO_ACTUAL (chưa có thực tế — cần lập lại)
    row_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # toàn bộ dòng kế hoạch nguồn (ngày dạng ISO)


class YearArchive(Base):
    """Lưu trữ dữ liệu giao dịch/lịch sử theo năm ra tệp nén; Master/reference data không bao giờ bị lưu trữ chỉ vì cũ (§27)."""

    __tablename__ = "year_archives"

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(12), default="ARCHIVED", index=True)  # ARCHIVED | RESTORED | FAILED
    path: Mapped[str] = mapped_column(String(400), default="")
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)  # {table: {rows, sha256, file}}
    carry_forward_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
