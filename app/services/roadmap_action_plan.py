"""Roadmap Action Plan & Milestone Coverage (Task 7 — Issue #15, GPT APPROVED_TO_IMPLEMENT WITH ACTION-PLAN CONTRACT).

Action Plan tách khỏi Run immutable: family (1 source run cố định) → version (DRAFT→UNDER_REVIEW→APPROVED→ARCHIVED, four-eyes) → item (selection thủ công).
- KHÔNG auto-select / optimizer / rank / ROI / thực thi mua-tuyển. KHÔNG dựa vào `decision_status` sống của proposal để tái tạo plan (chỉ guard REJECTED lúc thêm item, rồi snapshot).
- COUNTED item: chỉ LABOR_RECRUITMENT / MACHINE_PURCHASE ở proposal CALCULATED có productivity lineage; `planned_increment = selected_quantity × productivity_value` (Decimal exact,
  1..proposal.quantity, productivity từ SNAPSHOT proposal, không đọc live rule). Persistence CHỐT theo type = PERSISTENT; ONE_TIME chỉ reserve (không count).
  Mọi loại khác (NEEDS_INPUT/TECH/CAPACITY/không có lineage) chỉ là UNRESOLVED full-line, không coverage. NOT_APPLICABLE bị chặn.
- Coverage (OUTPUT_QTY, CALCULATED, gap>0): tách theo proposal_type — KHÔNG cộng chéo LABOR+MACHINE (mixed => NOT_COMBINABLE). Chỉ tính từ snapshot (run immutable + item snapshot).
- Chặn >1 COUNTED proposal cùng (target_result_id, proposal_type) — là phương án thay thế; UNRESOLVED khác proposal cùng key không được dùng để bypass.
- APPROVED immutable (sửa = version mới, giữ nguyên source run); coverage đóng băng từ UNDER_REVIEW và được verify lại trước APPROVED.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import User
from app.models.roadmap import (
    COUNTABLE_PROPOSAL_TYPES,
    RoadmapActionPlan,
    RoadmapActionPlanItem,
    RoadmapActionPlanVersion,
    RoadmapProposal,
    RoadmapRun,
    RoadmapRunTargetResult,
    RoadmapScenario,
    RoadmapScenarioVersion,
)
from app.services import roadmap as rm
from app.services import roadmap_engine as eng
from app.services.audit import write_audit

_bad = rm._bad
_iso = rm._iso
COVERAGE_ENGINE = "AP_COVERAGE_V1"


def _dec(v) -> Decimal:
    return Decimal(str(v))


def _f(d: Decimal) -> float:
    return float(round(d, 6))


# ------------------------------------------------------------------ getters / views
def get_plan(db: Session, plan_id: int) -> RoadmapActionPlan:
    p = db.get(RoadmapActionPlan, plan_id)
    if p is None:
        raise HTTPException(404, "Không tìm thấy Action Plan")
    return p


def get_version(db: Session, version_id: int) -> RoadmapActionPlanVersion:
    v = db.get(RoadmapActionPlanVersion, version_id)
    if v is None:
        raise HTTPException(404, "Không tìm thấy Action Plan version")
    return v


def get_item(db: Session, item_id: int) -> RoadmapActionPlanItem:
    i = db.get(RoadmapActionPlanItem, item_id)
    if i is None:
        raise HTTPException(404, "Không tìm thấy Action Plan item")
    return i


def version_items(db: Session, version_id: int) -> list[RoadmapActionPlanItem]:
    return db.query(RoadmapActionPlanItem).filter_by(plan_version_id=version_id).order_by(RoadmapActionPlanItem.id).all()


def item_view(db: Session, i: RoadmapActionPlanItem) -> dict:
    live = db.get(RoadmapProposal, i.proposal_id)
    return {
        "id": i.id, "plan_version_id": i.plan_version_id, "proposal_id": i.proposal_id, "proposal_type": i.proposal_type, "target_result_id": i.target_result_id,
        "source_milestone_code": i.source_milestone_code, "planned_effective_date": _iso(i.planned_effective_date), "selected_quantity": i.selected_quantity,
        "planned_increment": i.planned_increment, "unit": i.unit, "impact_persistence": i.impact_persistence, "inclusion_status": i.inclusion_status,
        "source_proposal_calc_status": i.source_proposal_calc_status, "source_proposal_decision_snapshot": i.source_proposal_decision_snapshot,
        "productivity_value": i.productivity_value, "productivity_unit": i.productivity_unit, "rule_effective_from": _iso(i.rule_effective_from),
        "rule_effective_to": _iso(i.rule_effective_to), "source_run_fingerprint": i.source_run_fingerprint, "notes": i.notes, "snapshot": i.snapshot_json,
        "current_proposal_decision_changed": bool(live is not None and live.decision_status != i.source_proposal_decision_snapshot),  # chỉ cảnh báo; coverage dùng snapshot
    }


def version_view(db: Session, v: RoadmapActionPlanVersion, detail: bool = True) -> dict:
    plan = get_plan(db, v.plan_id)
    out = {
        "id": v.id, "plan_id": v.plan_id, "action_plan_code": plan.action_plan_code, "name": plan.name, "version_no": v.version_no, "status": v.status, "note": v.note,
        "scenario_id": plan.scenario_id, "scenario_version_id": plan.scenario_version_id, "source_run_id": v.source_run_id, "source_run_fingerprint": v.source_run_fingerprint,
        "copied_from_version_id": v.copied_from_version_id, "reviewed_by": v.reviewed_by, "reviewed_at": _iso(v.reviewed_at), "approved_by": v.approved_by,
        "approved_at": _iso(v.approved_at), "archive_reason": v.archive_reason, "created_by": v.created_by, "created_at": _iso(v.created_at), "editable": v.status == "DRAFT",
        "coverage_frozen": v.status != "DRAFT",
    }
    if detail:
        out["items"] = [item_view(db, i) for i in version_items(db, v.id)]
        out["coverage"] = v.coverage_json or {}
    return out


def plan_view(db: Session, p: RoadmapActionPlan) -> dict:
    vs = db.query(RoadmapActionPlanVersion).filter_by(plan_id=p.id).order_by(RoadmapActionPlanVersion.version_no).all()
    return {"id": p.id, "action_plan_code": p.action_plan_code, "name": p.name, "scenario_id": p.scenario_id, "scenario_version_id": p.scenario_version_id, "source_run_id": p.source_run_id,
            "created_by": p.created_by, "created_at": _iso(p.created_at), "versions": [version_view(db, v, detail=False) for v in vs]}


def list_plans(db: Session, scenario_version_id: int | None = None, source_run_id: int | None = None) -> list[RoadmapActionPlan]:
    q = db.query(RoadmapActionPlan)
    if scenario_version_id:
        q = q.filter(RoadmapActionPlan.scenario_version_id == scenario_version_id)
    if source_run_id:
        q = q.filter(RoadmapActionPlan.source_run_id == source_run_id)
    return q.order_by(RoadmapActionPlan.id.desc()).all()


def version_history(db: Session, version_id: int) -> list[dict]:
    get_version(db, version_id)
    return rm.list_history(db, "ACTION_PLAN", version_id)


# ------------------------------------------------------------------ coverage (chỉ từ snapshot)
def _period_type_of(label: str) -> str:
    return "MONTH" if "-" in (label or "") else "YEAR"


def compute_coverage(db: Session, v: RoadmapActionPlanVersion) -> dict:
    items = version_items(db, v.id)
    counted = [i for i in items if i.inclusion_status == "COUNTED" and i.impact_persistence == "PERSISTENT" and i.planned_increment is not None]
    unresolved = [i for i in items if i.inclusion_status != "COUNTED"]
    results = (db.query(RoadmapRunTargetResult).filter_by(run_id=v.source_run_id, metric_code="OUTPUT_QTY", result_status="CALCULATED").order_by(RoadmapRunTargetResult.id).all())
    targets = []
    for r in results:
        if r.gap is None or r.gap <= 0:
            continue  # không tạo NO_GAP: gap<=0 bỏ khỏi numeric coverage
        gap, ptype = _dec(r.gap), _period_type_of(r.period_label)
        by_type: dict[str, dict] = {}
        for i in counted:
            lin = (i.snapshot_json or {}).get("lineage", {})
            if not (i.planned_effective_date <= r.milestone_date and (lin.get("scope_type"), lin.get("scope_value")) == (r.scope_type, r.scope_value)
                    and lin.get("capacity_unit") == "sp" and r.unit == "sp" and lin.get("period_type") == ptype):
                continue
            e = by_type.setdefault(i.proposal_type, {"inc": Decimal(0), "item_ids": []})
            e["inc"] += _dec(i.planned_increment)
            e["item_ids"].append(i.id)
        cov = {}
        for t in sorted(by_type):
            inc = by_type[t]["inc"]
            status = "NOT_COVERED" if inc == 0 else ("PARTIALLY_COVERED" if inc < gap else ("COVERED" if inc == gap else "OVER_COVERED"))
            cov[t] = {"planned_increment": _f(inc), "remaining_gap": _f(gap - inc), "status": status, "item_ids": by_type[t]["item_ids"]}
        types = sorted(cov)
        mixed = len(types) > 1
        row = {"target_result_id": r.id, "milestone_code": r.milestone_code, "milestone_date": _iso(r.milestone_date), "metric_code": r.metric_code, "period_label": r.period_label,
               "period_type": ptype, "scope_type": r.scope_type, "scope_value": r.scope_value, "unit": r.unit, "baseline_value": r.baseline_value, "effective_target": r.effective_target,
               "original_gap": r.gap, "coverage_by_proposal_type": cov, "counted_resource_types": types, "mixed_resource_types": mixed,
               "has_unresolved_actions": any(i.target_result_id == r.id for i in unresolved)}
        if mixed:  # KHÔNG cộng chéo labor+machine
            row.update(overall_combined_status="NOT_COMBINABLE", planned_increment=None, remaining_gap_after_plan=None)
        elif types:
            c = cov[types[0]]
            row.update(overall_combined_status=c["status"], planned_increment=c["planned_increment"], remaining_gap_after_plan=c["remaining_gap"])
        else:
            row.update(overall_combined_status="NOT_COVERED", planned_increment=0.0, remaining_gap_after_plan=r.gap)
        targets.append(row)
    return {"engine": COVERAGE_ENGINE, "source_run_id": v.source_run_id, "source_run_fingerprint": v.source_run_fingerprint, "targets": targets,
            "unresolved_items": [{"item_id": i.id, "proposal_id": i.proposal_id, "proposal_type": i.proposal_type, "target_result_id": i.target_result_id,
                                  "source_milestone_code": i.source_milestone_code, "source_proposal_calc_status": i.source_proposal_calc_status,
                                  "planned_effective_date": _iso(i.planned_effective_date)} for i in unresolved],
            "counted_item_count": len(counted), "unresolved_count": len(unresolved)}


def _refresh_preview(db: Session, v: RoadmapActionPlanVersion) -> None:
    v.coverage_json = compute_coverage(db, v)


# ------------------------------------------------------------------ create / edit
def _ensure_editable(v: RoadmapActionPlanVersion) -> None:
    if v.status != "DRAFT":
        raise _bad(f"Action Plan version {v.status} bất biến — chỉ sửa DRAFT; sửa = version mới", 409)


def _ensure_scenario_open(db: Session, plan: RoadmapActionPlan) -> None:
    if db.get(RoadmapScenario, plan.scenario_id).status == "ARCHIVED":
        raise _bad("Scenario đã ARCHIVED", 409)


def create_plan(db: Session, user: User, run_id: int, d: dict) -> RoadmapActionPlanVersion:
    run = eng.get_run(db, run_id)
    sv = db.get(RoadmapScenarioVersion, run.version_id)
    if db.get(RoadmapScenario, sv.scenario_id).status == "ARCHIVED":
        raise _bad("Scenario đã ARCHIVED", 409)
    plan = RoadmapActionPlan(action_plan_code="PENDING", name=(d.get("name") or "").strip()[:150], scenario_id=sv.scenario_id, scenario_version_id=sv.id, source_run_id=run.id,
                             created_by=user.username)
    db.add(plan)
    db.flush()
    plan.action_plan_code = f"AP-{plan.id:06d}"  # bất biến
    v = RoadmapActionPlanVersion(plan_id=plan.id, version_no=1, source_run_id=run.id, source_run_fingerprint=run.run_fingerprint, status="DRAFT", note=(d.get("note") or "").strip()[:300],
                                 created_by=user.username)
    db.add(v)
    db.flush()
    _refresh_preview(db, v)
    rm._hist(db, "ACTION_PLAN", v.id, None, "DRAFT", "created", user.username)
    db.commit()
    write_audit("ROADMAP_ACTION_PLAN_CREATE", user=user, object_type="RoadmapActionPlan", object_id=plan.action_plan_code, detail=f"run#{run.run_no}")
    return v


def _conflict_check(db: Session, v: RoadmapActionPlanVersion, proposal: RoadmapProposal, inclusion: str, exclude_id: int | None) -> None:
    for o in version_items(db, v.id):
        if o.id == exclude_id or o.proposal_id == proposal.id:
            continue
        if o.target_result_id == proposal.target_result_id and o.proposal_type == proposal.proposal_type and "COUNTED" in (o.inclusion_status, inclusion):
            raise _bad(f"Đã có item {o.inclusion_status} của proposal #{o.proposal_id} cùng (target, {proposal.proposal_type}) — các rule cùng loại là phương án thay thế, không cộng/không bypass. "
                       "Dùng Action Plan version khác hoặc thay selection ở DRAFT", 409)


def _prepare(db: Session, v: RoadmapActionPlanVersion, d: dict, existing: RoadmapActionPlanItem | None) -> dict:
    pid = d.get("proposal_id", existing.proposal_id if existing else None)
    p = db.get(RoadmapProposal, pid) if pid is not None else None
    if p is None:
        raise _bad("proposal_id không tồn tại", 404)
    if p.run_id != v.source_run_id:
        raise _bad("Proposal thuộc Run khác source run của Action Plan — không trộn proposal giữa các Run", 409)
    if existing is not None and p.id != existing.proposal_id:
        raise _bad("Không đổi proposal của item — xóa và thêm item mới")
    if p.decision_status == "REJECTED":
        raise _bad("Proposal đang REJECTED — không thêm vào Action Plan", 409)
    if p.calc_status == "NOT_APPLICABLE":
        raise _bad("Proposal NOT_APPLICABLE không được đưa vào Action Plan", 422)
    raw_date = d.get("planned_effective_date", existing.planned_effective_date if existing else None)
    if raw_date in (None, ""):
        raise _bad("planned_effective_date bắt buộc")
    eff = rm._date(raw_date, "planned_effective_date")
    run = db.get(RoadmapRun, v.source_run_id)
    if eff < run.created_at.date():
        raise _bad(f"planned_effective_date không được trước ngày tạo Run ({run.created_at.date().isoformat()}) — không backdate")
    isnap = p.input_snapshot_json or {}
    rule = isnap.get("executable_rule") or {}
    prod_raw = rule.get("productivity_value")
    lineage_ok = (p.calc_status == "CALCULATED" and p.proposal_type in COUNTABLE_PROPOSAL_TYPES and prod_raw is not None and float(prod_raw) > 0
                  and p.quantity is not None and float(p.quantity).is_integer() and p.quantity > 0 and isnap.get("adapter_output") is not None)
    want_unresolved = bool(d.get("as_unresolved", (existing.inclusion_status == "UNRESOLVED") if existing else False))
    common = {"proposal": p, "eff": eff, "notes": (d.get("notes", existing.notes if existing else "") or "").strip()[:300]}
    if lineage_ok and not want_unresolved:
        n = int(p.quantity)
        q_raw = d.get("selected_quantity", existing.selected_quantity if existing else n)
        q_raw = n if q_raw is None else q_raw
        if isinstance(q_raw, bool) or not isinstance(q_raw, (int, float)) or int(q_raw) != q_raw:
            raise _bad("selected_quantity phải là số nguyên (không fractional worker/machine)")
        q = int(q_raw)
        if q < 1 or q > n:
            raise _bad(f"selected_quantity phải trong 1..{n} (quantity của proposal)")
        used = sum(o.selected_quantity or 0 for o in version_items(db, v.id) if o.proposal_id == p.id and o.inclusion_status == "COUNTED" and (existing is None or o.id != existing.id))
        if used + q > n:
            raise _bad(f"Tổng selected_quantity của proposal #{p.id} ({used}+{q}) vượt quantity {n}", 409)
        ef, et = rule.get("effective_from"), rule.get("effective_to")
        ef_d = date.fromisoformat(ef) if ef else None
        et_d = date.fromisoformat(et) if et else None
        if ef_d is None or eff < ef_d or (et_d is not None and eff > et_d):
            raise _bad(f"planned_effective_date {eff.isoformat()} nằm ngoài hiệu lực của executable rule ({ef or '-'} → {et or 'mở'}) — không COUNTED được; "
                       "có thể lưu dưới dạng UNRESOLVED (as_unresolved) để theo dõi")
        _conflict_check(db, v, p, "COUNTED", existing.id if existing else None)
        inc = _dec(q) * _dec(prod_raw)
        return {**common, "inclusion": "COUNTED", "qty": q, "inc": _f(inc), "persistence": "PERSISTENT", "prod": float(prod_raw), "prod_unit": rule.get("productivity_unit", ""), "ef": ef_d, "et": et_d}
    if d.get("selected_quantity") is not None:
        raise _bad("Item UNRESOLVED là full-line, không numeric scaling — không nhận selected_quantity")
    _conflict_check(db, v, p, "UNRESOLVED", existing.id if existing else None)
    return {**common, "inclusion": "UNRESOLVED", "qty": None, "inc": None, "persistence": "UNSPECIFIED", "prod": None, "prod_unit": "", "ef": None, "et": None}


def _apply(db: Session, v: RoadmapActionPlanVersion, item: RoadmapActionPlanItem, x: dict) -> None:
    p = x["proposal"]
    isnap = p.input_snapshot_json or {}
    tr = db.get(RoadmapRunTargetResult, p.target_result_id) if p.target_result_id else None
    item.proposal_id, item.proposal_type, item.target_result_id, item.source_milestone_code = p.id, p.proposal_type, p.target_result_id, p.milestone_code
    item.planned_effective_date, item.selected_quantity, item.planned_increment = x["eff"], x["qty"], x["inc"]
    item.unit, item.impact_persistence, item.inclusion_status = (p.unit if x["inclusion"] == "COUNTED" else ""), x["persistence"], x["inclusion"]
    item.source_proposal_calc_status, item.source_proposal_decision_snapshot = p.calc_status, p.decision_status
    item.productivity_value, item.productivity_unit, item.rule_effective_from, item.rule_effective_to = x["prod"], x["prod_unit"], x["ef"], x["et"]
    item.source_run_fingerprint, item.notes = v.source_run_fingerprint, x["notes"]
    item.snapshot_json = {
        "proposal": eng.proposal_view(p), "source_run_id": v.source_run_id, "source_run_fingerprint": v.source_run_fingerprint,
        "target_result": None if tr is None else {"id": tr.id, "milestone_code": tr.milestone_code, "milestone_date": _iso(tr.milestone_date), "metric_code": tr.metric_code,
                                                  "period_label": tr.period_label, "gap": tr.gap, "unit": tr.unit, "scope_type": tr.scope_type, "scope_value": tr.scope_value},
        "lineage": {"period_type": isnap.get("period_type"), "capacity_unit": "sp", "scope_type": p.scope_type, "scope_value": p.scope_value,
                    "rule": (isnap.get("executable_rule") or {}) if x["inclusion"] == "COUNTED" else {}, "adapter_output": isnap.get("adapter_output"), "capacity_impact": isnap.get("capacity_impact"),
                    "evidence_refs": p.evidence_refs_json or []},
    }


def add_item(db: Session, user: User, version_id: int, d: dict) -> RoadmapActionPlanItem:
    v = get_version(db, version_id)
    _ensure_editable(v)
    _ensure_scenario_open(db, get_plan(db, v.plan_id))
    x = _prepare(db, v, d, None)
    dup = db.query(RoadmapActionPlanItem.id).filter_by(plan_version_id=v.id, proposal_id=x["proposal"].id, planned_effective_date=x["eff"]).first()
    if dup:
        raise _bad("Đã có item cùng proposal + cùng ngày hiệu lực — không nhân đôi", 409)
    item = RoadmapActionPlanItem(plan_version_id=v.id, proposal_id=x["proposal"].id, proposal_type=x["proposal"].proposal_type, planned_effective_date=x["eff"], created_by=user.username)
    _apply(db, v, item, x)
    db.add(item)
    db.flush()
    _refresh_preview(db, v)
    db.commit()
    write_audit("ROADMAP_ACTION_ITEM_ADD", user=user, object_type="RoadmapActionPlanVersion", object_id=str(v.id), detail=f"proposal#{item.proposal_id} {item.inclusion_status} qty={item.selected_quantity}")
    return item


def update_item(db: Session, user: User, item_id: int, d: dict) -> RoadmapActionPlanItem:
    item = get_item(db, item_id)
    v = get_version(db, item.plan_version_id)
    _ensure_editable(v)
    _ensure_scenario_open(db, get_plan(db, v.plan_id))
    x = _prepare(db, v, d, item)
    if x["eff"] != item.planned_effective_date and db.query(RoadmapActionPlanItem.id).filter_by(plan_version_id=v.id, proposal_id=item.proposal_id, planned_effective_date=x["eff"]).first():
        raise _bad("Đã có item cùng proposal + cùng ngày hiệu lực — không nhân đôi", 409)
    _apply(db, v, item, x)
    db.flush()
    _refresh_preview(db, v)
    db.commit()
    write_audit("ROADMAP_ACTION_ITEM_UPDATE", user=user, object_type="RoadmapActionPlanVersion", object_id=str(v.id), detail=f"item#{item.id}")
    return item


def remove_item(db: Session, user: User, item_id: int) -> None:
    item = get_item(db, item_id)
    v = get_version(db, item.plan_version_id)
    _ensure_editable(v)
    db.delete(item)
    db.flush()
    _refresh_preview(db, v)
    db.commit()
    write_audit("ROADMAP_ACTION_ITEM_REMOVE", user=user, object_type="RoadmapActionPlanVersion", object_id=str(v.id), detail=f"item#{item_id}")


# ------------------------------------------------------------------ workflow (four-eyes)
def _validate_snapshots(db: Session, v: RoadmapActionPlanVersion, items: list[RoadmapActionPlanItem]) -> list[str]:
    errs = []
    for i in items:
        if i.source_run_fingerprint != v.source_run_fingerprint or (i.snapshot_json or {}).get("proposal", {}).get("id") != i.proposal_id:
            errs.append(f"item#{i.id}: snapshot/lineage không khớp source run")
        if i.inclusion_status == "COUNTED":
            if i.productivity_value is None or i.selected_quantity is None or i.planned_increment is None or _dec(i.selected_quantity) * _dec(i.productivity_value) != _dec(i.planned_increment):
                errs.append(f"item#{i.id}: planned_increment ≠ selected_quantity × productivity snapshot")
    return errs


def _same_json(a, b) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def submit_review(db: Session, user: User, version_id: int) -> RoadmapActionPlanVersion:
    v = get_version(db, version_id)
    if v.status != "DRAFT":
        raise _bad(f"Chỉ chuyển UNDER_REVIEW từ DRAFT (hiện {v.status})", 409)
    _ensure_scenario_open(db, get_plan(db, v.plan_id))
    items = version_items(db, v.id)
    if not items:
        raise _bad("Action Plan cần ít nhất 1 item")
    errs = _validate_snapshots(db, v, items)
    if errs:
        raise _bad("Snapshot không hợp lệ: " + "; ".join(errs), 409)
    v.coverage_json = compute_coverage(db, v)  # đóng băng
    v.status, v.reviewed_by, v.reviewed_at = "UNDER_REVIEW", user.username, utcnow()
    rm._hist(db, "ACTION_PLAN", v.id, "DRAFT", "UNDER_REVIEW", "", user.username)
    db.commit()
    write_audit("ROADMAP_ACTION_PLAN_REVIEW", user=user, object_type="RoadmapActionPlanVersion", object_id=str(v.id), detail=f"items={len(items)}")
    return v


def approve(db: Session, user: User, version_id: int) -> RoadmapActionPlanVersion:
    """Quyền `roadmap.approve` do API kiểm."""
    v = get_version(db, version_id)
    if v.status != "UNDER_REVIEW":
        raise _bad(f"Chỉ duyệt được Action Plan UNDER_REVIEW (hiện {v.status})", 409)
    _ensure_scenario_open(db, get_plan(db, v.plan_id))
    if not v.reviewed_by or v.reviewed_by == user.username:
        raise _bad("Four-eyes: người duyệt (approver) phải khác người đã đưa vào review (reviewer)", 409)
    run = db.get(RoadmapRun, v.source_run_id)
    if run is None or run.run_fingerprint != v.source_run_fingerprint:
        raise _bad("Source run không còn khớp lineage", 409)
    items = version_items(db, v.id)
    if not items:
        raise _bad("Action Plan cần ít nhất 1 item", 409)
    errs = _validate_snapshots(db, v, items)
    if errs:
        raise _bad("Snapshot không hợp lệ: " + "; ".join(errs), 409)
    if not _same_json(compute_coverage(db, v), v.coverage_json):
        raise _bad("Coverage đóng băng không khớp tính lại từ snapshot", 409)
    v.status, v.approved_by, v.approved_at = "APPROVED", user.username, utcnow()
    rm._hist(db, "ACTION_PLAN", v.id, "UNDER_REVIEW", "APPROVED", "", user.username)
    db.commit()
    write_audit("ROADMAP_ACTION_PLAN_APPROVE", user=user, object_type="RoadmapActionPlanVersion", object_id=str(v.id), detail="không thực thi mua/tuyển")
    return v


def archive(db: Session, user: User, version_id: int, reason: str = "") -> RoadmapActionPlanVersion:
    v = get_version(db, version_id)
    if v.status != "APPROVED":
        raise _bad(f"Chỉ ARCHIVED từ APPROVED (hiện {v.status})", 409)
    if not (reason or "").strip():
        raise _bad("Archive bắt buộc có reason")
    v.status, v.archive_reason = "ARCHIVED", reason.strip()[:300]
    rm._hist(db, "ACTION_PLAN", v.id, "APPROVED", "ARCHIVED", reason.strip(), user.username)
    db.commit()
    write_audit("ROADMAP_ACTION_PLAN_ARCHIVE", user=user, object_type="RoadmapActionPlanVersion", object_id=str(v.id), detail=reason[:150])
    return v


def new_version(db: Session, user: User, version_id: int) -> RoadmapActionPlanVersion:
    src = get_version(db, version_id)
    plan = get_plan(db, src.plan_id)
    _ensure_scenario_open(db, plan)
    latest = db.query(RoadmapActionPlanVersion).filter_by(plan_id=plan.id).order_by(RoadmapActionPlanVersion.version_no.desc()).first()
    if latest.status in ("DRAFT", "UNDER_REVIEW"):
        raise _bad(f"Đã có version {latest.status} (v{latest.version_no}) — xử lý version đó trước", 409)
    v = RoadmapActionPlanVersion(plan_id=plan.id, version_no=latest.version_no + 1, source_run_id=src.source_run_id, source_run_fingerprint=src.source_run_fingerprint, status="DRAFT",
                                 note=src.note, copied_from_version_id=src.id, created_by=user.username)  # giữ nguyên source_run; muốn run khác => family mới
    db.add(v)
    db.flush()
    for i in version_items(db, src.id):
        db.add(RoadmapActionPlanItem(
            plan_version_id=v.id, proposal_id=i.proposal_id, proposal_type=i.proposal_type, target_result_id=i.target_result_id, source_milestone_code=i.source_milestone_code,
            planned_effective_date=i.planned_effective_date, selected_quantity=i.selected_quantity, planned_increment=i.planned_increment, unit=i.unit,
            impact_persistence=i.impact_persistence, inclusion_status=i.inclusion_status, source_proposal_calc_status=i.source_proposal_calc_status,
            source_proposal_decision_snapshot=i.source_proposal_decision_snapshot, productivity_value=i.productivity_value, productivity_unit=i.productivity_unit,
            rule_effective_from=i.rule_effective_from, rule_effective_to=i.rule_effective_to, source_run_fingerprint=i.source_run_fingerprint, notes=i.notes,
            snapshot_json=json.loads(json.dumps(i.snapshot_json, default=str)), created_by=user.username))  # clone snapshot, không live rule
    db.flush()
    _refresh_preview(db, v)
    rm._hist(db, "ACTION_PLAN", v.id, None, "DRAFT", f"new version of v{src.version_no}", user.username)
    db.commit()
    write_audit("ROADMAP_ACTION_PLAN_NEW_VERSION", user=user, object_type="RoadmapActionPlanVersion", object_id=str(v.id), detail=f"from v{src.version_no}")
    return v


# ------------------------------------------------------------------ compare (không ranking/winner)
def compare(db: Session, a_id: int, b_id: int) -> dict:
    a, b = get_version(db, a_id), get_version(db, b_id)
    pa, pb = get_plan(db, a.plan_id), get_plan(db, b.plan_id)
    if a.plan_id != b.plan_id and pa.scenario_version_id != pb.scenario_version_id:
        raise _bad("Chỉ so sánh version cùng Action Plan hoặc các Action Plan cùng scenario_version_id", 409)

    def key(t):
        return (t["milestone_code"], t["metric_code"], t["period_label"], t["scope_type"], t["scope_value"])

    ta = {key(t): t for t in (a.coverage_json or {}).get("targets", [])}
    tb = {key(t): t for t in (b.coverage_json or {}).get("targets", [])}

    def side(t):
        return None if t is None else {"original_gap": t["original_gap"], "coverage_by_proposal_type": {k: {x: v[x] for x in ("planned_increment", "remaining_gap", "status")} for k, v in t["coverage_by_proposal_type"].items()},
                                       "overall_combined_status": t["overall_combined_status"], "has_unresolved_actions": t["has_unresolved_actions"]}

    targets = [{"key": dict(zip(("milestone_code", "metric_code", "period_label", "scope_type", "scope_value"), k)), "a": side(ta.get(k)), "b": side(tb.get(k)),
                "changed": not _same_json(side(ta.get(k)), side(tb.get(k)))} for k in sorted(set(ta) | set(tb))]

    def items_of(v):
        out = {}
        for i in version_items(db, v.id):
            rule = ((i.snapshot_json or {}).get("lineage") or {}).get("rule") or {}
            lineage = f"{rule.get('rule_code')}@v{rule.get('rule_version')}" if rule else (i.snapshot_json or {}).get("proposal", {}).get("calculation_rule_version", "NONE")
            out[(i.proposal_type, lineage, i.source_milestone_code, i.planned_effective_date.isoformat(), i.inclusion_status)] = {"selected_quantity": i.selected_quantity, "planned_increment": i.planned_increment}
        return out

    ia, ib = items_of(a), items_of(b)
    items = [{"proposal_type": k[0], "rule_lineage": k[1], "source_milestone_code": k[2], "planned_effective_date": k[3], "inclusion_status": k[4], "a": ia.get(k), "b": ib.get(k),
              "changed": ia.get(k) != ib.get(k)} for k in sorted(set(ia) | set(ib))]
    return {"a": version_view(db, a, detail=False), "b": version_view(db, b, detail=False), "same_source_run": a.source_run_id == b.source_run_id,
            "source_runs": {"a": {"run_id": a.source_run_id, "fingerprint": a.source_run_fingerprint}, "b": {"run_id": b.source_run_id, "fingerprint": b.source_run_fingerprint}},
            "targets": targets, "items": items}  # không rank/score/winner
