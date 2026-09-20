from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow


class ActualObservation(Base):
    """Lịch sử thực tế (handoff §26): mỗi lần đồng bộ ghi lại trạng thái MỚI hoặc THAY ĐỔI của từng (PO, xí nghiệp, chuyền); không ghi đè trạng thái cũ.
    Trạng thái tại lần đồng bộ N = quan sát mới nhất có sync_run_id <= N của từng khóa."""

    __tablename__ = "actual_observations"
    __table_args__ = (
        UniqueConstraint("actual_key", "sync_run_id", name="uq_actual_obs"),
        Index("ix_actual_obs_po", "po"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    actual_key: Mapped[str] = mapped_column(String(160), index=True)  # PO|XN|CHUYEN (khóa nghiệp vụ, không dùng ID nội bộ eGMF)
    fingerprint: Mapped[str] = mapped_column(String(300), index=True)  # PO|STYLE|CUSTOMER đã chuẩn hóa
    sync_run_id: Mapped[int] = mapped_column(Integer, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_system: Mapped[str] = mapped_column(String(20), default="EGMF")
    source_ref: Mapped[str] = mapped_column(String(80), default="")  # đối tượng nguồn (phụ trợ), VD Report_BaoCaoMayRa
    po: Mapped[str] = mapped_column(String(80))
    style: Mapped[str] = mapped_column(String(60), default="")
    customer: Mapped[str] = mapped_column(String(100), default="")
    factory_code: Mapped[str] = mapped_column(String(20), default="")
    line: Mapped[str] = mapped_column(String(20), default="")
    qty: Mapped[int] = mapped_column(Integer, default=0)
    sewn_qty: Mapped[int] = mapped_column(Integer, default=0)  # may xong lũy kế
    fg_qty: Mapped[int] = mapped_column(Integer, default=0)  # nhập kho thành phẩm lũy kế
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sewn_done_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    fg_done_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_seen: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)
    changes: Mapped[dict] = mapped_column(JSON, default=dict)  # {"sewn_qty": [cũ, mới], ...} so với quan sát trước


class ActualMapping(Base):
    """Bản ghi mapping Actual -> Planning (handoff §25). Khóa là khóa nghiệp vụ nên khớp lại được nếu ID eGMF đổi sau khi migrate/rebuild."""

    __tablename__ = "actual_mappings"
    __table_args__ = (Index("ix_actual_map_status", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actual_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    source_system: Mapped[str] = mapped_column(String(20), default="EGMF")
    source_id: Mapped[str] = mapped_column(String(80), default="")  # ID nguồn — chỉ tham chiếu phụ
    fingerprint: Mapped[str] = mapped_column(String(300), default="")
    po: Mapped[str] = mapped_column(String(80), default="", index=True)
    style: Mapped[str] = mapped_column(String(60), default="")
    model_code: Mapped[str] = mapped_column(String(60), default="")
    customer: Mapped[str] = mapped_column(String(100), default="")
    factory_code: Mapped[str] = mapped_column(String(20), default="")
    line: Mapped[str] = mapped_column(String(20), default="")
    attrs: Mapped[dict] = mapped_column(JSON, default=dict)  # số lượng / ngày liên quan
    source_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # quan sát gần nhất
    status: Mapped[str] = mapped_column(String(16), default="UNMATCHED")  # MATCHED | REVIEW | UNMATCHED | OUT_OF_PLAN (thuộc kỳ trước kế hoạch, không phải ngoại lệ) | IGNORED
    method: Mapped[str] = mapped_column(String(24), default="")  # AUTO_FULL | AUTO_STYLE | AUTO_PO | AUTO_STYLE_WINDOW | MANUAL | IGNORED
    confidence: Mapped[float] = mapped_column(Float, default=0)
    reason: Mapped[str] = mapped_column(String(300), default="")
    candidates: Mapped[list] = mapped_column(JSON, default=list)  # row_uid ứng viên khi chưa quyết được
    mapped_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mapped_row_uid: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    mapped_source_key: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_by: Mapped[str] = mapped_column(String(100), default="")
