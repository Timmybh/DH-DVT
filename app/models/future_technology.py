"""Future Technology & Technology Scouting (Task 4 — Issue #9, GPT APPROVED_TO_IMPLEMENT 2026-09-25).

Entity riêng, KHÔNG reuse MachineModel làm entity chính (lifecycle/evidence khác Layer 2; không làm đổi eligibility
semantics của Task 3). `machine_model_id` chỉ là liên kết tham chiếu nullable. Evidence và status history là append-only.
Không xóa cứng candidate — chỉ đổi status.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow

# BR-402 — lifecycle
FUTURE_CANDIDATE_STATUSES = ("DISCOVERED", "UNDER_REVIEW", "TRIAL", "APPROVED_FOR_FUTURE", "REJECTED", "INACTIVE")
# GPT chốt (Issue #9 mục 9): REJECTED không tự reactivate trong Task 4; INACTIVE -> UNDER_REVIEW để reactivate.
FUTURE_CANDIDATE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DISCOVERED": ("UNDER_REVIEW", "INACTIVE"),
    "UNDER_REVIEW": ("TRIAL", "REJECTED", "INACTIVE"),
    "TRIAL": ("APPROVED_FOR_FUTURE", "REJECTED", "INACTIVE"),
    "APPROVED_FOR_FUTURE": ("REJECTED", "INACTIVE"),
    "INACTIVE": ("UNDER_REVIEW",),
    "REJECTED": (),
}
IDENTITY_EDITABLE_STATUSES = ("DISCOVERED", "UNDER_REVIEW")
REASON_REQUIRED_TARGETS = ("REJECTED", "INACTIVE")

EVIDENCE_SOURCE_KINDS = ("MANUFACTURER_SPEC", "TRIAL_REPORT", "SUPPLIER_QUOTE", "INTERNAL_TEST", "OTHER")
EVIDENCE_BASES = ("CLAIMED", "OBSERVED", "TRIALED")
EVIDENCE_METRIC_CODES = ("CYCLE_TIME", "OUTPUT", "OPERATOR", "OTHER")

FUTURE_COMPATIBILITY_STATUSES = ("PROPOSED", "TRIAL", "APPROVED", "REJECTED")


class FutureTechnologyCandidate(Base):
    __tablename__ = "future_technology_candidates"
    __table_args__ = (Index("ix_ftc_status", "status"), Index("ix_ftc_machine_type", "machine_type_code"))

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # sinh tự động, bất biến
    machine_type_code: Mapped[str] = mapped_column(ForeignKey("machine_types.code"))  # bắt buộc — Task 4 không tự tạo MachineType
    machine_model_id: Mapped[int | None] = mapped_column(ForeignKey("machine_models.id"), nullable=True)  # tham chiếu tùy chọn
    brand: Mapped[str] = mapped_column(String(100), default="")
    model_name: Mapped[str] = mapped_column(String(100), default="")
    technology_name: Mapped[str] = mapped_column(String(150), default="")
    automation_level: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(20), default="DISCOVERED")
    status_reason: Mapped[str] = mapped_column(String(300), default="")
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str] = mapped_column(String(100), default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FutureTechnologyEvidence(Base):
    """Append-only — sửa/bổ sung = thêm dòng mới, không overwrite, không xóa."""

    __tablename__ = "future_technology_evidence"
    __table_args__ = (Index("ix_fte_candidate", "candidate_id"), Index("ix_fte_metric", "metric_code"), Index("ix_fte_date", "evidence_date"))

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("future_technology_candidates.id"))
    source_ref: Mapped[str] = mapped_column(String(200))  # bắt buộc (BR-401/403)
    source_kind: Mapped[str] = mapped_column(String(20), default="OTHER")
    basis: Mapped[str] = mapped_column(String(10), default="CLAIMED")
    metric_code: Mapped[str] = mapped_column(String(12), default="OTHER")
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(30), default="")
    evidence_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    added_by: Mapped[str] = mapped_column(String(100), default="")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FutureTechnologyCompatibility(Base):
    """Operation ↔ Future candidate, explicit/auditable (BR-405). Bảng riêng — KHÔNG dùng chung OperationMachineCompatibility
    của Task 3 để generator Layer 2 không nhặt nhầm dòng Future."""

    __tablename__ = "future_technology_compatibility"
    __table_args__ = (
        Index("ix_ftcomp_operation", "operation_code"), Index("ix_ftcomp_source_type", "source_machine_type_code"), Index("ix_ftcomp_candidate", "candidate_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("future_technology_candidates.id"))
    operation_code: Mapped[str] = mapped_column(String(60))
    source_machine_type_code: Mapped[str | None] = mapped_column(ForeignKey("machine_types.code"), nullable=True)
    compatibility_status: Mapped[str] = mapped_column(String(12), default="PROPOSED")
    evidence_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    evidence_note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FutureTechnologyStatusHistory(Base):
    """Append-only — history thật của lifecycle (không dựa vào write_audit vốn best-effort)."""

    __tablename__ = "future_technology_status_history"
    __table_args__ = (Index("ix_ftsh_candidate_time", "candidate_id", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("future_technology_candidates.id"))
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(300), default="")
    actor: Mapped[str] = mapped_column(String(100), default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
