"""Quy trình công nghệ 3 tầng (Task 1 — Issue #3): Technology Process (Style/Model) -> Version theo Layer -> Operation (Machine + Manpower + SAM + Evidence).

Nguồn sự thật kỹ thuật (BR-001): SAM không còn là mô hình 3 tầng độc lập — SAM chỉ là chỉ số đi theo từng TechnologyProcessVersion,
giải thích được từ các Operation bên trong version đó (BR-002, BR-003). `StyleSam` (app/models/resources.py) được GIỮ NGUYÊN làm
nguồn ước lượng tạm thời, KHÔNG bị thay thế hay migrate ở đây.

Một TechnologyProcess là family logic cho một cặp (style_cc, model_code), chứa cả 3 layer; mỗi layer có chuỗi version riêng
(version_no unique trong phạm vi process+layer — BR-005). Version APPROVED bất biến về nội dung kỹ thuật (BR-004, V-007).
"""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base, utcnow

# Layer — thuật ngữ đã chốt (Issue #3 §2), KHÔNG đổi tên
LAYERS = ("CURRENT_PROCESS", "OPTIMIZED_CURRENT_TECHNOLOGY", "FUTURE_TECHNOLOGY")
LAYER_LABEL = {"CURRENT_PROCESS": "Current Process", "OPTIMIZED_CURRENT_TECHNOLOGY": "Optimized Current Technology", "FUTURE_TECHNOLOGY": "Future Technology"}

# Workflow version — §8 (forward-only trong Task 1, xem BR §6 Issue #3 review)
VERSION_STATUSES = ("DRAFT", "SIMULATED", "REVIEWED", "APPROVED", "RETIRED")
SOURCE_TYPES = ("ERP", "ENGINEERING", "AUTO_GENERATED", "MANUAL", "IMPORT", "TECHNOLOGY_SCOUTING")
SAM_STATUSES = ("EMPTY", "COMPLETE", "INCOMPLETE")  # BR-017: thiếu SAM của operation bắt buộc -> INCOMPLETE, không lấy default/median chỗ khác

# Task 3 (Issue #7 §BR-311, review mục 6) — generator Task 3 chỉ tự set UNCHANGED/MACHINE_SUBSTITUTION; các giá trị
# còn lại forward-compatible cho thay đổi thủ công sau này.
OPERATION_CHANGE_TYPES = ("UNCHANGED", "MACHINE_SUBSTITUTION", "AUTOMATION_UPGRADE", "MANPOWER_CHANGE", "TIME_CHANGE", "OTHER_ENGINEERING_CHANGE")


