"""Compatibility quản trị: operation nào tương thích máy nào để đề xuất thay thế (Task 3 — Issue #7).
Khác `MachineModel.status` (nói về bản thân máy/model đang Candidate/Trial/Approved) — `compatibility_status`
nói về quan hệ "operation này có thể dùng máy này" đã được kỹ thuật xác nhận tới mức nào (BR-309, GPT review mục 1).
Không xóa cứng — chỉ đổi status."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow

COMPATIBILITY_STATUSES = ("PROPOSED", "TRIAL", "APPROVED", "REJECTED")


class OperationMachineCompatibility(Base):
    __tablename__ = "operation_machine_compatibility"

    id: Mapped[int] = mapped_column(primary_key=True)
    operation_code: Mapped[str] = mapped_column(String(60), index=True)  # bắt buộc — không suy đoán theo operation_name
    source_machine_type_code: Mapped[str | None] = mapped_column(ForeignKey("machine_types.code"), nullable=True)
    candidate_machine_type_code: Mapped[str] = mapped_column(ForeignKey("machine_types.code"))
    candidate_machine_model_id: Mapped[int | None] = mapped_column(ForeignKey("machine_models.id"), nullable=True)  # null = type-level compatibility
    compatibility_status: Mapped[str] = mapped_column(String(12), default="PROPOSED", index=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    evidence_note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
