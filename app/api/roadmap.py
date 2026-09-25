"""API Roadmap Simulation (Task 5 — Issue #11). Permission domain riêng (GPT chốt): roadmap.view / manage / run / approve.
- view: đọc; manage: CRUD scenario/version/milestone/target/link/rule(DRAFT), DRAFT→READY, READY→REVIEWED, ARCHIVED, chọn/loại proposal;
- run: chạy simulation; approve: REVIEWED→APPROVED (scenario/version) và duyệt/retire rule.
Route nested theo id (tránh lặp lỗi routing collision Task 3)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.core.permissions import ROLE_PERMISSIONS
from app.db.session import get_db
from app.models.core import User
from app.models.roadmap import (
    BASELINE_BASES,
    CANONICAL_UNITS,
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
from app.services import roadmap_baseline as rb
from app.services import roadmap_engine as eng

router = APIRouter(prefix="/roadmap", tags=["roadmap"])

View = Depends(require_perm("roadmap.view"))
Manage = Depends(require_perm("roadmap.manage"))
Run = Depends(require_perm("roadmap.run"))


def _need_approve(user: User, what: str) -> None:
    if "roadmap.approve" not in ROLE_PERMISSIONS.get(user.role, set()):
        raise HTTPException(403, f"Thiếu quyền: roadmap.approve ({what})")


@router.get("/options")
def options(_: User = View):
    return {"lifecycle_statuses": list(LIFECYCLE_STATUSES), "scope_types": list(SCOPE_TYPES), "metric_codes": list(METRIC_CODES), "target_kinds": list(TARGET_KINDS),
            "period_types": list(PERIOD_TYPES), "baseline_bases": {k: list(v) for k, v in BASELINE_BASES.items()}, "canonical_units": CANONICAL_UNITS,
            "proposal_types": list(PROPOSAL_TYPES), "rule_proposal_types": list(RULE_PROPOSAL_TYPES), "proposal_decisions": list(PROPOSAL_DECISIONS), "tech_link_types": list(TECH_LINK_TYPES)}


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
    rate_value: float | None = None
    rate_unit: str | None = Field(None, max_length=40)
    rate_period: str | None = None
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