class TechnologyProcess(Base):
    """§6.1 — family logic cho một cặp (style_cc, model_code); chứa cả 3 layer bên trong (mỗi layer có chuỗi version riêng)."""

    __tablename__ = "technology_processes"
    __table_args__ = (UniqueConstraint("style_cc", "model_code", name="uq_tech_process_style_model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    process_code: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # sinh tự động, bất biến sau khi tạo (business identity)
    style_cc: Mapped[str] = mapped_column(String(60), index=True)
    model_code: Mapped[str] = mapped_column(String(60), default="", index=True)  # default "" (không NULL) để unique constraint null-safe
    product_family: Mapped[str | None] = mapped_column(String(60), nullable=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", index=True)  # ACTIVE | INACTIVE — không xóa (master data, giống MachineType)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    versions: Mapped[list["TechnologyProcessVersion"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="TechnologyProcessVersion.id", backref="technology_process")


class TechnologyProcessVersion(Base):
    """§6.2 — một phiên bản kỹ thuật cụ thể của một layer. Total SAM = SUM(sam_minutes của Operation active) — BR-016, không hidden efficiency factor."""

    __tablename__ = "technology_process_versions"
    __table_args__ = (
        UniqueConstraint("technology_process_id", "layer", "version_no", name="uq_tpv_process_layer_version"),  # BR-005
        Index("ix_tpv_process_layer", "technology_process_id", "layer", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    technology_process_id: Mapped[int] = mapped_column(ForeignKey("technology_processes.id", ondelete="CASCADE"), index=True)
    layer: Mapped[str] = mapped_column(String(32), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="DRAFT", index=True)
    source_type: Mapped[str] = mapped_column(String(20), default="MANUAL")
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)  # §6.4 evidence tối thiểu (source_ref)
    source_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # §6.4 evidence tối thiểu (source_date)
    derived_from_version_id: Mapped[int | None] = mapped_column(ForeignKey("technology_process_versions.id", ondelete="SET NULL"), nullable=True)  # BR-006 — không auto-sync sau khi tạo
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    total_sam_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    sam_status: Mapped[str] = mapped_column(String(10), default="EMPTY")  # EMPTY | COMPLETE | INCOMPLETE — BR-017
    expected_output_per_day: Mapped[float | None] = mapped_column(Float, nullable=True)  # nullable/optional — KHÔNG tự tính, không có công thức duyệt (Issue #3 review mục 5)
    required_labor: Mapped[int | None] = mapped_column(Integer, nullable=True)  # nullable/optional — KHÔNG tự tính

    assumptions_json: Mapped[dict] = mapped_column(JSON, default=dict)  # giả định đi kèm khi expected_output_per_day/required_labor được nhập tay
    note: Mapped[str] = mapped_column(String(500), default="")

    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str] = mapped_column(String(100), default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_by: Mapped[str] = mapped_column(String(100), default="")
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    bootstrap_fingerprint: Mapped[str] = mapped_column(String(120), default="", index=True)  # BR-015 idempotency (Task 2, Current Process import) — kiểm tra ở service, không unique-constraint cứng (nhiều DRAFT được phép)
    # Task 3 (Issue #7 review mục 5): KHÔNG dùng chung bootstrap_fingerprint cho Layer 2 — ngữ nghĩa khác nhau
    # (bootstrap_fingerprint = snapshot nguồn ERP lúc import; generation_fingerprint = snapshot THỰC TẾ của source
    # version + rule + compatibility mapping + lựa chọn người dùng TẠI THỜI ĐIỂM generate, vì Current Process DRAFT
    # có thể bị sửa sau import nên chỉ hash lại bootstrap_fingerprint/id của nguồn là chưa đủ).
    generation_fingerprint: Mapped[str] = mapped_column(String(120), default="", index=True)

    operations: Mapped[list["TechnologyProcessOperation"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="TechnologyProcessOperation.sequence_no")


class TechnologyProcessOperation(Base):
    """§6.3 — một công đoạn trong process version. `is_active=False` = đã "gỡ" (soft — giữ lịch sử); BR-016 chỉ cộng SAM của operation active."""

    __tablename__ = "technology_process_operations"
    __table_args__ = (Index("ix_tpo_version_seq", "process_version_id", "sequence_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    process_version_id: Mapped[int] = mapped_column(ForeignKey("technology_process_versions.id", ondelete="CASCADE"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer)  # duy nhất/deterministic trong các operation ACTIVE của version (V-003, enforce ở service)
    operation_code: Mapped[str] = mapped_column(String(60), default="")
    operation_name: Mapped[str] = mapped_column(String(200), default="")

    machine_type_code: Mapped[str | None] = mapped_column(ForeignKey("machine_types.code"), nullable=True)
    machine_model_id: Mapped[int | None] = mapped_column(ForeignKey("machine_models.id"), nullable=True)

    # Nullable (Task 2, Issue #5 review vòng 2 mục 3): 0 có nghĩa nghiệp vụ khác "không biết" — ERP import không có
    # observed operator count thật (Detail.SoLaoDong là giá trị phân bổ tính toán, không phải headcount quan sát) nên
    # phải để NULL thay vì mặc định 0. KHÔNG đặt default= ở cột: SQLAlchemy áp default bất cứ khi nào giá trị hiện tại
    # là None, kể cả khi None được set TƯỜNG MINH — service layer (add_operation) mới là nơi quyết định 0 vs None.
    # Manual entry (Task 1 UI) vẫn giữ hành vi cũ: không truyền field -> service tự set 0.
    operator_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # >= 0 nếu có giá trị — V-005

    helper_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sam_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)  # > 0 nếu có giá trị — V-004
    cycle_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_output_per_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    automation_level: Mapped[str] = mapped_column(String(60), default="")
    setup_changeover_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_defect_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_type: Mapped[str] = mapped_column(String(20), default="MANUAL")
    evidence_note: Mapped[str] = mapped_column(String(300), default="")  # §6.4 evidence
    evidence_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)  # §6.4 evidence
    source_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # §6.4 evidence

    # Task 3 (Issue #7 review mục 6) — chỉ có ý nghĩa với operation thuộc Layer 2 trở lên; Layer 1 (Current Process)
    # luôn null. Generator Task 3 CHỈ tự set UNCHANGED/MACHINE_SUBSTITUTION; các giá trị còn lại (AUTOMATION_UPGRADE,
    # MANPOWER_CHANGE, TIME_CHANGE, OTHER_ENGINEERING_CHANGE) để dành cho thay đổi thủ công sau này, không tự set.
    change_type: Mapped[str | None] = mapped_column(String(30), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # gỡ operation = soft (giữ lịch sử/audit); version APPROVED thì không đổi được nữa (V-007)

    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
