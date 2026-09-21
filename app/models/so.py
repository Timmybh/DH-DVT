from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow


class PlanningSO(Base):
    """SO (Sales/Business Order) = danh tính nghiệp vụ bền vững xuyên suốt Unplanned → Planned → PO tạm → PO ERP → đổi PO → mượn PO → Split/Merge → Transfer XN → Actual.
    Định dạng SO/YY/NNNNNN (6 chữ số, reset theo năm), sinh tự động, KHÔNG sửa, KHÔNG mã hóa XN/PO vào số SO. Chỉ `description` do nghiệp vụ chỉnh."""

    __tablename__ = "planning_sos"
    __table_args__ = (UniqueConstraint("year2", "seq", name="uq_so_year_seq"), Index("ix_so_identity_key", "identity_key"))

    id: Mapped[int] = mapped_column(primary_key=True)
    so_number: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # SO/26/000001
    year2: Mapped[int] = mapped_column(Integer)  # YY
    seq: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(300), default="")  # SO Description (nghiệp vụ chỉnh được)
    customer: Mapped[str] = mapped_column(String(100), default="")
    style_cc: Mapped[str] = mapped_column(String(60), default="")
    model_code: Mapped[str] = mapped_column(String(60), default="")
    season: Mapped[str] = mapped_column(String(30), default="")
    sport: Mapped[str] = mapped_column(String(60), default="")
    planned_qty: Mapped[float] = mapped_column(Float, default=0)
    origin_factory: Mapped[str] = mapped_column(String(20), default="")  # nơi bắt đầu (để truy vết)
    current_factory: Mapped[str] = mapped_column(String(20), default="")  # XN đang thực hiện (thay đổi qua SO Transfer, không sửa tay)
    window_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_po: Mapped[str] = mapped_column(String(80), default="")
    temp_po: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")  # ACTIVE | CLOSED
    note: Mapped[str] = mapped_column(String(400), default="")
    source: Mapped[str] = mapped_column(String(12), default="IMPORT")  # IMPORT | BULK_TEMP (cấp tạm hàng loạt cho UAT) | MANUAL
    identity_key: Mapped[str] = mapped_column(String(320), default="")  # khóa nhận diện khi import lại: không cấp lại SO cho cùng business item
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(100), default="")


class SOSequence(Base):
    """Bộ đếm SO theo năm (khóa dòng khi cấp số để không trùng)."""

    __tablename__ = "so_sequences"

    year2: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)


class PlanningSOExternalIdentity(Base):
    """PO chỉ là danh tính ngoài / bí danh của SO: PLAN_NOTE | TEMP_PO | ERP_PO | CUSTOMER_PO | PREVIOUS_PO. Đổi PO không đổi SO."""

    __tablename__ = "planning_so_external_identities"
    __table_args__ = (Index("ix_so_ext_value", "identity_type", "identity_value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    planning_so_id: Mapped[int] = mapped_column(ForeignKey("planning_sos.id", ondelete="CASCADE"), index=True)
    source_system: Mapped[str] = mapped_column(String(20), default="PLAN")
    identity_type: Mapped[str] = mapped_column(String(14), default="PLAN_NOTE")
    identity_value: Mapped[str] = mapped_column(String(120), index=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")  # ACTIVE | INACTIVE (không xóa)
    reason: Mapped[str] = mapped_column(Text, default="")
