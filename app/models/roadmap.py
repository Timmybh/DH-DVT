"""Roadmap Simulation Foundation (Task 5 — Issue #11, GPT APPROVED_TO_IMPLEMENT 2026-09-25).

Scenario -> Version (khóa từ READY) -> Milestone -> Target. Run là IMMUTABLE (không có UPDATE/DELETE ở service), mang
snapshot đầy đủ + kết quả theo từng target + proposal. Rule registry versioned, APPROVED bất biến, KHÔNG seed rule nào.
Không hard-delete scenario/version/run. Decision của proposal tách khỏi nội dung proposal (append-only history).
"""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow

# --- lifecycle (GPT chốt Issue #11 mục 9): forward-only; scenario và version đều DRAFT→READY→REVIEWED→APPROVED, ARCHIVED
LIFECYCLE_STATUSES = ("DRAFT", "READY", "REVIEWED", "APPROVED", "ARCHIVED")
LIFECYCLE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("READY", "ARCHIVED"),
    "READY": ("REVIEWED", "ARCHIVED"),
    "REVIEWED": ("APPROVED", "ARCHIVED"),
    "APPROVED": ("ARCHIVED",),
    "ARCHIVED": (),
}
RUNNABLE_VERSION_STATUSES = ("READY", "REVIEWED")  # không chạy trực tiếp DRAFT; khóa từ READY để reproducible

SCOPE_TYPES = ("TOTAL", "FACTORY")  # Task 5: không LINE
METRIC_CODES = ("REVENUE", "OUTPUT_QTY")
TARGET_KINDS = ("ABSOLUTE", "INCREMENT")
PERIOD_TYPES = ("MONTH", "YEAR")
# baseline_basis hợp lệ theo metric. OUTPUT_QTY chốt bảo thủ = PACK_QTY (đóng gói/FG), không gọi chung "production output".
BASELINE_BASES = {"REVENUE": ("PLAN", "ACTUAL"), "OUTPUT_QTY": ("PACK_QTY",)}
CANONICAL_UNITS = {"REVENUE": "USD", "OUTPUT_QTY": "sp"}  # hard-code vocabulary theo metric, không convert alias

RESULT_STATUSES = ("CALCULATED", "NEEDS_INPUT", "MISSING_BASELINE", "UNIT_MISMATCH", "SCOPE_MISMATCH", "PARTIAL_SOURCE")
DATA_QUALITY_FLAGS = (
    "INVALID_SOURCE_DATE", "PARTIAL_SOURCE_COVERAGE", "SOURCE_STALE_OR_LAST_SYNC_FAILED", "MISSING_BASELINE", "UNIT_MISMATCH", "SCOPE_MISMATCH",
    "SOURCE_INCONSISTENT_PERIODS",
)

PROPOSAL_TYPES = ("LABOR_RECRUITMENT", "MACHINE_PURCHASE", "TECHNOLOGY_ADOPTION", "CAPACITY_CHANGE")
RULE_PROPOSAL_TYPES = ("LABOR_RECRUITMENT", "MACHINE_PURCHASE")  # CAPACITY/TECHNOLOGY: không tính số trong Task 5
PROPOSAL_CALC_STATUSES = ("CALCULATED", "NEEDS_INPUT", "NOT_APPLICABLE")
PROPOSAL_DECISIONS = ("SELECTED", "REJECTED")
RULE_STATUSES = ("DRAFT", "APPROVED", "RETIRED")
TECH_LINK_TYPES = ("FUTURE_CANDIDATE", "PROCESS_VERSION")

# --- Task 6 (Issue #13, GPT APPROVED_TO_IMPLEMENT): executable rule — workflow + evidence source kind
EXEC_RULE_STATUSES = ("DRAFT", "UNDER_REVIEW", "APPROVED", "RETIRED")
EXEC_APPROVABLE_SOURCE_KINDS = ("IE_APPROVED_STUDY", "TIME_MOTION_STUDY", "APPROVED_CAPACITY_STUDY", "CONTROLLED_PRODUCTION_TRIAL")
EXEC_BLOCKED_SOURCE_KINDS = ("ESTIMATE", "DEFAULT", "CLAIMED", "BROCHURE", "PLACEHOLDER", "UNVERIFIED")  # chỉ lưu được ở DRAFT/UNDER_REVIEW để nghiên cứu


