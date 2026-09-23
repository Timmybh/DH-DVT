"""ERP QTCN sync (Task 2 — Issue #5): crosswalk thiết bị (quản trị, KHÔNG hard-code trong query) + exception queue
có thể resolve. Khác với `SyncRun`/`SyncRunItem` (app/models/data.py, log một lần cho một run) — exception ở đây
cần theo dõi trạng thái xử lý qua nhiều lần (OPEN -> RESOLVED/IGNORED), nên tách bảng riêng, vẫn liên kết `sync_run_id`.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow

# EXACT: khớp text canonical + duy nhất 2 chiều (seed tự động được). MANUAL_CONFIRMED: người xác nhận tay cho case
# POSSIBLE trước đây (Issue #5 review vòng 2 mục 4) — không tự suy đoán, phải qua người xác nhận.
MACHINE_MATCH_TYPES = ("EXACT", "MANUAL_CONFIRMED")


class MachineCrosswalk(Base):
    """Crosswalk ERP equipment identity (QTCN_DanhMucThietBi) -> DVT MachineType. Chỉ EXACT/MANUAL_CONFIRMED mới
    được service dùng để tự map machine_type_code; còn lại luôn là UNMAPPED_MACHINE_TYPE (BR-212)."""

    __tablename__ = "erp_qtcn_machine_crosswalk"
    __table_args__ = (UniqueConstraint("source_system", "source_equipment_code", name="uq_erp_machine_crosswalk_src"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_system: Mapped[str] = mapped_column(String(30), default="ERP_QTCN")
    source_equipment_code: Mapped[str] = mapped_column(String(50), index=True)  # QTCN_DanhMucThietBi.MaThietBi
    source_equipment_name: Mapped[str] = mapped_column(String(500), default="")  # TenThietBi tại thời điểm seed (evidence)
    machine_type_code: Mapped[str | None] = mapped_column(ForeignKey("machine_types.code"), nullable=True)
    match_type: Mapped[str] = mapped_column(String(20), default="EXACT")
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# Danh mục exception cuối (Issue #5 review vòng 2 mục 8)
EXCEPTION_CATEGORIES = (
    "MISSING_STYLE",
    "AMBIGUOUS_PROCESS",
    "NO_PUBLISHED_VERSION",
    "INCONSISTENT_VERSION_STATUS",
    "DUPLICATE_SEQUENCE",
    "MISSING_SEQUENCE",
    "UNMAPPED_OPERATION",
    "UNMAPPED_MACHINE_TYPE",
    "INVALID_SOURCE_RELATION",
    "INVALID_SAM",
    "OTHER",
)
RESOLUTION_STATUSES = ("OPEN", "RESOLVED", "IGNORED")


class TechProcessSyncException(Base):
    """Exception queue có resolution status/note (Issue #5 §10) — khác SyncRunItem (chỉ là log không đổi trạng thái)."""

    __tablename__ = "tech_process_sync_exceptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    sync_run_id: Mapped[int] = mapped_column(ForeignKey("sync_runs.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(30), index=True)
    source_key: Mapped[str] = mapped_column(String(200), default="")  # VD MaHang hoặc "QTCN#<Id>"
    source_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(String(500), default="")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    resolution_status: Mapped[str] = mapped_column(String(10), default="OPEN", index=True)
    resolution_note: Mapped[str] = mapped_column(String(500), default="")
    resolved_by: Mapped[str] = mapped_column(String(100), default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
