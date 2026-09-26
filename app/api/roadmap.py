"""API Roadmap Simulation (Task 5 — Issue #11). Permission domain riêng (GPT chốt): roadmap.view / manage / run / approve.
- view: đọc; manage: CRUD scenario/version/milestone/target/link/rule(DRAFT), DRAFT→READY, READY→REVIEWED, ARCHIVED, chọn/loại proposal;
- run: chạy simulation; approve: REVIEWED→APPROVED (scenario/version) và duyệt/retire rule.
Route nested theo id (tránh lặp lỗi routing collision Task 3)."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.core.permissions import ROLE_PERMISSIONS
from app.db.session import get_db
from app.models.core import User
from app.models.roadmap import (
    ACTION_PLAN_STATUSES,
    ASSET_KINDS,
    ASSET_SUBJECT_TYPES,
    COST_APPROVABLE_SOURCE_KINDS,
    COST_BLOCKED_SOURCE_KINDS,
    COST_FAMILIES,
    MACHINE_PRICE_BASES,
    PACKAGE_STATUSES,
    BASELINE_BASES,
    CANONICAL_UNITS,
    EXEC_APPROVABLE_SOURCE_KINDS,
    EXEC_BLOCKED_SOURCE_KINDS,
    EXEC_RULE_STATUSES,
    LIFECYCLE_STATUSES,
    METRIC_CODES,
    PERIOD_TYPES,
    PROPOSAL_DECISIONS,
    PROPOSAL_TYPES,
    RULE_PROPOSAL_TYPES,
    SCOPE_TYPES,
    TARGET_KINDS,
    TECH_LINK_TYPES,
)
from app.services import roadmap as rm
from app.services import roadmap_action_plan as ap
from app.services import roadmap_adapters as ad
from app.services import roadmap_cost as rc
from app.services import roadmap_decision_package as dp
from app.services import roadmap_health as hl
from app.services import roadmap_exec_rules as xr
from app.services import roadmap_baseline as rb
from app.services import roadmap_engine as eng

router = APIRouter(prefix="/roadmap", tags=["roadmap"])
log = logging.getLogger("dvt.roadmap")

View = Depends(require_perm("roadmap.view"))
Manage = Depends(require_perm("roadmap.manage"))
Run = Depends(require_perm("roadmap.run"))


def _need_approve(user: User, what: str) -> None:
    if "roadmap.approve" not in ROLE_PERMISSIONS.get(user.role, set()):
        log.warning("ROADMAP_PERMISSION_DENIED user=%s role=%s need=roadmap.approve action=%s", user.username, user.role, what)
        raise HTTPException(403, f"Thiếu quyền: roadmap.approve ({what})")


@router.get("/options")
def options(_: User = View):
    return {"lifecycle_statuses": list(LIFECYCLE_STATUSES), "scope_types": list(SCOPE_TYPES), "metric_codes": list(METRIC_CODES), "target_kinds": list(TARGET_KINDS),
            "period_types": list(PERIOD_TYPES), "baseline_bases": {k: list(v) for k, v in BASELINE_BASES.items()}, "canonical_units": CANONICAL_UNITS,
            "proposal_types": list(PROPOSAL_TYPES), "rule_proposal_types": list(RULE_PROPOSAL_TYPES), "proposal_decisions": list(PROPOSAL_DECISIONS), "tech_link_types": list(TECH_LINK_TYPES),
            "exec_rule_statuses": list(EXEC_RULE_STATUSES), "exec_approvable_source_kinds": list(EXEC_APPROVABLE_SOURCE_KINDS),
            "exec_blocked_source_kinds": list(EXEC_BLOCKED_SOURCE_KINDS), "action_plan_statuses": list(ACTION_PLAN_STATUSES), "cost_families": list(COST_FAMILIES),
            "cost_approvable_source_kinds": {k: list(v) for k, v in COST_APPROVABLE_SOURCE_KINDS.items()}, "cost_blocked_source_kinds": list(COST_BLOCKED_SOURCE_KINDS),
            "machine_price_bases": list(MACHINE_PRICE_BASES), "package_statuses": list(PACKAGE_STATUSES), "asset_kinds": list(ASSET_KINDS), "asset_subject_types": list(ASSET_SUBJECT_TYPES), "adapters": [a.contract() for a in ad.ADAPTERS.values()]}


# ------------------------------------------------------------------ scenario
class ScenarioBody(BaseModel):
    name: str | None = Field(None, max_length=150)
    description: str | None = Field(None, max_length=500)
    scope_type: str | None = None
    scope_value: str | None = Field(None, max_length=20)
    owner: str | None = Field(None, max_length=100)


class TransitionBody(BaseModel):
    to_status: str
    reason: str = Field("", max_length=300)


@router.get("/scenarios")
def list_scenarios(status: str = "", db: Session = Depends(get_db), _: User = View):
    return [rm.scenario_view(s) for s in rm.list_scenarios(db, status)]


@router.post("/scenarios")
def create_scenario(body: ScenarioBody, db: Session = Depends(get_db), user: User = Manage):
    return rm.scenario_view(rm.create_scenario(db, user, body.model_dump(exclude_unset=True)))


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: int, db: Session = Depends(get_db), _: User = View):
    s = rm.get_scenario(db, scenario_id)
    return {**rm.scenario_view(s, rm.scenario_versions(db, s.id)), "history": rm.list_history(db, "SCENARIO", s.id)}


@router.put("/scenarios/{scenario_id}")
def update_scenario(scenario_id: int, body: ScenarioBody, db: Session = Depends(get_db), user: User = Manage):
    return rm.scenario_view(rm.update_scenario(db, user, scenario_id, body.model_dump(exclude_unset=True)))


@router.post("/scenarios/{scenario_id}/transition")
def transition_scenario(scenario_id: int, body: TransitionBody, db: Session = Depends(get_db), user: User = Manage):
    if rm.requires_approve("", body.to_status):
        _need_approve(user, "REVIEWED→APPROVED")
    return rm.scenario_view(rm.transition_scenario(db, user, scenario_id, body.to_status, body.reason))


class NewVersionBody(BaseModel):
    copy_from_version_id: int | None = None
    note: str = Field("", max_length=300)


@router.post("/scenarios/{scenario_id}/versions")
def create_version(scenario_id: int, body: NewVersionBody, db: Session = Depends(get_db), user: User = Manage):
    return rm.version_view(db, rm.create_version(db, user, scenario_id, body.copy_from_version_id, body.note))


# ------------------------------------------------------------------ version / milestone / target / links
@router.get("/versions/{version_id}")
def get_version(version_id: int, db: Session = Depends(get_db), _: User = View):
    v = rm.get_version(db, version_id)
    return {**rm.version_view(db, v), "history": rm.list_history(db, "VERSION", v.id)}


@router.post("/versions/{version_id}/transition")
def transition_version(version_id: int, body: TransitionBody, db: Session = Depends(get_db), user: User = Manage):
    if rm.requires_approve("", body.to_status):
        _need_approve(user, "REVIEWED→APPROVED")
    return rm.version_view(db, rm.transition_version(db, user, version_id, body.to_status, body.reason))


class MilestoneBody(BaseModel):
    code: str | None = Field(None, max_length=40)
    name: str | None = Field(None, max_length=150)
    target_date: str | None = None
    sequence: int | None = None
    note: str | None = Field(None, max_length=300)


@router.post("/versions/{version_id}/milestones")
def add_milestone(version_id: int, body: MilestoneBody, db: Session = Depends(get_db), user: User = Manage):
    m = rm.add_milestone(db, user, version_id, body.model_dump(exclude_unset=True))
    return {"id": m.id, "code": m.code, "sequence": m.sequence, "target_date": m.target_date.isoformat()}


@router.put("/milestones/{milestone_id}")
def update_milestone(milestone_id: int, body: MilestoneBody, db: Session = Depends(get_db), user: User = Manage):
    m = rm.update_milestone(db, user, milestone_id, body.model_dump(exclude_unset=True))
    return {"id": m.id, "code": m.code, "sequence": m.sequence, "target_date": m.target_date.isoformat()}


@router.delete("/milestones/{milestone_id}")
def remove_milestone(milestone_id: int, db: Session = Depends(get_db), user: User = Manage):
    rm.remove_milestone(db, user, milestone_id)
    return {"ok": True}


class TargetBody(BaseModel):
    metric_code: str | None = None
    target_kind: str | None = None
    target_value: float | None = None
    unit: str | None = Field(None, max_length=20)
    scope_type: str | None = None
    scope_value: str | None = Field(None, max_length=20)
    period_type: str | None = None
    period_year: int | None = None
    period_month: int | None = None
    baseline_basis: str | None = None
    baseline_ref_year: int | None = None
    baseline_ref_month: int | None = None
    note: str | None = Field(None, max_length=300)


@router.post("/milestones/{milestone_id}/targets")
def add_target(milestone_id: int, body: TargetBody, db: Session = Depends(get_db), user: User = Manage):
    return rm.target_view(rm.add_target(db, user, milestone_id, body.model_dump(exclude_unset=True)))


@router.put("/targets/{target_id}")
def update_target(target_id: int, body: TargetBody, db: Session = Depends(get_db), user: User = Manage):
    return rm.target_view(rm.update_target(db, user, target_id, body.model_dump(exclude_unset=True)))


@router.delete("/targets/{target_id}")
def remove_target(target_id: int, db: Session = Depends(get_db), user: User = Manage):
    rm.remove_target(db, user, target_id)
    return {"ok": True}


class LinkBody(BaseModel):
    link_type: str
    ref_id: int
    note: str = Field("", max_length=300)


@router.post("/versions/{version_id}/technology-links")
def add_link(version_id: int, body: LinkBody, db: Session = Depends(get_db), user: User = Manage):
    k = rm.add_link(db, user, version_id, body.link_type, body.ref_id, body.note)
    return {"id": k.id, "link_type": k.link_type, "ref_id": k.ref_id}


@router.delete("/technology-links/{link_id}")
def remove_link(link_id: int, db: Session = Depends(get_db), user: User = Manage):
    rm.remove_link(db, user, link_id)
    return {"ok": True}


@router.get("/baseline-preview")
def baseline_preview(metric_code: str, baseline_basis: str, period_type: str, year: int, month: int | None = None, scope_type: str = "TOTAL", scope_value: str = "",
                     db: Session = Depends(get_db), _: User = View):
    """Xem baseline hiện có (chỉ đọc) trước khi chốt target — không ghi gì, không tạo Run."""
    if metric_code not in METRIC_CODES or baseline_basis not in BASELINE_BASES[metric_code] or period_type not in PERIOD_TYPES:
        raise HTTPException(422, "metric_code / baseline_basis / period_type không hợp lệ")
    if period_type == "MONTH" and not (month and 1 <= month <= 12):
        raise HTTPException(422, "period_type MONTH cần month 1..12")
    st, sv = rm._validate_scope(db, scope_type, scope_value)
    return rb.baseline_for(db, metric_code, baseline_basis, period_type, year, month if period_type == "MONTH" else None, st, sv)


# ------------------------------------------------------------------ run / proposals
@router.post("/versions/{version_id}/runs")
def run_simulation(version_id: int, db: Session = Depends(get_db), user: User = Run):
    return eng.run_simulation(db, user, version_id)


@router.get("/versions/{version_id}/runs")
def list_runs(version_id: int, db: Session = Depends(get_db), _: User = View):
    return [eng.run_view(db, r, detail=False) for r in eng.list_runs(db, version_id)]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), _: User = View):
    return eng.run_view(db, eng.get_run(db, run_id))


@router.get("/runs/{run_id}/compare-with/{other_run_id}")
def compare_runs(run_id: int, other_run_id: int, db: Session = Depends(get_db), _: User = View):
    return eng.compare_runs(db, run_id, other_run_id)


class DecisionBody(BaseModel):
    decision: str
    reason: str = Field("", max_length=300)


@router.post("/proposals/{proposal_id}/decision")
def decide(proposal_id: int, body: DecisionBody, db: Session = Depends(get_db), user: User = Manage):
    return eng.proposal_view(eng.decide_proposal(db, user, proposal_id, body.decision, body.reason))


@router.get("/proposals/{proposal_id}/history")
def proposal_history(proposal_id: int, db: Session = Depends(get_db), _: User = View):
    return eng.proposal_history(db, proposal_id)


# ------------------------------------------------------------------ rule registry
class RuleBody(BaseModel):
    rule_code: str | None = Field(None, max_length=40)
    proposal_type: str | None = None
    title: str | None = Field(None, max_length=200)
    formula_type: str | None = Field(None, max_length=40)
    formula_description: str | None = Field(None, max_length=500)
    parameters: dict | None = None
    machine_type_code: str | None = Field(None, max_length=20)
    basis_note: str | None = Field(None, max_length=300)


@router.get("/rules")
def list_rules(proposal_type: str = "", approval_status: str = "", db: Session = Depends(get_db), _: User = View):
    return [rm.rule_view(r) for r in rm.list_rules(db, proposal_type, approval_status)]


@router.post("/rules")
def create_rule(body: RuleBody, db: Session = Depends(get_db), user: User = Manage):
    return rm.rule_view(rm.create_rule(db, user, body.model_dump(exclude_unset=True)))


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleBody, db: Session = Depends(get_db), user: User = Manage):
    return rm.rule_view(rm.update_rule(db, user, rule_id, body.model_dump(exclude_unset=True)))


@router.post("/rules/{rule_id}/new-version")
def new_rule_version(rule_id: int, db: Session = Depends(get_db), user: User = Manage):
    return rm.rule_view(rm.new_rule_version(db, user, rule_id))


@router.post("/rules/{rule_id}/approve")
def approve_rule(rule_id: int, db: Session = Depends(get_db), user: User = Manage):
    _need_approve(user, "duyệt rule")
    return rm.rule_view(rm.approve_rule(db, user, rule_id))


class RetireBody(BaseModel):
    reason: str = Field("", max_length=300)


@router.post("/rules/{rule_id}/retire")
def retire_rule(rule_id: int, body: RetireBody, db: Session = Depends(get_db), user: User = Manage):
    _need_approve(user, "retire rule")
    return rm.rule_view(rm.retire_rule(db, user, rule_id, body.reason))


# ------------------------------------------------------------------ executable rules (Task 6)
class ExecRuleBody(BaseModel):
    rule_code: str | None = Field(None, max_length=40)
    title: str | None = Field(None, max_length=200)
    adapter_code: str | None = Field(None, max_length=40)
    metadata_rule_id: int | None = None
    scope_type: str | None = None
    scope_value: str | None = Field(None, max_length=20)
    period_type: str | None = None
    machine_type_code: str | None = Field(None, max_length=20)
    productivity_value: float | None = None
    productivity_unit: str | None = Field(None, max_length=30)
    owner: str | None = Field(None, max_length=100)
    source_kind: str | None = Field(None, max_length=30)
    source_ref: str | None = Field(None, max_length=300)
    effective_from: str | None = None
    effective_to: str | None = None
    assumptions: str | None = Field(None, max_length=500)
    sample_input: dict | None = None
    sample_expected: dict | None = None


@router.get("/executable-rules")
def list_exec_rules(proposal_type: str = "", status: str = "", db: Session = Depends(get_db), _: User = View):
    return [xr.rule_view(r) for r in xr.list_rules(db, proposal_type, status)]


@router.post("/executable-rules")
def create_exec_rule(body: ExecRuleBody, db: Session = Depends(get_db), user: User = Manage):
    return xr.rule_view(xr.create_rule(db, user, body.model_dump(exclude_unset=True)))


@router.get("/executable-rules/{rule_id}")
def get_exec_rule(rule_id: int, db: Session = Depends(get_db), _: User = View):
    return xr.rule_view(xr.get_rule(db, rule_id))


@router.put("/executable-rules/{rule_id}")
def update_exec_rule(rule_id: int, body: ExecRuleBody, db: Session = Depends(get_db), user: User = Manage):
    return xr.rule_view(xr.update_rule(db, user, rule_id, body.model_dump(exclude_unset=True)))


@router.post("/executable-rules/{rule_id}/new-version")
def new_exec_rule_version(rule_id: int, db: Session = Depends(get_db), user: User = Manage):
    return xr.rule_view(xr.new_version(db, user, rule_id))


@router.post("/executable-rules/{rule_id}/submit-review")
def submit_exec_rule_review(rule_id: int, db: Session = Depends(get_db), user: User = Manage):
    return xr.rule_view(xr.submit_review(db, user, rule_id))


@router.post("/executable-rules/{rule_id}/verify-sample")
def verify_exec_rule_sample(rule_id: int, db: Session = Depends(get_db), _: User = View):
    return xr.verify_sample(xr.get_rule(db, rule_id))


@router.post("/executable-rules/{rule_id}/approve")
def approve_exec_rule(rule_id: int, db: Session = Depends(get_db), user: User = Manage):
    _need_approve(user, "duyệt executable rule")
    return xr.rule_view(xr.approve_rule(db, user, rule_id))


@router.post("/executable-rules/{rule_id}/retire")
def retire_exec_rule(rule_id: int, body: RetireBody, db: Session = Depends(get_db), user: User = Manage):
    _need_approve(user, "retire executable rule")
    return xr.rule_view(xr.retire_rule(db, user, rule_id, body.reason))


@router.get("/executable-rules/{rule_id}/history")
def exec_rule_history(rule_id: int, db: Session = Depends(get_db), _: User = View):
    xr.get_rule(db, rule_id)
    return rm.list_history(db, "EXEC_RULE", rule_id)


# ------------------------------------------------------------------ action plan (Task 7)
class ActionPlanBody(BaseModel):
    name: str | None = Field(None, max_length=150)
    note: str | None = Field(None, max_length=300)


class ActionItemBody(BaseModel):
    proposal_id: int | None = None
    planned_effective_date: str | None = None
    selected_quantity: int | None = None
    as_unresolved: bool | None = None
    notes: str | None = Field(None, max_length=300)


@router.get("/action-plans")
def list_action_plans(scenario_version_id: int | None = None, source_run_id: int | None = None, db: Session = Depends(get_db), _: User = View):
    return [ap.plan_view(db, p) for p in ap.list_plans(db, scenario_version_id, source_run_id)]


@router.post("/runs/{run_id}/action-plans")
def create_action_plan(run_id: int, body: ActionPlanBody, db: Session = Depends(get_db), user: User = Manage):
    return ap.version_view(db, ap.create_plan(db, user, run_id, body.model_dump(exclude_unset=True)))


@router.get("/action-plans/{plan_id}")
def get_action_plan(plan_id: int, db: Session = Depends(get_db), _: User = View):
    return ap.plan_view(db, ap.get_plan(db, plan_id))


@router.get("/action-plan-versions/{version_id}")
def get_action_plan_version(version_id: int, db: Session = Depends(get_db), _: User = View):
    return ap.version_view(db, ap.get_version(db, version_id))


@router.post("/action-plan-versions/{version_id}/items")
def add_action_item(version_id: int, body: ActionItemBody, db: Session = Depends(get_db), user: User = Manage):
    return ap.item_view(db, ap.add_item(db, user, version_id, body.model_dump(exclude_unset=True)))


@router.put("/action-plan-items/{item_id}")
def update_action_item(item_id: int, body: ActionItemBody, db: Session = Depends(get_db), user: User = Manage):
    return ap.item_view(db, ap.update_item(db, user, item_id, body.model_dump(exclude_unset=True)))


@router.delete("/action-plan-items/{item_id}")
def remove_action_item(item_id: int, db: Session = Depends(get_db), user: User = Manage):
    ap.remove_item(db, user, item_id)
    return {"ok": True}


@router.post("/action-plan-versions/{version_id}/submit-review")
def submit_action_plan_review(version_id: int, db: Session = Depends(get_db), user: User = Manage):
    return ap.version_view(db, ap.submit_review(db, user, version_id))


@router.post("/action-plan-versions/{version_id}/approve")
def approve_action_plan(version_id: int, db: Session = Depends(get_db), user: User = Manage):
    _need_approve(user, "duyệt Action Plan")
    return ap.version_view(db, ap.approve(db, user, version_id))


@router.post("/action-plan-versions/{version_id}/archive")
def archive_action_plan(version_id: int, body: RetireBody, db: Session = Depends(get_db), user: User = Manage):
    _need_approve(user, "archive Action Plan")
    return ap.version_view(db, ap.archive(db, user, version_id, body.reason))


@router.post("/action-plan-versions/{version_id}/new-version")
def new_action_plan_version(version_id: int, db: Session = Depends(get_db), user: User = Manage):
    return ap.version_view(db, ap.new_version(db, user, version_id))


@router.get("/action-plan-versions/{version_id}/history")
def action_plan_history(version_id: int, db: Session = Depends(get_db), _: User = View):
    return ap.version_history(db, version_id)


@router.get("/action-plan-compare/{a_id}/{b_id}")
def compare_action_plans(a_id: int, b_id: int, db: Session = Depends(get_db), _: User = View):
    return ap.compare(db, a_id, b_id)


# ------------------------------------------------------------------ cost evidence / asset refs / decision package (Task 8)
class CostEvidenceBody(BaseModel):
    evidence_code: str | None = Field(None, max_length=40)
    cost_family: str | None = None
    machine_type_code: str | None = Field(None, max_length=20)
    machine_model_id: int | None = None
    future_candidate_id: int | None = None
    scope_type: str | None = None
    scope_value: str | None = Field(None, max_length=20)
    cost_period: str | None = None
    amount: str | float | int | None = None
    currency: str | None = Field(None, max_length=3)
    price_basis: str | None = Field(None, max_length=40)
    vendor: str | None = Field(None, max_length=150)
    source_kind: str | None = Field(None, max_length=30)
    source_ref: str | None = Field(None, max_length=300)
    evidence_date: str | None = None
    quote_valid_until: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    note: str | None = Field(None, max_length=300)


@router.get("/cost-evidence")
def list_cost_evidence(cost_family: str = "", status: str = "", db: Session = Depends(get_db), _: User = View):
    return [rc.evidence_view(e) for e in rc.list_evidence(db, cost_family, status)]


@router.post("/cost-evidence")
def create_cost_evidence(body: CostEvidenceBody, db: Session = Depends(get_db), user: User = Manage):
    return rc.evidence_view(rc.create_evidence(db, user, body.model_dump(exclude_unset=True)))


@router.get("/cost-evidence/{evidence_id}")
def get_cost_evidence(evidence_id: int, db: Session = Depends(get_db), _: User = View):
    return rc.evidence_view(rc.get_evidence(db, evidence_id))


@router.put("/cost-evidence/{evidence_id}")
def update_cost_evidence(evidence_id: int, body: CostEvidenceBody, db: Session = Depends(get_db), user: User = Manage):
    return rc.evidence_view(rc.update_evidence(db, user, evidence_id, body.model_dump(exclude_unset=True)))


@router.post("/cost-evidence/{evidence_id}/new-version")
def new_cost_evidence_version(evidence_id: int, db: Session = Depends(get_db), user: User = Manage):
    return rc.evidence_view(rc.new_version(db, user, evidence_id))


@router.post("/cost-evidence/{evidence_id}/submit-review")
def submit_cost_evidence_review(evidence_id: int, db: Session = Depends(get_db), user: User = Manage):
    return rc.evidence_view(rc.submit_review(db, user, evidence_id))


@router.post("/cost-evidence/{evidence_id}/approve")
def approve_cost_evidence(evidence_id: int, db: Session = Depends(get_db), user: User = Manage):
    _need_approve(user, "duyệt cost evidence")
    return rc.evidence_view(rc.approve_evidence(db, user, evidence_id))


@router.post("/cost-evidence/{evidence_id}/retire")
def retire_cost_evidence(evidence_id: int, body: RetireBody, db: Session = Depends(get_db), user: User = Manage):
    _need_approve(user, "retire cost evidence")
    return rc.evidence_view(rc.retire_evidence(db, user, evidence_id, body.reason))


@router.get("/cost-evidence/{evidence_id}/history")
def cost_evidence_history(evidence_id: int, db: Session = Depends(get_db), _: User = View):
    rc.get_evidence(db, evidence_id)
    return rm.list_history(db, "COST_EVID", evidence_id)


class AssetRefBody(BaseModel):
    subject_type: str | None = None
    subject_ref: str | None = Field(None, max_length=30)
    asset_kind: str | None = None
    uri: str | None = Field(None, max_length=500)
    asset_ref: str | None = Field(None, max_length=200)
    source_ref: str | None = Field(None, max_length=300)
    note: str | None = Field(None, max_length=300)


class ActiveBody(BaseModel):
    active: bool


@router.get("/asset-refs")
def list_asset_refs(subject_type: str = "", subject_ref: str = "", db: Session = Depends(get_db), _: User = View):
    return [rc.asset_view(a) for a in rc.list_assets(db, subject_type, subject_ref)]


@router.post("/asset-refs")
def create_asset_ref(body: AssetRefBody, db: Session = Depends(get_db), user: User = Manage):
    return rc.asset_view(rc.create_asset(db, user, body.model_dump(exclude_unset=True)))


@router.post("/asset-refs/{asset_id}/active")
def set_asset_ref_active(asset_id: int, body: ActiveBody, db: Session = Depends(get_db), user: User = Manage):
    return rc.asset_view(rc.set_asset_active(db, user, asset_id, body.active))


class PackageBody(BaseModel):
    note: str | None = Field(None, max_length=300)


class BindingBody(BaseModel):
    action_item_id: int
    evidence_id: int
    machine_model_id: int | None = None
    future_candidate_id: int | None = None


@router.get("/decision-packages")
def list_decision_packages(action_plan_version_id: int | None = None, db: Session = Depends(get_db), _: User = View):
    return [dp.package_view(db, p, detail=False) for p in dp.list_packages(db, action_plan_version_id)]


@router.post("/action-plan-versions/{version_id}/decision-packages")
def create_decision_package(version_id: int, body: PackageBody, db: Session = Depends(get_db), user: User = Manage):
    return dp.package_view(db, dp.create_package(db, user, version_id, body.model_dump(exclude_unset=True)))


@router.get("/decision-packages/{package_id}")
def get_decision_package(package_id: int, db: Session = Depends(get_db), _: User = View):
    return dp.package_view(db, dp.get_package(db, package_id))


@router.post("/decision-packages/{package_id}/bindings")
def bind_package_evidence(package_id: int, body: BindingBody, db: Session = Depends(get_db), user: User = Manage):
    dp.bind(db, user, package_id, body.model_dump(exclude_unset=True))
    return dp.package_view(db, dp.get_package(db, package_id))


@router.delete("/decision-packages/{package_id}/bindings/{action_item_id}")
def unbind_package_evidence(package_id: int, action_item_id: int, db: Session = Depends(get_db), user: User = Manage):
    dp.unbind(db, user, package_id, action_item_id)
    return dp.package_view(db, dp.get_package(db, package_id))


@router.post("/decision-packages/{package_id}/submit-review")
def submit_decision_package_review(package_id: int, db: Session = Depends(get_db), user: User = Manage):
    return dp.package_view(db, dp.submit_review(db, user, package_id))


@router.post("/decision-packages/{package_id}/approve")
def approve_decision_package(package_id: int, db: Session = Depends(get_db), user: User = Manage):
    _need_approve(user, "duyệt Decision Package")
    return dp.package_view(db, dp.approve(db, user, package_id))


@router.post("/decision-packages/{package_id}/archive")
def archive_decision_package(package_id: int, body: RetireBody, db: Session = Depends(get_db), user: User = Manage):
    _need_approve(user, "archive Decision Package")
    return dp.package_view(db, dp.archive(db, user, package_id, body.reason))


@router.get("/decision-packages/{package_id}/history")
def decision_package_history(package_id: int, db: Session = Depends(get_db), _: User = View):
    return dp.history(db, package_id)


@router.get("/decision-package-compare/{a_id}/{b_id}")
def compare_decision_packages(a_id: int, b_id: int, db: Session = Depends(get_db), _: User = View):
    return dp.compare(db, a_id, b_id)


# ------------------------------------------------------------------ Source Data Health + Production Readiness (Task 10 — chỉ đọc)
@router.get("/source-health")
def source_health(year: int | None = None, month: int | None = None, db: Session = Depends(get_db), _: User = View):
    if (year is None) != (month is None) or (month is not None and not 1 <= month <= 12) or (year is not None and not 2000 <= year <= 2100):
        raise HTTPException(422, "year/month phải đi cùng nhau: year 2000..2100, month 1..12")
    return hl.source_health(db, year, month)


@router.get("/readiness")
def production_readiness(db: Session = Depends(get_db), _: User = View):
    return hl.production_readiness(db)