class RoadmapScenario(Base):
    __tablename__ = "roadmap_scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # sinh tự động, bất biến
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(String(500), default="")
    scope_type: Mapped[str] = mapped_column(String(10), default="TOTAL")
    scope_value: Mapped[str] = mapped_column(String(20), default="")  # factory code khi FACTORY, "" khi TOTAL
    owner: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(10), default="DRAFT", index=True)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str] = mapped_column(String(100), default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoadmapScenarioVersion(Base):
    __tablename__ = "roadmap_scenario_versions"
    __table_args__ = (UniqueConstraint("scenario_id", "version_no", name="uq_roadmap_version_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("roadmap_scenarios.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="DRAFT", index=True)
    scope_type: Mapped[str] = mapped_column(String(10), default="TOTAL")  # copy lúc tạo version — khóa cùng version
    scope_value: Mapped[str] = mapped_column(String(20), default="")
    note: Mapped[str] = mapped_column(String(300), default="")
    copied_from_version_id: Mapped[int | None] = mapped_column(ForeignKey("roadmap_scenario_versions.id"), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # thời điểm READY
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str] = mapped_column(String(100), default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RoadmapMilestone(Base):
    __tablename__ = "roadmap_milestones"
    __table_args__ = (UniqueConstraint("version_id", "code", name="uq_roadmap_ms_code"), UniqueConstraint("version_id", "sequence", name="uq_roadmap_ms_seq"))

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("roadmap_scenario_versions.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(150), default="")
    target_date: Mapped[date] = mapped_column(Date)
    sequence: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(300), default="")


class RoadmapTarget(Base):
    __tablename__ = "roadmap_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    milestone_id: Mapped[int] = mapped_column(ForeignKey("roadmap_milestones.id"), index=True)
    metric_code: Mapped[str] = mapped_column(String(20))
    target_kind: Mapped[str] = mapped_column(String(10), default="ABSOLUTE")
    target_value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))  # bắt buộc; khác canonical => UNIT_MISMATCH lúc run (không convert)
    scope_type: Mapped[str] = mapped_column(String(10), default="TOTAL")
    scope_value: Mapped[str] = mapped_column(String(20), default="")
    period_type: Mapped[str] = mapped_column(String(6), default="MONTH")
    period_year: Mapped[int] = mapped_column(Integer)
    period_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    baseline_basis: Mapped[str | None] = mapped_column(String(12), nullable=True)  # PLAN|ACTUAL|PACK_QTY; null => NEEDS_INPUT lúc run
    baseline_ref_year: Mapped[int | None] = mapped_column(Integer, nullable=True)  # kỳ tham chiếu tường minh; null => cùng kỳ target
    baseline_ref_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(300), default="")  # source/assumption note


class RoadmapTechnologyLink(Base):
    """Liên kết evidence Future Technology / Technology Process cho TECHNOLOGY_ADOPTION (BR-516) — chỉ link + snapshot, không sinh số."""

    __tablename__ = "roadmap_technology_links"
    __table_args__ = (UniqueConstraint("version_id", "link_type", "ref_id", name="uq_roadmap_tech_link"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("roadmap_scenario_versions.id"), index=True)
    link_type: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(300), default="")


