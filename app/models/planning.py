from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow


class WorkingCalendarRule(Base):
    """Lịch làm việc mức ngày (handoff §15). Kế thừa Company -> XN -> Line, phạm vi hẹp hơn thắng."""

    __tablename__ = "working_calendar_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(10), index=True)  # COMPANY | XN | LINE
    scope_key: Mapped[str] = mapped_column(String(40), default="", index=True)  # '' | 'XN1' | 'XN1:07'
    rule_type: Mapped[str] = mapped_column(String(12))  # WEEKLY_OFF | DATE_OFF | OVERTIME
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0=Thứ hai .. 6=Chủ nhật
    rule_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlanningEditSession(Base):
    """Phiên soạn thảo độc quyền (handoff §2.1). Chỉ MỘT phiên ACTIVE tại mọi thời điểm (ràng buộc ở mức DB)."""

    __tablename__ = "planning_edit_sessions"
    __table_args__ = (
        Index("uq_planning_single_active_session", "status", unique=True, postgresql_where=text("status = 'ACTIVE'")),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # EditSessionId do backend cấp
    user_id: Mapped[int] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")  # ACTIVE | CLOSED | EXPIRED | REVOKED
    close_reason: Mapped[str] = mapped_column(String(100), default="")
    base_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Kết quả Recheck gần nhất, gắn với đúng DraftRevision + nội dung thao tác (handoff §11)
    last_recheck_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_recheck_hash: Mapped[str] = mapped_column(String(64), default="")
    last_recheck_result: Mapped[str] = mapped_column(String(10), default="")
    last_recheck_trace: Mapped[str] = mapped_column(String(40), default="")


class PlanningVersion(Base):
    """Phiên bản kế hoạch cấp Tổng công ty (handoff §19, §21). Commit = bất biến."""

    __tablename__ = "planning_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # 2026.W26.Master.v01.f01
    year: Mapped[int] = mapped_column(Integer)
    week: Mapped[int] = mapped_column(Integer)
    family: Mapped[str] = mapped_column(String(30), default="Master")
    major: Mapped[int] = mapped_column(Integer)  # v
    minor: Mapped[int | None] = mapped_column(Integer, nullable=True)  # f (con của v)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="COMMITTED", index=True)  # COMMITTED|ISSUED|SUPERSEDED
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_session_id: Mapped[str] = mapped_column(String(40), default="")
    base_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    recheck_result: Mapped[str] = mapped_column(String(10), default="")  # PASS | WARNING | ERROR
    recheck_trace_id: Mapped[str] = mapped_column(String(40), default="")
    recheck_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recheck_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_by: Mapped[str] = mapped_column(String(100), default="")


class PlanningVersionRow(Base):
    __tablename__ = "planning_version_rows"
    __table_args__ = (
        Index("ix_pvr_version_factory_line", "version_id", "factory_code", "primary_line"),
        Index("ix_pvr_version_uid", "version_id", "row_uid", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("planning_versions.id", ondelete="CASCADE"), index=True)
    row_uid: Mapped[str] = mapped_column(String(40))  # rowId bất biến, ổn định qua các version
    sequence: Mapped[int] = mapped_column(Integer)  # thứ tự nghiệp vụ trong (XN, chuyền) sau commit
    origin: Mapped[str] = mapped_column(String(14), default="EXISTING")  # EXISTING | DRAFT_NEW
    source_key: Mapped[str] = mapped_column(String(300), default="", index=True)  # khóa nghiệp vụ ổn định (§25)
    source_plan_row_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # chỉ tham chiếu kỹ thuật phụ
    factory_code: Mapped[str] = mapped_column(String(20), default="")
    primary_line: Mapped[str] = mapped_column(String(20), default="")
    line_raw: Mapped[str] = mapped_column(String(60), default="")  # chuỗi hiển thị "4 + 5 + 9" (chỉ để trình bày)
    line_assignments: Mapped[list] = mapped_column(JSON, default=list)  # cấu trúc thật: ["4","5","9"]
    transfer: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {from,to,effective_date,planned_remaining_qty,status}
    po_number: Mapped[str] = mapped_column(String(60), default="")
    style_cc: Mapped[str] = mapped_column(String(60), default="")
    model_code: Mapped[str] = mapped_column(String(60), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    customer: Mapped[str] = mapped_column(String(100), default="")
    sport: Mapped[str] = mapped_column(String(60), default="")
    season: Mapped[str] = mapped_column(String(30), default="")
    quantity: Mapped[float] = mapped_column(Float, default=0)
    capacity: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    begin_prod_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_prod_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    warehouse_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    chd: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(400), default="")
    extra: Mapped[dict] = mapped_column(JSON, default=dict)  # overrides: {"begin_prod_date": {"source":"OVERRIDE","calculated":"..."}}
