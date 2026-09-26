"""Executive Decision Package (Task 8 — Issue #17, GPT COST/EVIDENCE CONTRACT).

Package = snapshot đóng băng của 1 Action Plan version **APPROVED** + cost bindings do user chọn tường minh (1 evidence / COUNTED item; KHÔNG auto-pick, KHÔNG tie-break).
- Direct cost (Decimal exact, không round khi cộng): MACHINE_CAPEX = selected_quantity × unit_price (group currency);
  LABOR_RECURRING_COST = selected_quantity × cost_per_worker_per_period (group currency + cost_period; run-rate mỗi kỳ, KHÔNG nhân số kỳ/accumulate/annualize).
- KHÔNG grand_total / CAPEX+OPEX total / FX / ROI-NPV-IRR-payback / ranking. Technology/Capacity/UNRESOLVED luôn UNPRICED (UNSUPPORTED_COST_FAMILY / UNRESOLVED_ACTION).
- Evidence phải APPROVED + hiệu lực tại planned_effective_date (+ quote_valid_until cho SUPPLIER_QUOTATION); không đúng => UNPRICED + warning (không fallback).
- Lifecycle DRAFT (preview live) -> UNDER_REVIEW (đóng băng package_json + binding snapshots) -> APPROVED (verify từ snapshot, không đọc nguồn sống) -> ARCHIVED (chỉ từ APPROVED + reason).
  Four-eyes; cho APPROVE khi còn UNPRICED/unresolved/warnings. Evidence retire SAU freeze => chỉ live-overlay warning SOURCE_EVIDENCE_RETIRED_AFTER_SNAPSHOT (không đổi package_json/fingerprint).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import User
from app.models.future_technology import FutureTechnologyCandidate, FutureTechnologyEvidence
from app.models.resources import MachineModel, MachineType
from app.models.roadmap import (
    COUNTABLE_PROPOSAL_TYPES,
    RoadmapActionPlan,
    RoadmapActionPlanItem,
    RoadmapActionPlanVersion,
    RoadmapCostEvidence,
    RoadmapDecisionPackage,
    RoadmapPackageBinding,
    RoadmapRun,
    RoadmapScenario,
    RoadmapScenarioVersion,
)
from app.services import roadmap as rm
from app.services import roadmap_action_plan as ap
from app.services import roadmap_cost as rc
from app.services.audit import write_audit

_bad = rm._bad
_iso = rm._iso
PACKAGE_ENGINE = "DP_V1"
FAMILY_OF = {"MACHINE_PURCHASE": "MACHINE_UNIT_PRICE", "LABOR_RECRUITMENT": "LABOR_COST_PER_WORKER_PERIOD"}
AFTER_LAST = "AFTER_LAST_MILESTONE"


def _hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")).hexdigest()[:40]


def _dec(v) -> Decimal:
    return Decimal(str(v))


# ------------------------------------------------------------------ getters / guards
def get_package(db: Session, package_id: int) -> RoadmapDecisionPackage:
    p = db.get(RoadmapDecisionPackage, package_id)
    if p is None:
        raise HTTPException(404, "Không tìm thấy Decision Package")
    return p


def package_bindings(db: Session, package_id: int) -> list[RoadmapPackageBinding]:
    return db.query(RoadmapPackageBinding).filter_by(package_id=package_id).order_by(RoadmapPackageBinding.id).all()


def _ctx(db: Session, pkg: RoadmapDecisionPackage):
    apv = ap.get_version(db, pkg.action_plan_version_id)
    plan = ap.get_plan(db, apv.plan_id)
    return apv, plan


def _ensure_scenario_open(db: Session, plan: RoadmapActionPlan) -> None:
    if db.get(RoadmapScenario, plan.scenario_id).status == "ARCHIVED":
        raise _bad("Scenario đã ARCHIVED", 409)


def _ensure_draft(pkg: RoadmapDecisionPackage) -> None:
    if pkg.status != "DRAFT":
        raise _bad(f"Package {pkg.status} bất biến — chỉ sửa DRAFT", 409)


# ------------------------------------------------------------------ pricing (pure)
def _milestones(run_snapshot: dict) -> list[dict]:
    ms = (run_snapshot or {}).get("version", {}).get("milestones", [])
    return sorted(({"code": m["code"], "date": m["target_date"], "name": m.get("name", "")} for m in ms), key=lambda m: m["date"])


def bucket_for(eff: date, milestones: list[dict]) -> str:
    """Planning bucket (KHÔNG phải payment/cash date): milestone đầu tiên có target_date >= planned_effective_date."""
    for m in milestones:
        if date.fromisoformat(m["date"]) >= eff:
            return m["code"]
    return AFTER_LAST


def evaluate_line(item: RoadmapActionPlanItem, ev: dict | None, milestones: list[dict]) -> dict:
    """Định giá 1 action item từ evidence SNAPSHOT (dict). Trả line có cost_status PRICED|UNPRICED; không bịa số."""
    lin = (item.snapshot_json or {}).get("lineage", {})
    rule = lin.get("rule") or {}
    line = {"item_id": item.id, "proposal_id": item.proposal_id, "proposal_type": item.proposal_type, "source_milestone_code": item.source_milestone_code,
            "planned_effective_date": _iso(item.planned_effective_date), "milestone_bucket": bucket_for(item.planned_effective_date, milestones), "inclusion_status": item.inclusion_status,
            "selected_quantity": item.selected_quantity, "planned_increment": item.planned_increment, "unit": item.unit, "period_type": lin.get("period_type"),
            "scope_type": lin.get("scope_type"), "scope_value": lin.get("scope_value"), "machine_type_code": rule.get("machine_type_code"),
            "productivity_value": item.productivity_value, "productivity_unit": item.productivity_unit,
            "cost_class": None, "cost_status": "UNPRICED", "cost_status_reason": "", "evidence": None, "unit_cost": None, "currency": None, "cost_period": None, "price_basis": None,
            "amount": None, "warnings": []}
    w = line["warnings"]
    if item.inclusion_status != "COUNTED" or item.proposal_type not in COUNTABLE_PROPOSAL_TYPES:
        line["cost_status_reason"] = "UNSUPPORTED_COST_FAMILY" if item.proposal_type not in COUNTABLE_PROPOSAL_TYPES else "UNRESOLVED_ACTION"
        w.append("UNRESOLVED_ACTION")
        w.append("UNPRICED_ACTION")
        return line
    is_machine = item.proposal_type == "MACHINE_PURCHASE"
    line["cost_class"] = "MACHINE_CAPEX" if is_machine else "LABOR_RECURRING_COST"
    if ev is None:
        line["cost_status_reason"] = "MISSING_PRICE_EVIDENCE" if is_machine else "MISSING_LABOR_COST_BASIS"
        w += ["MISSING_PRICE_EVIDENCE" if is_machine else "MISSING_LABOR_COST_BASIS", "UNPRICED_ACTION"]
        return line
    line["evidence"] = {"id": ev["id"], "evidence_code": ev["evidence_code"], "evidence_version": ev["evidence_version"], "source_kind": ev["source_kind"], "status_at_snapshot": ev["status"]}

    def fail(code: str) -> dict:
        line["cost_status_reason"] = code
        w.extend([code, "UNPRICED_ACTION"])
        return line

    if ev["status"] != "APPROVED":
        return fail("PRICE_NOT_APPROVED")
    eff = item.planned_effective_date.isoformat()
    if ev["effective_from"] is None or eff < ev["effective_from"] or (ev["effective_to"] and eff > ev["effective_to"]):
        return fail("PRICE_OUTSIDE_EFFECTIVE_DATE")
    if ev["source_kind"] == "SUPPLIER_QUOTATION" and (not ev["quote_valid_until"] or eff > ev["quote_valid_until"]):
        return fail("QUOTE_EXPIRED")
    if ev["cost_family"] != FAMILY_OF[item.proposal_type]:
        return fail("PRICE_NOT_APPROVED")
    if is_machine:
        if ev["machine_type_code"] != line["machine_type_code"]:
            return fail("PRICE_NOT_APPROVED")
    else:
        if (ev["scope_type"], ev["scope_value"]) != (line["scope_type"], line["scope_value"]):
            return fail("PRICE_OUTSIDE_EFFECTIVE_DATE")
        if ev["cost_period"] != line["period_type"]:  # không quy đổi MONTH↔YEAR
            return fail("COST_PERIOD_MISMATCH")
    if item.selected_quantity is None or item.selected_quantity < 1:
        return fail("UNPRICED_ACTION")
    amount = _dec(item.selected_quantity) * _dec(ev["amount"])
    line.update(cost_status="PRICED", cost_status_reason="", unit_cost=ev["amount"], currency=ev["currency"], amount=rc.dstr(amount),
                cost_period=ev["cost_period"] or None, price_basis=ev["price_basis"] or None)
    return line


def summarize(lines: list[dict], milestones: list[dict]) -> dict:
    """Aggregation Decimal exact; machine & labor tách riêng; group theo currency (machine) / currency+period (labor); KHÔNG grand_total."""
    cap: dict[str, dict] = {}
    lab: dict[tuple, dict] = {}
    for ln in lines:
        if ln["cost_status"] != "PRICED":
            continue
        a = _dec(ln["amount"])
        if ln["cost_class"] == "MACHINE_CAPEX":
            g = cap.setdefault(ln["currency"], {"amount": Decimal(0), "item_ids": [], "by_milestone_bucket": {}})
            g["amount"] += a
            g["item_ids"].append(ln["item_id"])
            g["by_milestone_bucket"][ln["milestone_bucket"]] = g["by_milestone_bucket"].get(ln["milestone_bucket"], Decimal(0)) + a
        else:
            g = lab.setdefault((ln["currency"], ln["cost_period"]), {"amount": Decimal(0), "item_ids": []})
            g["amount"] += a
            g["item_ids"].append(ln["item_id"])
    machine = [{"currency": c, "amount": rc.dstr(g["amount"]), "item_ids": g["item_ids"], "by_milestone_bucket": {k: rc.dstr(v) for k, v in sorted(g["by_milestone_bucket"].items())}}
               for c, g in sorted(cap.items())]
    labor = [{"currency": c, "cost_period": p, "amount": rc.dstr(g["amount"]), "item_ids": g["item_ids"]} for (c, p), g in sorted(lab.items())]
    run_rate = []
    for m in milestones:  # run-rate tại milestone (persistent, effective <= milestone) — KHÔNG phải "total labor cost to milestone"
        rr: dict[tuple, Decimal] = {}
        for ln in lines:
            if ln["cost_status"] == "PRICED" and ln["cost_class"] == "LABOR_RECURRING_COST" and ln["planned_effective_date"] <= m["date"]:
                k = (ln["currency"], ln["cost_period"])
                rr[k] = rr.get(k, Decimal(0)) + _dec(ln["amount"])
        for (c, p), v in sorted(rr.items()):
            run_rate.append({"milestone_code": m["code"], "milestone_date": m["date"], "currency": c, "cost_period": p, "run_rate_per_period": rc.dstr(v)})
    unpriced = [{"item_id": ln["item_id"], "proposal_type": ln["proposal_type"], "reason": ln["cost_status_reason"] or "UNPRICED_ACTION", "inclusion_status": ln["inclusion_status"]}
                for ln in lines if ln["cost_status"] != "PRICED"]
    return {"MACHINE_CAPEX": machine, "LABOR_RECURRING_COST": labor, "labor_run_rate_by_milestone": run_rate, "UNPRICED_ACTIONS": unpriced}


def _completeness(lines: list[dict]) -> dict:
    supported = [ln for ln in lines if ln["cost_class"] is not None]
    priced = [ln for ln in supported if ln["cost_status"] == "PRICED"]
    label = "UNPRICED" if not priced else ("COMPLETE_PRICING" if len(priced) == len(supported) else "PARTIAL_PRICING")
    return {"pricing": label, "supported_action_count": len(supported), "priced_action_count": len(priced), "unresolved_count": sum(1 for ln in lines if ln["inclusion_status"] != "COUNTED")}


# ------------------------------------------------------------------ details (machine/labor)
def machine_type_details(db: Session, code: str | None) -> dict | None:
    t = db.get(MachineType, code) if code else None
    if t is None:
        return None
    return {"code": t.code, "name": t.name, "model": t.model, "machine_group": t.machine_group, "process": t.process, "status": t.status,
            "reference_placeholders": {"nominal_output_per_day": t.nominal_output_per_day, "default_efficiency": t.default_efficiency,
                                       "note": "giá trị tham chiếu/placeholder trong MachineType — KHÔNG phải spec đã chứng minh"}}


def binding_details(db: Session, machine_type_code: str | None, model_id: int | None, cand_id: int | None) -> dict:
    out: dict = {"machine_type": machine_type_details(db, machine_type_code), "machine_model": None, "future_candidate": None, "asset_refs": []}
    if model_id is not None:
        m = db.get(MachineModel, model_id)
        if m is not None:
            out["machine_model"] = {"id": m.id, "brand": m.brand, "model": m.model, "automation_level": m.automation_level, "reference_output": m.reference_output,
                                    "reference_cycle_time": m.reference_cycle_time, "required_operator": m.required_operator, "source": m.source, "status": m.status}
    if cand_id is not None:
        c = db.get(FutureTechnologyCandidate, cand_id)
        if c is not None:
            evs = db.query(FutureTechnologyEvidence).filter_by(candidate_id=c.id).order_by(FutureTechnologyEvidence.id).all()
            out["future_candidate"] = {"id": c.id, "candidate_code": c.candidate_code, "brand": c.brand, "model_name": c.model_name, "technology_name": c.technology_name,
                                       "automation_level": c.automation_level, "status": c.status,
                                       "evidence": [{"id": e.id, "source_kind": e.source_kind, "source_ref": e.source_ref, "basis": e.basis, "metric_code": e.metric_code, "value": e.value,
                                                     "unit": e.unit, "evidence_date": _iso(e.evidence_date)} for e in evs]}
    subjects = [("MACHINE_TYPE", machine_type_code), ("MACHINE_MODEL", str(model_id) if model_id is not None else None), ("FUTURE_CANDIDATE", str(cand_id) if cand_id is not None else None)]
    for st, ref in subjects:
        if ref:
            out["asset_refs"] += [{**rc.asset_view(a), "created_at": None} for a in rc.list_assets(db, st, ref, active_only=True)]
    return out


# ------------------------------------------------------------------ build
def _evidence_maps(db: Session, pkg: RoadmapDecisionPackage, frozen: bool) -> tuple[dict, dict, dict]:
    ev, det, bmap = {}, {}, {}
    for b in package_bindings(db, pkg.id):
        bmap[b.action_item_id] = b
        if frozen:
            ev[b.action_item_id], det[b.action_item_id] = b.snapshot_json.get("evidence"), b.snapshot_json.get("details")
        else:
            e = db.get(RoadmapCostEvidence, b.evidence_id)
            ev[b.action_item_id] = rc.evidence_snapshot(e) if e else None
    return ev, det, bmap


def build_package(db: Session, pkg: RoadmapDecisionPackage, frozen: bool = False) -> dict:
    apv, plan = _ctx(db, pkg)
    run = db.get(RoadmapRun, apv.source_run_id)
    scen = db.get(RoadmapScenario, plan.scenario_id)
    sv = db.get(RoadmapScenarioVersion, plan.scenario_version_id)
    milestones = _milestones(run.snapshot_json)
    items = ap.version_items(db, apv.id)
    ev, det, bmap = _evidence_maps(db, pkg, frozen)
    lines = [evaluate_line(i, ev.get(i.id), milestones) for i in items]
    selected, unresolved, machine_details, labor_details = [], [], [], []
    for i, ln in zip(items, lines):
        if i.inclusion_status != "COUNTED":
            unresolved.append({**ln, "evidence_refs": (i.snapshot_json or {}).get("lineage", {}).get("evidence_refs", [])})
            continue
        selected.append(ln)
        lin = (i.snapshot_json or {}).get("lineage", {})
        if i.proposal_type == "MACHINE_PURCHASE":
            b = bmap.get(i.id)
            d = det.get(i.id) if frozen and b is not None else None
            if d is None:
                d = binding_details(db, ln["machine_type_code"], b.machine_model_id if b else None, b.future_candidate_id if b else None)
            machine_details.append({"item_id": i.id, "machine_type_code": ln["machine_type_code"], "selected_quantity": i.selected_quantity, "bound_model_id": b.machine_model_id if b else None,
                                    "bound_candidate_id": b.future_candidate_id if b else None, "details": d, "price_basis": ln["price_basis"]})
        else:
            labor_details.append({"item_id": i.id, "selected_headcount": i.selected_quantity, "productivity": {"value": i.productivity_value, "unit": i.productivity_unit},
                                  "rule": {k: (lin.get("rule") or {}).get(k) for k in ("rule_code", "rule_version", "source_kind", "source_ref")},
                                  "labor_standard_context": ((i.snapshot_json or {}).get("proposal", {}).get("input_snapshot") or {}).get("available_baseline"),
                                  "scope": {"type": lin.get("scope_type"), "value": lin.get("scope_value")}, "cost_period": ln["cost_period"]})
    summary = summarize(lines, milestones)
    warnings = [{"code": c, "item_id": ln["item_id"]} for ln in lines for c in ln["warnings"]]
    cov = apv.coverage_json or {}
    if any(t.get("mixed_resource_types") for t in cov.get("targets", [])):
        warnings.append({"code": "MIXED_RESOURCE_TYPES", "item_id": None})
    used = []
    for iid, e in ev.items():
        if e is not None:
            used.append({"item_id": iid, **e})
    return {
        "engine": PACKAGE_ENGINE,
        "scenario": {"id": scen.id, "code": scen.scenario_code, "name": scen.name, "status": scen.status, "scope_type": scen.scope_type, "scope_value": scen.scope_value},
        "scenario_version": {"id": sv.id, "version_no": sv.version_no, "status": sv.status},
        "source_run": {"id": run.id, "run_no": run.run_no, "fingerprint": run.run_fingerprint, "engine_version": run.engine_version},
        "action_plan": {"id": plan.id, "code": plan.action_plan_code, "version_id": apv.id, "version_no": apv.version_no, "status": apv.status, "reviewed_by": apv.reviewed_by,
                        "approved_by": apv.approved_by, "approved_at": _iso(apv.approved_at)},
        "milestones": milestones,
        "targets": cov.get("targets", []),  # gồm coverage_by_proposal_type (giữ NOT_COMBINABLE)
        "selected_actions": selected, "unresolved_actions": unresolved,
        "technology_evidence": (run.snapshot_json or {}).get("technology_links", []),
        "machine_details": machine_details, "labor_details": labor_details, "cost_evidence_used": used,
        "direct_cost_summary": summary, "completeness": _completeness(lines),
        "warnings": warnings, "warning_codes": sorted({w["code"] for w in warnings}),
        "history_refs": {"action_plan_version_id": apv.id, "scenario_id": scen.id, "source_run_id": run.id},
    }


def effective_package_json(db: Session, pkg: RoadmapDecisionPackage) -> dict:
    """DRAFT => preview LIVE (build từ bindings/evidence/details hiện tại, không lưu DB, không giả lập frozen); UNDER_REVIEW/APPROVED/ARCHIVED => chỉ trả package_json đã đóng băng."""
    return build_package(db, pkg, frozen=False) if pkg.status == "DRAFT" else (pkg.package_json or {})


def _refresh_preview(db: Session, pkg: RoadmapDecisionPackage) -> None:
    """DRAFT không lưu preview: package_json rỗng + fingerprint rỗng cho tới khi freeze (tránh nhầm với snapshot đã đóng băng)."""
    pkg.package_json = {}
    pkg.package_fingerprint = ""


# ------------------------------------------------------------------ views
def _live_warnings(db: Session, pkg: RoadmapDecisionPackage) -> list[dict]:
    """Live overlay (KHÔNG sửa package_json/fingerprint): evidence đã RETIRED sau snapshot."""
    if pkg.status == "DRAFT":
        return []
    out = []
    for b in package_bindings(db, pkg.id):
        snap = (b.snapshot_json or {}).get("evidence") or {}
        e = db.get(RoadmapCostEvidence, b.evidence_id)
        if e is not None and e.status == "RETIRED" and snap.get("status") == "APPROVED":
            out.append({"code": "SOURCE_EVIDENCE_RETIRED_AFTER_SNAPSHOT", "item_id": b.action_item_id, "evidence_id": e.id,
                        "evidence": f"{e.evidence_code}@v{e.evidence_version}", "detail": "evidence đã RETIRED sau khi snapshot; số liệu package giữ nguyên theo snapshot"})
    return out


def package_view(db: Session, pkg: RoadmapDecisionPackage, detail: bool = True) -> dict:
    apv, plan = _ctx(db, pkg)
    out = {"id": pkg.id, "package_code": pkg.package_code, "package_no": pkg.package_no, "status": pkg.status, "note": pkg.note, "action_plan_version_id": apv.id,
           "action_plan_code": plan.action_plan_code, "action_plan_version_no": apv.version_no, "action_plan_id": plan.id, "scenario_version_id": plan.scenario_version_id,
           "source_run_id": apv.source_run_id, "package_fingerprint": pkg.package_fingerprint, "reviewed_by": pkg.reviewed_by, "reviewed_at": _iso(pkg.reviewed_at),
           "approved_by": pkg.approved_by, "approved_at": _iso(pkg.approved_at), "archive_reason": pkg.archive_reason, "created_by": pkg.created_by, "created_at": _iso(pkg.created_at),
           "editable": pkg.status == "DRAFT", "frozen": pkg.status != "DRAFT"}
    if detail:
        out["package"] = effective_package_json(db, pkg)
        out["live_warnings"] = _live_warnings(db, pkg)
        out["bindings"] = [{"id": b.id, "action_item_id": b.action_item_id, "evidence_id": b.evidence_id, "machine_model_id": b.machine_model_id, "future_candidate_id": b.future_candidate_id}
                           for b in package_bindings(db, pkg.id)]
    return out


def list_packages(db: Session, action_plan_version_id: int | None = None) -> list[RoadmapDecisionPackage]:
    q = db.query(RoadmapDecisionPackage)
    if action_plan_version_id:
        q = q.filter(RoadmapDecisionPackage.action_plan_version_id == action_plan_version_id)
    return q.order_by(RoadmapDecisionPackage.id.desc()).all()


def history(db: Session, package_id: int) -> list[dict]:
    get_package(db, package_id)
    return rm.list_history(db, "DEC_PACKAGE", package_id)


# ------------------------------------------------------------------ create / bind
def create_package(db: Session, user: User, action_plan_version_id: int, d: dict) -> RoadmapDecisionPackage:
    apv = ap.get_version(db, action_plan_version_id)
    if apv.status != "APPROVED":
        raise _bad(f"Decision Package chỉ tạo từ Action Plan version APPROVED (hiện {apv.status})", 409)
    plan = ap.get_plan(db, apv.plan_id)
    _ensure_scenario_open(db, plan)
    open_pkg = db.query(RoadmapDecisionPackage).filter(RoadmapDecisionPackage.action_plan_version_id == apv.id, RoadmapDecisionPackage.status.in_(("DRAFT", "UNDER_REVIEW"))).first()
    if open_pkg:
        raise _bad(f"Đã có package {open_pkg.package_code} ({open_pkg.status}) cho Action Plan version này — xử lý nó trước", 409)
    last = db.query(RoadmapDecisionPackage).filter_by(action_plan_version_id=apv.id).order_by(RoadmapDecisionPackage.package_no.desc()).first()
    pkg = RoadmapDecisionPackage(package_code="PENDING", action_plan_version_id=apv.id, package_no=(last.package_no + 1 if last else 1), status="DRAFT",
                                 note=(d.get("note") or "").strip()[:300], created_by=user.username)
    db.add(pkg)
    db.flush()
    pkg.package_code = f"DP-{pkg.id:06d}"
    _refresh_preview(db, pkg)
    rm._hist(db, "DEC_PACKAGE", pkg.id, None, "DRAFT", "created", user.username)
    db.commit()
    write_audit("ROADMAP_DECISION_PACKAGE_CREATE", user=user, object_type="RoadmapDecisionPackage", object_id=pkg.package_code, detail=f"AP v{apv.version_no}")
    return pkg


def bind(db: Session, user: User, package_id: int, d: dict) -> RoadmapPackageBinding:
    pkg = get_package(db, package_id)
    _ensure_draft(pkg)
    apv, plan = _ctx(db, pkg)
    _ensure_scenario_open(db, plan)
    item = db.get(RoadmapActionPlanItem, d.get("action_item_id"))
    if item is None or item.plan_version_id != apv.id:
        raise _bad("action_item_id không thuộc Action Plan version của package", 422)
    if item.inclusion_status != "COUNTED" or item.proposal_type not in COUNTABLE_PROPOSAL_TYPES:
        raise _bad("Chỉ bind evidence cho item COUNTED LABOR/MACHINE (Technology/Capacity/UNRESOLVED luôn UNPRICED)", 422)
    ev = db.get(RoadmapCostEvidence, d.get("evidence_id"))
    if ev is None:
        raise _bad("evidence_id không tồn tại", 404)
    if ev.status != "APPROVED":
        raise _bad(f"Chỉ bind evidence APPROVED (hiện {ev.status})", 422)
    if ev.cost_family != FAMILY_OF[item.proposal_type]:
        raise _bad(f"Evidence {ev.cost_family} không dùng cho {item.proposal_type}", 422)
    lin = (item.snapshot_json or {}).get("lineage", {})
    mid, cid = d.get("machine_model_id"), d.get("future_candidate_id")
    if item.proposal_type == "MACHINE_PURCHASE":
        mt = (lin.get("rule") or {}).get("machine_type_code")
        if ev.machine_type_code != mt:
            raise _bad(f"Evidence machine_type {ev.machine_type_code} khác machine_type của item ({mt})", 422)
        if ev.machine_model_id is not None:
            if mid is not None and mid != ev.machine_model_id:
                raise _bad("Evidence gắn model cụ thể — binding phải đúng model đó", 422)
            mid = ev.machine_model_id
        if ev.future_candidate_id is not None:
            if cid is not None and cid != ev.future_candidate_id:
                raise _bad("Evidence gắn candidate cụ thể — binding phải đúng candidate đó", 422)
            cid = ev.future_candidate_id
        rc.check_model_candidate(db, mt, mid, cid)
    else:
        if mid is not None or cid is not None:
            raise _bad("Labor binding không dùng machine model/candidate", 422)
        if (ev.scope_type, ev.scope_value) != (lin.get("scope_type"), lin.get("scope_value")):
            raise _bad("Labor evidence phải exact-match scope của item", 422)
    old = db.query(RoadmapPackageBinding).filter_by(package_id=pkg.id, action_item_id=item.id).first()
    if old:
        db.delete(old)
        db.flush()
    b = RoadmapPackageBinding(package_id=pkg.id, action_item_id=item.id, evidence_id=ev.id, machine_model_id=mid, future_candidate_id=cid, created_by=user.username)
    db.add(b)
    db.flush()
    _refresh_preview(db, pkg)
    db.commit()
    write_audit("ROADMAP_PACKAGE_BIND", user=user, object_type="RoadmapDecisionPackage", object_id=pkg.package_code, detail=f"item#{item.id} ← {ev.evidence_code}@v{ev.evidence_version}")
    return b


def unbind(db: Session, user: User, package_id: int, action_item_id: int) -> None:
    pkg = get_package(db, package_id)
    _ensure_draft(pkg)
    _ensure_scenario_open(db, _ctx(db, pkg)[1])
    b = db.query(RoadmapPackageBinding).filter_by(package_id=pkg.id, action_item_id=action_item_id).first()
    if b is None:
        raise _bad("Không có binding cho item này", 404)
    db.delete(b)
    db.flush()
    _refresh_preview(db, pkg)
    db.commit()


# ------------------------------------------------------------------ workflow
def _ensure_source_approved(apv: RoadmapActionPlanVersion) -> None:
    if apv.status != "APPROVED":
        raise _bad(f"Action Plan nguồn không còn APPROVED (hiện {apv.status})", 409)


def submit_review(db: Session, user: User, package_id: int) -> RoadmapDecisionPackage:
    pkg = get_package(db, package_id)
    if pkg.status != "DRAFT":
        raise _bad(f"Chỉ chuyển UNDER_REVIEW từ DRAFT (hiện {pkg.status})", 409)
    apv, plan = _ctx(db, pkg)
    _ensure_scenario_open(db, plan)
    _ensure_source_approved(apv)
    if not ap.version_items(db, apv.id):
        raise _bad("Package cần ít nhất 1 Action Plan item", 409)
    for b in package_bindings(db, pkg.id):  # đóng băng snapshot evidence + chi tiết máy tại thời điểm freeze (evidence RETIRED => sẽ UNPRICED, không freeze thành priced)
        e = db.get(RoadmapCostEvidence, b.evidence_id)
        item = db.get(RoadmapActionPlanItem, b.action_item_id)
        mt = (((item.snapshot_json or {}).get("lineage") or {}).get("rule") or {}).get("machine_type_code") if item.proposal_type == "MACHINE_PURCHASE" else None
        b.snapshot_json = {"evidence": rc.evidence_snapshot(e), "details": binding_details(db, mt, b.machine_model_id, b.future_candidate_id) if mt else None}
    db.flush()
    pkg.package_json = build_package(db, pkg, frozen=True)
    pkg.package_fingerprint = _hash(pkg.package_json)
    pkg.status, pkg.reviewed_by, pkg.reviewed_at = "UNDER_REVIEW", user.username, utcnow()
    rm._hist(db, "DEC_PACKAGE", pkg.id, "DRAFT", "UNDER_REVIEW", "", user.username)
    db.commit()
    write_audit("ROADMAP_DECISION_PACKAGE_REVIEW", user=user, object_type="RoadmapDecisionPackage", object_id=pkg.package_code, detail=pkg.package_fingerprint)
    return pkg


def verify(db: Session, pkg: RoadmapDecisionPackage) -> list[str]:
    """Verify từ SNAPSHOT (không đọc evidence/giá sống): fingerprint + tái định giá từng line + tái tổng hợp."""
    errs = []
    pj = pkg.package_json or {}
    if _hash(pj) != pkg.package_fingerprint:
        errs.append("package_fingerprint không khớp package_json")
    apv, _plan = _ctx(db, pkg)
    milestones = pj.get("milestones", [])
    items = {i.id: i for i in ap.version_items(db, apv.id)}
    bsnap = {b.action_item_id: (b.snapshot_json or {}).get("evidence") for b in package_bindings(db, pkg.id)}
    lines = []
    for ln in pj.get("selected_actions", []) + pj.get("unresolved_actions", []):
        item = items.get(ln["item_id"])
        if item is None:
            errs.append(f"item#{ln['item_id']} không còn trong Action Plan")
            continue
        again = evaluate_line(item, bsnap.get(item.id), milestones)
        keep = ("cost_class", "cost_status", "cost_status_reason", "amount", "unit_cost", "currency", "cost_period", "price_basis", "milestone_bucket", "warnings")
        if any(again[k] != ln[k] for k in keep):
            errs.append(f"item#{item.id}: định giá tính lại từ snapshot không khớp package")
        lines.append(again)
    for ln in lines:
        if ln["cost_status"] == "PRICED" and (ln["evidence"] or {}).get("status_at_snapshot") != "APPROVED":
            errs.append(f"item#{ln['item_id']}: priced bằng evidence không APPROVED")
    if summarize(lines, milestones) != pj.get("direct_cost_summary"):
        errs.append("direct_cost_summary không khớp tổng hợp lại từ snapshot")
    return errs


def approve(db: Session, user: User, package_id: int) -> RoadmapDecisionPackage:
    """Quyền `roadmap.approve` do API kiểm."""
    pkg = get_package(db, package_id)
    if pkg.status != "UNDER_REVIEW":
        raise _bad(f"Chỉ duyệt được package UNDER_REVIEW (hiện {pkg.status})", 409)
    if not pkg.reviewed_by or pkg.reviewed_by == user.username:
        raise _bad("Four-eyes: người duyệt (approver) phải khác người đã đưa vào review (reviewer)", 409)
    apv, plan = _ctx(db, pkg)
    _ensure_scenario_open(db, plan)
    _ensure_source_approved(apv)
    errs = verify(db, pkg)
    if errs:
        raise _bad("Snapshot/fingerprint verify thất bại: " + "; ".join(errs), 409)
    pkg.status, pkg.approved_by, pkg.approved_at = "APPROVED", user.username, utcnow()
    rm._hist(db, "DEC_PACKAGE", pkg.id, "UNDER_REVIEW", "APPROVED", "", user.username)
    db.commit()
    write_audit("ROADMAP_DECISION_PACKAGE_APPROVE", user=user, object_type="RoadmapDecisionPackage", object_id=pkg.package_code, detail="không thực thi mua/tuyển")
    return pkg


def archive(db: Session, user: User, package_id: int, reason: str = "") -> RoadmapDecisionPackage:
    pkg = get_package(db, package_id)
    if pkg.status != "APPROVED":
        raise _bad(f"Chỉ ARCHIVED từ APPROVED (hiện {pkg.status})", 409)
    if not (reason or "").strip():
        raise _bad("Archive bắt buộc có reason")
    pkg.status, pkg.archive_reason = "ARCHIVED", reason.strip()[:300]
    rm._hist(db, "DEC_PACKAGE", pkg.id, "APPROVED", "ARCHIVED", reason.strip(), user.username)
    db.commit()
    write_audit("ROADMAP_DECISION_PACKAGE_ARCHIVE", user=user, object_type="RoadmapDecisionPackage", object_id=pkg.package_code, detail=reason[:150])
    return pkg


# ------------------------------------------------------------------ compare (không ranking / cheapest / winner)
def compare(db: Session, a_id: int, b_id: int) -> dict:
    a, b = get_package(db, a_id), get_package(db, b_id)
    (va, pa), (vb, pb) = _ctx(db, a), _ctx(db, b)
    if pa.id != pb.id and pa.scenario_version_id != pb.scenario_version_id:
        raise _bad("Chỉ so sánh package cùng Action Plan family hoặc cùng scenario_version_id", 409)
    ja, jb = effective_package_json(db, a), effective_package_json(db, b)  # DRAFT => live preview; còn lại => frozen

    def cov(j):
        return {(t["milestone_code"], t["metric_code"], t["period_label"], t["scope_type"], t["scope_value"]): {"original_gap": t["original_gap"], "overall_combined_status": t["overall_combined_status"],
                                                                                                                 "coverage_by_proposal_type": {k: {x: v[x] for x in ("planned_increment", "remaining_gap", "status")} for k, v in t["coverage_by_proposal_type"].items()},
                                                                                                                 "has_unresolved_actions": t["has_unresolved_actions"]} for t in j.get("targets", [])}

    def acts(j):
        return {(x["proposal_type"], x["source_milestone_code"], x["planned_effective_date"], x["inclusion_status"]): {"selected_quantity": x["selected_quantity"], "cost_status": x["cost_status"], "amount": x["amount"],
                                                                                                                    "currency": x["currency"], "cost_period": x["cost_period"], "evidence": (x["evidence"] or {}).get("evidence_code") and f"{x['evidence']['evidence_code']}@v{x['evidence']['evidence_version']}"}
                for x in j.get("selected_actions", []) + j.get("unresolved_actions", [])}

    ca, cb, aa, ab = cov(ja), cov(jb), acts(ja), acts(jb)
    sa, sb = ja.get("direct_cost_summary", {}), jb.get("direct_cost_summary", {})
    return {
        "a": package_view(db, a, detail=False), "b": package_view(db, b, detail=False),
        "lineage": {"a": {"action_plan_version_id": va.id, "source_run_id": va.source_run_id, "source_run_fingerprint": va.source_run_fingerprint, "package_fingerprint": a.package_fingerprint},
                    "b": {"action_plan_version_id": vb.id, "source_run_id": vb.source_run_id, "source_run_fingerprint": vb.source_run_fingerprint, "package_fingerprint": b.package_fingerprint}},
        "same_source_run": va.source_run_id == vb.source_run_id,
        "targets": [{"key": dict(zip(("milestone_code", "metric_code", "period_label", "scope_type", "scope_value"), k)), "a": ca.get(k), "b": cb.get(k), "changed": ca.get(k) != cb.get(k)} for k in sorted(set(ca) | set(cb))],
        "actions": [{"proposal_type": k[0], "source_milestone_code": k[1], "planned_effective_date": k[2], "inclusion_status": k[3], "a": aa.get(k), "b": ab.get(k), "changed": aa.get(k) != ab.get(k)}
                    for k in sorted(set(aa) | set(ab))],
        "machine_capex": {"a": sa.get("MACHINE_CAPEX", []), "b": sb.get("MACHINE_CAPEX", [])},
        "labor_recurring_cost": {"a": sa.get("LABOR_RECURRING_COST", []), "b": sb.get("LABOR_RECURRING_COST", [])},
        "unpriced_actions": {"a": sa.get("UNPRICED_ACTIONS", []), "b": sb.get("UNPRICED_ACTIONS", [])},
        "completeness": {"a": ja.get("completeness"), "b": jb.get("completeness")}, "warning_codes": {"a": ja.get("warning_codes", []), "b": jb.get("warning_codes", [])},
        "evidence_versions": {"a": [f"{e['evidence_code']}@v{e['evidence_version']}" for e in ja.get("cost_evidence_used", [])], "b": [f"{e['evidence_code']}@v{e['evidence_version']}" for e in jb.get("cost_evidence_used", [])]},
    }  # không rank/score/cheapest/best/winner/recommendation