class RoadmapRule(Base):
    """Registry rule — CHỈ METADATA (GPT review PR #12): lưu rule/evidence/version/status/approval, KHÔNG có logic thực thi số trong Task 5.
    `formula_type`/`parameters_json` chỉ là mô tả khai báo; engine Task 5 không đọc chúng để tính quantity (không có allowlist thực thi nào).
    Versioned; APPROVED bất biến; KHÔNG seed rule nào."""

    __tablename__ = "roadmap_rules"
    __table_args__ = (UniqueConstraint("rule_code", "rule_version", name="uq_roadmap_rule_version"), Index("ix_roadmap_rule_type_status", "proposal_type", "approval_status"))

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(40), index=True)
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    proposal_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200), default="")
    formula_type: Mapped[str] = mapped_column(String(40), default="UNSPECIFIED")  # explicit metadata; KHÔNG được thực thi trong Task 5
    formula_description: Mapped[str] = mapped_column(String(500), default="")  # mô tả rule bằng lời (business-owned)
    parameters_json: Mapped[dict] = mapped_column(JSON, default=dict)  # tham số khai báo (metadata), không được engine đọc để tính
    machine_type_code: Mapped[str | None] = mapped_column(ForeignKey("machine_types.code"), nullable=True)  # metadata cho MACHINE_PURCHASE
    basis_note: Mapped[str] = mapped_column(String(300), default="")  # nguồn/căn cứ (evidence) — bắt buộc để APPROVE
    approval_status: Mapped[str] = mapped_column(String(10), default="DRAFT", index=True)
    approved_by: Mapped[str] = mapped_column(String(100), default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RoadmapRun(Base):
    """IMMUTABLE — không có UPDATE/DELETE ở service."""

    __tablename__ = "roadmap_runs"
    __table_args__ = (UniqueConstraint("version_id", "run_fingerprint", name="uq_roadmap_run_fp"), UniqueConstraint("version_id", "run_no", name="uq_roadmap_run_no"))

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("roadmap_scenario_versions.id"), index=True)
    run_no: Mapped[int] = mapped_column(Integer)
    run_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="COMPLETED")
    engine_version: Mapped[str] = mapped_column(String(20), default="")
    snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)  # version/scope/milestones/targets + nguồn + refs + rules + flags
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)  # completeness + đếm trạng thái
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RoadmapRunTargetResult(Base):
    __tablename__ = "roadmap_run_target_results"
    __table_args__ = (Index("ix_roadmap_result_run", "run_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("roadmap_runs.id"))
    target_id: Mapped[int] = mapped_column(Integer)  # tham chiếu target lúc chạy (giá trị nằm trong snapshot, không phụ thuộc bảng target)
    milestone_code: Mapped[str] = mapped_column(String(40), default="")
    milestone_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    metric_code: Mapped[str] = mapped_column(String(20))
    target_kind: Mapped[str] = mapped_column(String(10))
    target_value: Mapped[float] = mapped_column(Float)
    increment_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    effective_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(20), default="")
    scope_type: Mapped[str] = mapped_column(String(10), default="")
    scope_value: Mapped[str] = mapped_column(String(20), default="")
    period_label: Mapped[str] = mapped_column(String(20), default="")
    baseline_basis: Mapped[str | None] = mapped_column(String(12), nullable=True)
    baseline_period_label: Mapped[str] = mapped_column(String(20), default="")
    output_definition: Mapped[str | None] = mapped_column(String(12), nullable=True)
    baseline_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_unit: Mapped[str] = mapped_column(String(20), default="")
    gap: Mapped[float | None] = mapped_column(Float, nullable=True)  # không clamp; âm = đã vượt
    result_status: Mapped[str] = mapped_column(String(20))
    source_identity_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_meta_json: Mapped[dict] = mapped_column(JSON, default=dict)  # latest success / last attempt / age
    data_quality_flags_json: Mapped[list] = mapped_column(JSON, default=list)
    missing_inputs_json: Mapped[list] = mapped_column(JSON, default=list)
    completeness: Mapped[str] = mapped_column(String(12), default="INCOMPLETE")


class RoadmapProposal(Base):
    """Nội dung bất biến (thuộc run). `decision_status` (SELECTED/REJECTED) là state riêng có history append-only."""

    __tablename__ = "roadmap_proposals"
    __table_args__ = (Index("ix_roadmap_proposal_run", "run_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("roadmap_runs.id"))
    target_result_id: Mapped[int | None] = mapped_column(ForeignKey("roadmap_run_target_results.id"), nullable=True)
    milestone_code: Mapped[str] = mapped_column(String(40), default="")
    proposal_type: Mapped[str] = mapped_column(String(20))
    scope_type: Mapped[str] = mapped_column(String(10), default="")
    scope_value: Mapped[str] = mapped_column(String(20), default="")
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(30), default="")
    rationale: Mapped[str] = mapped_column(String(500), default="")
    calculation_rule_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    calculation_rule_version: Mapped[str] = mapped_column(String(30), default="NONE")
    input_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    missing_inputs_json: Mapped[list] = mapped_column(JSON, default=list)
    completeness: Mapped[str] = mapped_column(String(12), default="INCOMPLETE")
    calc_status: Mapped[str] = mapped_column(String(14))  # CALCULATED | NEEDS_INPUT | NOT_APPLICABLE
    decision_status: Mapped[str | None] = mapped_column(String(10), nullable=True)  # SELECTED | REJECTED | null
    decision_reason: Mapped[str] = mapped_column(String(300), default="")
    decision_by: Mapped[str] = mapped_column(String(100), default="")
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoadmapProposalDecisionHistory(Base):
    __tablename__ = "roadmap_proposal_decisions"
    __table_args__ = (Index("ix_roadmap_pd_proposal", "proposal_id", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("roadmap_proposals.id"))
    from_status: Mapped[str | None] = mapped_column(String(14), nullable=True)
    to_status: Mapped[str] = mapped_column(String(14))
    reason: Mapped[str] = mapped_column(String(300), default="")
    actor: Mapped[str] = mapped_column(String(100), default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RoadmapStatusHistory(Base):
    """Append-only: scenario / version / rule."""

    __tablename__ = "roadmap_status_history"
    __table_args__ = (Index("ix_roadmap_sh_obj", "object_type", "object_id", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    object_type: Mapped[str] = mapped_column(String(12))  # SCENARIO | VERSION | RULE
    object_id: Mapped[int] = mapped_column(Integer)
    from_status: Mapped[str | None] = mapped_column(String(12), nullable=True)
    to_status: Mapped[str] = mapped_column(String(12))
    reason: Mapped[str] = mapped_column(String(300), default="")
    actor: Mapped[str] = mapped_column(String(100), default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RoadmapExecutableRule(Base):
    """Rule THỰC THI (Task 6). Khác `RoadmapRule` (metadata-only): mang tham số productivity do business khai báo + adapter allowlist trong code.
    Productivity KHÔNG suy từ bảng nguồn nào. Versioned; APPROVED bất biến (sửa = version mới); DRAFT→UNDER_REVIEW→APPROVED→RETIRED; four-eyes reviewer != approver.
    KHÔNG seed rule nào."""

    __tablename__ = "roadmap_executable_rules"
    __table_args__ = (UniqueConstraint("rule_code", "rule_version", name="uq_roadmap_exec_rule_version"), Index("ix_roadmap_exec_rule_type_status", "proposal_type", "status"))

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(40), index=True)
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200), default="")
    adapter_code: Mapped[str] = mapped_column(String(40))  # phải nằm trong ALLOWLISTED_ADAPTERS (code)
    adapter_version: Mapped[str] = mapped_column(String(10), default="")
    proposal_type: Mapped[str] = mapped_column(String(20))
    metadata_rule_id: Mapped[int | None] = mapped_column(ForeignKey("roadmap_rules.id"), nullable=True)  # tham chiếu tùy chọn tới rule metadata
    scope_type: Mapped[str] = mapped_column(String(10), default="TOTAL")  # exact match scope scenario; không rollup/average
    scope_value: Mapped[str] = mapped_column(String(20), default="")
    period_type: Mapped[str] = mapped_column(String(6), default="MONTH")  # phải khớp period target; không quy đổi DAY→MONTH/YEAR
    machine_type_code: Mapped[str | None] = mapped_column(ForeignKey("machine_types.code"), nullable=True)  # 1 rule = 1 machine type explicit (adapter machine)
    productivity_value: Mapped[float] = mapped_column(Float)  # business-owned, không derive từ DB
    productivity_unit: Mapped[str] = mapped_column(String(30), default="")  # sp/worker/MONTH | sp/machine/YEAR ...
    owner: Mapped[str] = mapped_column(String(100), default="")
    source_kind: Mapped[str] = mapped_column(String(30), default="")
    source_ref: Mapped[str] = mapped_column(String(300), default="")
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    assumptions: Mapped[str] = mapped_column(String(500), default="")
    sample_input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    sample_expected_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="DRAFT", index=True)
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str] = mapped_column(String(100), default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --- Task 7 (Issue #15, GPT APPROVED_TO_IMPLEMENT): Roadmap Action Plan & Milestone Coverage
ACTION_PLAN_STATUSES = ("DRAFT", "UNDER_REVIEW", "APPROVED", "ARCHIVED")
ACTION_PLAN_PERSISTENCE = ("PERSISTENT", "UNSPECIFIED", "ONE_TIME")  # ONE_TIME chỉ reserve: Task 7 không count numeric
ACTION_ITEM_STATUSES = ("COUNTED", "UNRESOLVED")
COUNTABLE_PROPOSAL_TYPES = ("LABOR_RECRUITMENT", "MACHINE_PURCHASE")  # persistence CHỐT theo type = PERSISTENT
COVERAGE_STATUSES = ("NOT_COVERED", "PARTIALLY_COVERED", "COVERED", "OVER_COVERED")


class RoadmapActionPlan(Base):
    """Family. Gắn 1 source run cố định (không rebase sang run khác — tạo family mới)."""

    __tablename__ = "roadmap_action_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    action_plan_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # sinh tự động, bất biến
    name: Mapped[str] = mapped_column(String(150), default="")
    scenario_id: Mapped[int] = mapped_column(ForeignKey("roadmap_scenarios.id"), index=True)
    scenario_version_id: Mapped[int] = mapped_column(ForeignKey("roadmap_scenario_versions.id"), index=True)
    source_run_id: Mapped[int] = mapped_column(ForeignKey("roadmap_runs.id"), index=True)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RoadmapActionPlanVersion(Base):
    __tablename__ = "roadmap_action_plan_versions"
    __table_args__ = (UniqueConstraint("plan_id", "version_no", name="uq_roadmap_ap_version_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("roadmap_action_plans.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    source_run_id: Mapped[int] = mapped_column(ForeignKey("roadmap_runs.id"))
    source_run_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(12), default="DRAFT", index=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    copied_from_version_id: Mapped[int | None] = mapped_column(ForeignKey("roadmap_action_plan_versions.id"), nullable=True)
    coverage_json: Mapped[dict] = mapped_column(JSON, default=dict)  # DRAFT: preview; đóng băng từ UNDER_REVIEW; APPROVED không recompute từ nguồn sống
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str] = mapped_column(String(100), default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archive_reason: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RoadmapActionPlanItem(Base):
    __tablename__ = "roadmap_action_plan_items"
    __table_args__ = (UniqueConstraint("plan_version_id", "proposal_id", "planned_effective_date", name="uq_roadmap_ap_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_version_id: Mapped[int] = mapped_column(ForeignKey("roadmap_action_plan_versions.id"), index=True)
    proposal_id: Mapped[int] = mapped_column(Integer)  # tham chiếu lúc chọn; giá trị nằm trong snapshot_json (không phụ thuộc proposal sống)
    proposal_type: Mapped[str] = mapped_column(String(20))
    target_result_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_milestone_code: Mapped[str] = mapped_column(String(40), default="")
    planned_effective_date: Mapped[date] = mapped_column(Date)
    selected_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_increment: Mapped[float | None] = mapped_column(Float, nullable=True)  # = selected_quantity × productivity_value (Decimal exact)
    unit: Mapped[str] = mapped_column(String(30), default="")
    impact_persistence: Mapped[str] = mapped_column(String(12), default="UNSPECIFIED")
    inclusion_status: Mapped[str] = mapped_column(String(12), default="UNRESOLVED")
    source_proposal_calc_status: Mapped[str] = mapped_column(String(14), default="")
    source_proposal_decision_snapshot: Mapped[str | None] = mapped_column(String(10), nullable=True)
    productivity_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    productivity_unit: Mapped[str] = mapped_column(String(30), default="")
    rule_effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    rule_effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_run_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(String(300), default="")
    snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
