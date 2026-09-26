"""Roadmap Simulation engine (Task 5 — Issue #11): baseline snapshot -> gap -> proposal framework. KHÔNG có optimizer.

Nguyên tắc đã chốt (GPT Issue #11):
- Run CHỈ trên version READY/REVIEWED (khóa từ READY); Run IMMUTABLE, snapshot đầy đủ; cùng input => trả run cũ (no-op).
- gap = effective_target - baseline (không clamp). INCREMENT: effective_target = baseline + increment. Không đổi unit ngầm.
- Thiếu/không khớp => trạng thái minh bạch (NEEDS_INPUT / MISSING_BASELINE / UNIT_MISMATCH / SCOPE_MISMATCH / PARTIAL_SOURCE), KHÔNG fallback.
- Proposal: chỉ THỰC THI khi có executable rule APPROVED (Task 6, allowlist LABOR/MACHINE_GAP_REQUIREMENT_V1 — INCREMENTAL GAP, không total requirement,
  không trừ available, không quy đổi period, productivity do business khai báo). Không có rule hiệu lực => NEEDS_INPUT (không quantity).
  Rule metadata (Task 5) vẫn chỉ là registry, không thực thi. CAPACITY_CHANGE luôn NEEDS_INPUT; TECHNOLOGY_ADOPTION chỉ link/snapshot evidence;
  revenue gap KHÔNG suy ra labor/machine/capacity; không rank/score, không auto SELECTED.
- Fingerprint = version inputs + baseline VALUES + source identity + rule versions + tech/evidence + resource baselines; timestamp/sync_run_id
  chỉ là evidence (không vào hash).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import User
from app.models.future_technology import FutureTechnologyCandidate, FutureTechnologyEvidence
from app.models.roadmap import (
    CANONICAL_UNITS,
    PROPOSAL_DECISIONS,
    PROPOSAL_TYPES,
    RUNNABLE_VERSION_STATUSES,
    RoadmapProposal,
    RoadmapProposalDecisionHistory,
    RoadmapRule,
    RoadmapRun,
    RoadmapRunTargetResult,
    RoadmapScenario,
    RoadmapScenarioVersion,
)
from app.models.technology_process import TechnologyProcess, TechnologyProcessVersion
from app.services import roadmap as rm
from app.services import roadmap_adapters as ad
from app.services import roadmap_baseline as rb
from app.services import roadmap_exec_rules as xr
from app.services.audit import write_audit

log = logging.getLogger("dvt.roadmap")
ENGINE_VERSION = "RM_ENGINE_V2"  # V2 (Task 6): executable adapter LABOR/MACHINE_GAP_REQUIREMENT_V1 (incremental gap)


def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def _hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")).hexdigest()[:40]


# ------------------------------------------------------------------ evaluate một target
def evaluate_target(db: Session, v: RoadmapScenarioVersion, ms, t) -> dict:
    plabel = rb.period_label(t.period_type, t.period_year, t.period_month)
    if t.baseline_ref_year is not None:
        blabel = rb.period_label(t.period_type, t.baseline_ref_year, t.baseline_ref_month)
        by, bm = t.baseline_ref_year, t.baseline_ref_month
    else:
        blabel, by, bm = plabel, t.period_year, t.period_month
    res = {
        "target_id": t.id, "milestone_code": ms.code, "milestone_date": ms.target_date, "metric_code": t.metric_code, "target_kind": t.target_kind,
        "target_value": t.target_value, "increment_value": None, "effective_target": None, "unit": t.unit, "scope_type": t.scope_type, "scope_value": t.scope_value,
        "period_label": plabel, "baseline_basis": t.baseline_basis, "baseline_period_label": blabel,
        "output_definition": "PACK_QTY" if t.metric_code == "OUTPUT_QTY" else None, "baseline_value": None, "baseline_unit": CANONICAL_UNITS[t.metric_code], "gap": None,
        "result_status": "NEEDS_INPUT", "source_identity_json": {}, "source_meta_json": {}, "data_quality_flags_json": [], "missing_inputs_json": [], "completeness": "INCOMPLETE",
        "period_type": t.period_type, "note": t.note,
    }
    if not t.baseline_basis:
        res["missing_inputs_json"] = ["baseline_basis (bắt buộc, explicit)"]
        return res
    if (t.scope_type, t.scope_value) != (v.scope_type, v.scope_value):  # không auto-rollup/drilldown
        res.update(result_status="SCOPE_MISMATCH", data_quality_flags_json=["SCOPE_MISMATCH"],
                   missing_inputs_json=[f"Target scope {t.scope_type}/{t.scope_value or '-'} khác scope scenario {v.scope_type}/{v.scope_value or '-'}"])
        return res
    if t.unit != CANONICAL_UNITS[t.metric_code]:  # không convert alias/FX
        res.update(result_status="UNIT_MISMATCH", data_quality_flags_json=["UNIT_MISMATCH"],
                   missing_inputs_json=[f"Target unit '{t.unit}' khác canonical '{CANONICAL_UNITS[t.metric_code]}' của {t.metric_code} — không quy đổi"])
        return res

    b = rb.baseline_for(db, t.metric_code, t.baseline_basis, t.period_type, by, bm, t.scope_type, t.scope_value)
    res.update(source_identity_json=b["identity"], source_meta_json={**b["source_meta"], "diagnostics": b["diagnostics"]},
               data_quality_flags_json=list(dict.fromkeys(b["flags"])), missing_inputs_json=b["missing_inputs"])
    if b["status"] != "OK":
        res["result_status"] = b["status"]
        return res
    base = float(b["value"])
    res["baseline_value"], res["baseline_unit"] = base, b["unit"]
    if t.target_kind == "INCREMENT":
        res["increment_value"], res["effective_target"] = t.target_value, base + t.target_value
    else:
        res["effective_target"] = t.target_value
    res["gap"] = res["effective_target"] - base  # không clamp
    res["result_status"], res["completeness"] = "CALCULATED", "COMPLETE"
    return res


# ------------------------------------------------------------------ technology snapshot (link + evidence summary, không sinh số)
def technology_snapshot(db: Session, v: RoadmapScenarioVersion) -> list[dict]:
    out = []
    for k in rm.version_links(db, v.id):
        if k.link_type == "FUTURE_CANDIDATE":
            c = db.get(FutureTechnologyCandidate, k.ref_id)
            if c is None:
                out.append({"type": k.link_type, "ref_id": k.ref_id, "missing": True})
                continue
            ev = db.query(FutureTechnologyEvidence).filter_by(candidate_id=c.id).order_by(FutureTechnologyEvidence.id).all()
            out.append({"type": k.link_type, "ref_id": c.id, "code": c.candidate_code, "status": c.status, "machine_type_code": c.machine_type_code, "automation_level": c.automation_level,
                        "evidence_count": len(ev),
                        "evidence": [{"id": e.id, "basis": e.basis, "metric_code": e.metric_code, "value": e.value, "unit": e.unit, "source_kind": e.source_kind,
                                      "source_ref": e.source_ref, "evidence_date": _iso(e.evidence_date)} for e in ev]})
        else:
            pv = db.get(TechnologyProcessVersion, k.ref_id)
            if pv is None:
                out.append({"type": k.link_type, "ref_id": k.ref_id, "missing": True})
                continue
            p = db.get(TechnologyProcess, pv.technology_process_id)
            out.append({"type": k.link_type, "ref_id": pv.id, "code": p.process_code if p else "", "layer": pv.layer, "status": pv.status, "sam_status": pv.sam_status,
                        "total_sam_minutes": pv.total_sam_minutes, "generation_fingerprint": pv.generation_fingerprint})
    return out


def _approved_rules(db: Session) -> list[RoadmapRule]:
    return db.query(RoadmapRule).filter(RoadmapRule.approval_status == "APPROVED").order_by(RoadmapRule.rule_code, RoadmapRule.rule_version).all()


def _rule_snapshot(r: RoadmapRule) -> dict:
    """Snapshot metadata của rule APPROVED (đi vào fingerprint + snapshot run). KHÔNG dùng để tính số."""
    return {"rule_code": r.rule_code, "rule_version": r.rule_version, "proposal_type": r.proposal_type, "formula_type": r.formula_type, "formula_description": r.formula_description,
            "parameters": r.parameters_json or {}, "machine_type_code": r.machine_type_code, "basis_note": r.basis_note, "executable": False}


# ------------------------------------------------------------------ proposals
def _tech_refs(tech: list[dict]) -> list[dict]:
    return [{"type": t["type"], "ref_id": t["ref_id"], "code": t.get("code"), "status": t.get("status"), "evidence_count": t.get("evidence_count"), "missing": t.get("missing", False)} for t in tech]


def _proposal(r: dict, ptype: str, status: str, rationale: str, *, quantity=None, unit="", rule: RoadmapRule | None = None, inputs=None, refs=None, missing=None, completeness="INCOMPLETE") -> dict:
    return {"result_key": (r["milestone_code"], r["metric_code"], r["period_label"], r["target_id"]), "milestone_code": r["milestone_code"], "proposal_type": ptype, "scope_type": r["scope_type"],
            "scope_value": r["scope_value"], "quantity": quantity, "unit": unit, "rationale": rationale[:500], "calculation_rule_code": rule.rule_code if rule else None,
            "calculation_rule_version": f"{rule.rule_code}@v{rule.rule_version}" if rule else "NONE", "input_snapshot_json": inputs or {}, "evidence_refs_json": refs or [],
            "missing_inputs_json": missing or [], "completeness": completeness, "calc_status": status}


def _capacity_impact(gap: float, out: dict, period_type: str) -> dict:
    """Task 6: baseline/resulting capacity = NULL (chưa có relation được duyệt); KHÔNG utilization/bottleneck."""
    return {"requirement_basis": ad.REQUIREMENT_BASIS, "capacity_unit": "sp", "period_type": period_type, "gap_output": gap, "baseline_capacity": None,
            "proposed_increment": out["proposed_increment"], "resulting_capacity": None, "remaining_gap": out["remaining_gap_after_proposal"], "completeness": "PARTIAL",
            "note": "baseline/resulting capacity chưa xác định: chưa có approved relation giữa available resource và baseline output"}


def _exec_lines(r: dict, pt: str, xrules: list, labor: dict | None, machine_avail: dict) -> list[dict] | None:
    """Mỗi executable rule APPROVED (scope exact, hiệu lực tại milestone.target_date) = một dòng; không tie-break/rank. None nếu không có rule nào liên quan."""
    scope = (r["scope_type"], r["scope_value"])
    cand = [x for x in xrules if x.proposal_type == pt and (x.scope_type, x.scope_value) == scope and xr.is_effective(x, r["milestone_date"])]
    if not cand:
        return None
    out: list[dict] = []
    for x in cand:
        a = ad.get_adapter(x.adapter_code)
        ref = {"type": "EXECUTABLE_RULE", "rule_code": x.rule_code, "rule_version": x.rule_version, "adapter_code": x.adapter_code, "adapter_version": x.adapter_version,
               "source_kind": x.source_kind, "source_ref": x.source_ref}
        if a.needs_machine_type:
            av = machine_avail.get(x.machine_type_code)
            avail_val = av["available_machines"] if av else None
            avail_missing = f"available machines (machine_capacities ACTIVE, loại máy {x.machine_type_code}, scope {r['scope_type']}/{r['scope_value'] or 'TOTAL'})"
        else:
            av = labor
            avail_val = labor["total_labor"] if labor else None
            avail_missing = "available labor (labor_standards ACTIVE theo scope)"
        snap = {"gap": r["gap"], "gap_unit": "sp", "period_type": r["period_type"], "available_baseline": av, "executable_rule": xr.snapshot(x), "requirement_basis": ad.REQUIREMENT_BASIS}
        missing: list[str] = []
        if x.period_type != r["period_type"]:
            snap["flags"] = ["PERIOD_MISMATCH"]
            missing.append(f"PERIOD_MISMATCH: rule {x.rule_code}@v{x.rule_version} khai productivity theo {x.period_type} nhưng target theo {r['period_type']} — không quy đổi period; cần rule đúng {r['period_type']}")
        if avail_val is None:
            missing.append(avail_missing)
        if missing:
            out.append(_proposal(r, pt, "NEEDS_INPUT", f"Rule {x.rule_code}@v{x.rule_version} hiệu lực nhưng thiếu/lệch input: {'; '.join(missing)}", rule=x, inputs=snap,
                                 refs=[ref], missing=missing, completeness="PARTIAL"))
            continue
        inp = {"gap_output": r["gap"], "gap_unit": "sp", "period_type": r["period_type"], a.productivity_key: x.productivity_value, "productivity_unit": x.productivity_unit,
               a.available_key: avail_val}
        if a.needs_machine_type:
            inp["machine_type_code"] = x.machine_type_code
        try:
            res = a.run(inp)
        except ad.AdapterInputError as e:
            snap["adapter_error"] = {"code": e.code, "message": str(e)}
            out.append(_proposal(r, pt, "NEEDS_INPUT", f"Rule {x.rule_code}@v{x.rule_version}: input không hợp lệ cho adapter ({e.code}): {e}", rule=x, inputs=snap, refs=[ref],
                                 missing=[f"{e.code}: {e}"], completeness="PARTIAL"))
            continue
        snap["adapter_input"], snap["adapter_output"] = inp, res
        snap["capacity_impact"] = _capacity_impact(r["gap"], res, r["period_type"])
        qty = res["additional_machines" if a.needs_machine_type else "additional_labor"]
        out.append(_proposal(r, pt, "CALCULATED",
                             f"{x.adapter_code}: CEIL({r['gap']:g} / {x.productivity_value:g}) = {qty} {a.resource} tăng thêm để bù gap (INCREMENTAL_GAP; không phải tổng nhu cầu; available chỉ là context).",
                             quantity=float(qty), unit=a.resource, rule=x, inputs=snap, refs=[ref], missing=[], completeness="COMPLETE"))
    return out


def relevant_exec_rules(xrules: list, results: list[dict]) -> list:
    """Chỉ rule có thể ảnh hưởng >=1 proposal của run: OUTPUT_QTY CALCULATED gap>0, scope exact, hiệu lực tại milestone.target_date (period lệch vẫn relevant vì tạo dòng NEEDS_INPUT)."""
    live = [r for r in results if r["metric_code"] == "OUTPUT_QTY" and r["result_status"] == "CALCULATED" and r["gap"] is not None and r["gap"] > 0]
    return [x for x in xrules if any((x.scope_type, x.scope_value) == (r["scope_type"], r["scope_value"]) and xr.is_effective(x, r["milestone_date"]) for r in live)]


def build_proposals(r: dict, tech: list[dict], rules: list[RoadmapRule], labor: dict | None, machine: dict | None, xrules: list | None = None,
                    machine_avail: dict | None = None) -> list[dict]:
    out: list[dict] = []
    trefs = _tech_refs(tech)
    tech_missing = ["approved technology impact formula (Task 5 không dùng claimed evidence thành numeric uplift)"] + ([] if tech else ["chưa liên kết Future Technology / Technology Process nào"])

    def tech_prop(prefix: str = "") -> dict:
        return _proposal(r, "TECHNOLOGY_ADOPTION", "NEEDS_INPUT", f"{prefix}Chỉ link/snapshot evidence; chưa có approved formula để tính tác động số.",
                         refs=trefs, missing=tech_missing, inputs={"linked_technology": tech}, completeness="PARTIAL" if tech else "INCOMPLETE")

    if r["result_status"] != "CALCULATED":
        for pt in PROPOSAL_TYPES:
            if pt == "TECHNOLOGY_ADOPTION":
                out.append(tech_prop(f"Gap chưa xác định ({r['result_status']}). "))
            else:
                out.append(_proposal(r, pt, "NEEDS_INPUT", f"Gap của target chưa tính được ({r['result_status']}) nên chưa có căn cứ đề xuất.",
                                     missing=[f"target gap unresolved: {r['result_status']}", *r["missing_inputs_json"]]))
        return out
    if r["gap"] <= 0:
        for pt in PROPOSAL_TYPES:
            out.append(_proposal(r, pt, "NOT_APPLICABLE", f"Gap = {r['gap']:g} <= 0: target đã đạt/vượt baseline, không cần đề xuất.", inputs={"gap": r["gap"]}, completeness="COMPLETE"))
        return out

    if r["metric_code"] == "REVENUE":  # BR-510: không suy revenue <-> nguồn lực
        for pt in ("LABOR_RECRUITMENT", "MACHINE_PURCHASE", "CAPACITY_CHANGE"):
            out.append(_proposal(r, pt, "NOT_APPLICABLE", "Không suy nguồn lực từ revenue gap khi chưa có approved price/revenue-per-unit rule.", inputs={"gap": r["gap"], "unit": "USD"}, completeness="COMPLETE"))
        out.append(tech_prop())
        return out

    # OUTPUT_QTY, gap dương — Task 5 KHÔNG có executable calculation adapter nào: LABOR/MACHINE luôn NEEDS_INPUT, không quantity
    for pt, baseline, bname in (("LABOR_RECRUITMENT", labor, "labor_standards"), ("MACHINE_PURCHASE", machine, "machine_capacities")):
        lines = _exec_lines(r, pt, xrules or [], labor, machine_avail or {})
        if lines is not None:  # có executable rule hiệu lực => các dòng thực thi thay cho dòng metadata
            out.extend(lines)
            continue
        cand = [x for x in rules if x.proposal_type == pt]
        base_inputs = {"gap": r["gap"], "gap_unit": "sp", "available_baseline": baseline}
        if not cand:
            out.append(_proposal(r, pt, "NEEDS_INPUT", f"Chưa có executable rule {pt} nào APPROVED, đúng scope và còn hiệu lực tại {r['milestone_date']} — không tự bịa công thức.",
                                 missing=["executable rule APPROVED (đúng scope, hiệu lực tại milestone.target_date)", "productivity do business khai báo & duyệt"], inputs=base_inputs))
            continue
        for rule in cand:  # mỗi rule APPROVED (metadata) = một dòng, KHÔNG thực thi, KHÔNG chọn/rank
            out.append(_proposal(r, pt, "NEEDS_INPUT",
                                 f"Rule {rule.rule_code}@v{rule.rule_version} chỉ APPROVED ở mức metadata (không thực thi). Cần executable rule riêng được duyệt, đúng scope và còn hiệu lực.",
                                 rule=rule, inputs={**base_inputs, "rule": _rule_snapshot(rule)}, refs=[{"type": "RULE", "rule_code": rule.rule_code, "rule_version": rule.rule_version, "basis_note": rule.basis_note}],
                                 missing=[f"executable rule APPROVED (đúng scope, hiệu lực) — rule {rule.rule_code}@v{rule.rule_version} chỉ là metadata"], completeness="PARTIAL"))
    out.append(_proposal(r, "CAPACITY_CHANGE", "NEEDS_INPUT", "Chưa có approved capacity-change rule; không diễn giải thành đổi ca/OT/tuyển người/mua máy.",
                         missing=["approved capacity-change rule"], inputs={"gap": r["gap"], "unit": "sp"}))
    out.append(tech_prop())
    return out


# ------------------------------------------------------------------ run
def _canonical_result(r: dict) -> dict:
    return {k: r[k] for k in ("milestone_code", "milestone_date", "metric_code", "target_kind", "target_value", "unit", "scope_type", "scope_value", "period_label", "baseline_basis",
                              "baseline_period_label", "result_status", "baseline_value", "effective_target", "gap", "source_identity_json")}


def _core_tech(tech: list[dict]) -> list[dict]:
    return tech  # snapshot đã chỉ chứa giá trị nghiệp vụ (không timestamp)


def run_simulation(db: Session, user: User, version_id: int) -> dict:
    v = rm.get_version(db, version_id)
    s = db.get(RoadmapScenario, v.scenario_id)
    if s.status == "ARCHIVED":
        raise HTTPException(409, "Scenario đã ARCHIVED — không chạy simulation")
    if v.status not in RUNNABLE_VERSION_STATUSES:
        raise HTTPException(409, f"Chỉ chạy simulation trên version {RUNNABLE_VERSION_STATUSES} (hiện {v.status}) — DRAFT chưa khóa inputs nên không reproducible")

    ms_list = rm.version_milestones(db, v.id)
    results: list[dict] = []
    version_snap = {"scenario_code": s.scenario_code, "scenario_name": s.name, "version_id": v.id, "version_no": v.version_no, "version_status": v.status, "scope_type": v.scope_type,
                    "scope_value": v.scope_value, "locked_at": _iso(v.locked_at), "milestones": []}
    for m in ms_list:
        tl = rm.milestone_targets(db, m.id)
        version_snap["milestones"].append({"code": m.code, "name": m.name, "target_date": _iso(m.target_date), "sequence": m.sequence, "note": m.note,
                                           "targets": [rm.target_view(t) for t in tl]})
        for t in tl:
            results.append(evaluate_target(db, v, m, t))

    tech = technology_snapshot(db, v)
    rules = _approved_rules(db)
    labor, machine = rb.labor_baseline(db, v.scope_type, v.scope_value), rb.machine_baseline(db, v.scope_type, v.scope_value)
    xrules = relevant_exec_rules(xr.approved_rules(db), results)
    machine_avail = {mt: rb.machine_available(db, v.scope_type, v.scope_value, mt) for mt in sorted({x.machine_type_code for x in xrules if x.machine_type_code})}
    proposals: list[dict] = []
    for r in results:
        proposals.extend(build_proposals(r, tech, rules, labor, machine, xrules, machine_avail))

    fp_types = set(machine_avail) | {x.machine_type_code for x in rules if x.machine_type_code}  # loại máy của rule relevant (executable) + rule metadata APPROVED
    fingerprint = _hash({
        "engine": ENGINE_VERSION,
        "scope": [v.scope_type, v.scope_value],
        "results": [_canonical_result(r) for r in results],
        "technology": _core_tech(tech),
        "rules": [_rule_snapshot(x) for x in rules],
        # machine baseline chỉ tính loại máy thuộc rule relevant (tồn kho loại máy không liên quan không được làm đổi run); phần hiển thị vẫn nằm trong snapshot
        "resources": {"labor": labor, "machine": {"by_machine_type": {t: n for t, n in ((machine or {}).get("by_machine_type") or {}).items() if t in fp_types}}},
        "executable_rules": [xr.snapshot(x) for x in xrules],
        "machine_availability": machine_avail,
    })
    existing = db.query(RoadmapRun).filter_by(version_id=v.id, run_fingerprint=fingerprint).first()
    if existing:
        return {"created": False, "run": run_view(db, existing)}

    flags = sorted({f for r in results for f in r["data_quality_flags_json"]})
    if flags:
        log.warning("ROADMAP_RUN_SOURCE_WARNINGS version=%s user=%s flags=%s", v.id, user.username, ",".join(flags))
    counts: dict[str, int] = {}
    for r in results:
        counts[r["result_status"]] = counts.get(r["result_status"], 0) + 1
    pcounts: dict[str, int] = {}
    for p in proposals:
        pcounts[p["calc_status"]] = pcounts.get(p["calc_status"], 0) + 1
    calculated = counts.get("CALCULATED", 0)
    completeness = "COMPLETE" if results and calculated == len(results) else ("PARTIAL" if calculated else "INCOMPLETE")
    snapshot = {
        "engine_version": ENGINE_VERSION, "version": version_snap, "source_freshness": rb.source_freshness(db), "data_quality_flags": flags,
        "resource_baselines": {"labor": labor, "machine": machine, "capacity_definitions_note": "capacity_definitions chỉ tham chiếu, KHÔNG cộng thô thành baseline (guardrail Issue #11)"},
        "technology_links": tech, "approved_rules": [_rule_snapshot(x) for x in rules],
        "executable_rules": [xr.snapshot(x) for x in xrules], "machine_availability": machine_avail, "missing_inputs": sorted({m for r in results for m in r["missing_inputs_json"]}),
    }
    summary = {"completeness": completeness, "target_result_counts": counts, "proposal_status_counts": pcounts, "target_count": len(results), "proposal_count": len(proposals), "data_quality_flags": flags}

    try:
        last = db.query(RoadmapRun).filter_by(version_id=v.id).order_by(RoadmapRun.run_no.desc()).first()
        run = RoadmapRun(version_id=v.id, run_no=(last.run_no + 1 if last else 1), run_fingerprint=fingerprint, status="COMPLETED", engine_version=ENGINE_VERSION,
                         snapshot_json=snapshot, summary_json=summary, created_by=user.username)
        db.add(run)
        db.flush()
        rows: dict[tuple, RoadmapRunTargetResult] = {}
        for r in results:
            row = RoadmapRunTargetResult(run_id=run.id, **{k: r[k] for k in (
                "target_id", "milestone_code", "milestone_date", "metric_code", "target_kind", "target_value", "increment_value", "effective_target", "unit", "scope_type",
                "scope_value", "period_label", "baseline_basis", "baseline_period_label", "output_definition", "baseline_value", "baseline_unit", "gap", "result_status",
                "source_identity_json", "source_meta_json", "data_quality_flags_json", "missing_inputs_json", "completeness")})
            db.add(row)
            db.flush()
            rows[(r["milestone_code"], r["metric_code"], r["period_label"], r["target_id"])] = row
        for p in proposals:
            tr = rows.get(p["result_key"])
            db.add(RoadmapProposal(run_id=run.id, target_result_id=tr.id if tr else None, **{k: p[k] for k in (
                "milestone_code", "proposal_type", "scope_type", "scope_value", "quantity", "unit", "rationale", "calculation_rule_code", "calculation_rule_version",
                "input_snapshot_json", "evidence_refs_json", "missing_inputs_json", "completeness", "calc_status")}))
        db.commit()
    except IntegrityError:
        db.rollback()
        again = db.query(RoadmapRun).filter_by(version_id=v.id, run_fingerprint=fingerprint).first()
        if again:
            return {"created": False, "run": run_view(db, again)}
        raise HTTPException(409, "Trùng run do request đồng thời — thử lại") from None
    except Exception:
        db.rollback()
        log.exception("ROADMAP_RUN_FAILED version=%s user=%s", v.id, user.username)
        raise
    write_audit("ROADMAP_RUN", user=user, object_type="RoadmapRun", object_id=str(run.id), detail=f"{s.scenario_code} v{v.version_no} run#{run.run_no} {completeness}")
    return {"created": True, "run": run_view(db, run)}


# ------------------------------------------------------------------ views / history / compare
def result_view(x: RoadmapRunTargetResult) -> dict:
    return {
        "id": x.id, "target_id": x.target_id, "milestone_code": x.milestone_code, "milestone_date": _iso(x.milestone_date), "metric_code": x.metric_code, "target_kind": x.target_kind,
        "target_value": x.target_value, "increment_value": x.increment_value, "effective_target": x.effective_target, "unit": x.unit, "scope_type": x.scope_type, "scope_value": x.scope_value,
        "period_label": x.period_label, "baseline_basis": x.baseline_basis, "baseline_period_label": x.baseline_period_label, "output_definition": x.output_definition,
        "baseline_value": x.baseline_value, "baseline_unit": x.baseline_unit, "gap": x.gap, "result_status": x.result_status, "source_identity": x.source_identity_json,
        "source_meta": x.source_meta_json, "data_quality_flags": x.data_quality_flags_json, "missing_inputs": x.missing_inputs_json, "completeness": x.completeness,
    }


def proposal_view(p: RoadmapProposal) -> dict:
    return {
        "id": p.id, "run_id": p.run_id, "target_result_id": p.target_result_id, "milestone_code": p.milestone_code, "proposal_type": p.proposal_type, "scope_type": p.scope_type,
        "scope_value": p.scope_value, "quantity": p.quantity, "unit": p.unit, "rationale": p.rationale, "calculation_rule_code": p.calculation_rule_code,
        "calculation_rule_version": p.calculation_rule_version, "input_snapshot": p.input_snapshot_json, "evidence_refs": p.evidence_refs_json, "missing_inputs": p.missing_inputs_json,
        "completeness": p.completeness, "calc_status": p.calc_status, "status": p.decision_status or p.calc_status, "decision_status": p.decision_status,
        "calculation": (p.input_snapshot_json or {}).get("adapter_output"), "capacity_impact": (p.input_snapshot_json or {}).get("capacity_impact"),
        "decision_reason": p.decision_reason, "decision_by": p.decision_by, "decision_at": _iso(p.decision_at),
    }


def run_view(db: Session, run: RoadmapRun, detail: bool = True) -> dict:
    out = {"id": run.id, "version_id": run.version_id, "run_no": run.run_no, "run_fingerprint": run.run_fingerprint, "status": run.status, "engine_version": run.engine_version,
           "summary": run.summary_json, "created_by": run.created_by, "created_at": _iso(run.created_at)}
    if detail:
        out["snapshot"] = run.snapshot_json
        out["results"] = [result_view(x) for x in db.query(RoadmapRunTargetResult).filter_by(run_id=run.id).order_by(RoadmapRunTargetResult.id).all()]
        out["proposals"] = [proposal_view(p) for p in db.query(RoadmapProposal).filter_by(run_id=run.id).order_by(RoadmapProposal.id).all()]
    return out


def get_run(db: Session, run_id: int) -> RoadmapRun:
    r = db.get(RoadmapRun, run_id)
    if r is None:
        raise HTTPException(404, "Không tìm thấy Roadmap Run")
    return r


def list_runs(db: Session, version_id: int) -> list[RoadmapRun]:
    rm.get_version(db, version_id)
    return db.query(RoadmapRun).filter_by(version_id=version_id).order_by(RoadmapRun.run_no.desc()).all()


def compare_runs(db: Session, run_a_id: int, run_b_id: int) -> dict:
    a, b = get_run(db, run_a_id), get_run(db, run_b_id)
    ra = {(x.milestone_code, x.metric_code, x.period_label, x.baseline_basis or ""): x for x in db.query(RoadmapRunTargetResult).filter_by(run_id=a.id).all()}
    rb_ = {(x.milestone_code, x.metric_code, x.period_label, x.baseline_basis or ""): x for x in db.query(RoadmapRunTargetResult).filter_by(run_id=b.id).all()}
    rows = []
    for key in sorted(set(ra) | set(rb_)):
        x, y = ra.get(key), rb_.get(key)
        rows.append({"milestone_code": key[0], "metric_code": key[1], "period_label": key[2], "baseline_basis": key[3] or None,
                     "a": {"baseline": x.baseline_value, "effective_target": x.effective_target, "gap": x.gap, "status": x.result_status} if x else None,
                     "b": {"baseline": y.baseline_value, "effective_target": y.effective_target, "gap": y.gap, "status": y.result_status} if y else None,
                     "changed": (x is None) != (y is None) or (x is not None and (x.baseline_value, x.effective_target, x.gap, x.result_status) != (y.baseline_value, y.effective_target, y.gap, y.result_status))})
    pa = {(p.milestone_code, p.proposal_type, p.calculation_rule_version): p for p in db.query(RoadmapProposal).filter_by(run_id=a.id).all()}
    pb = {(p.milestone_code, p.proposal_type, p.calculation_rule_version): p for p in db.query(RoadmapProposal).filter_by(run_id=b.id).all()}
    props = [{"milestone_code": k[0], "proposal_type": k[1], "rule": k[2], "a": ({"status": pa[k].calc_status, "quantity": pa[k].quantity} if k in pa else None),
              "b": ({"status": pb[k].calc_status, "quantity": pb[k].quantity} if k in pb else None)} for k in sorted(set(pa) | set(pb))]
    # KHÔNG có ranking/score/"best plan"
    return {"run_a": run_view(db, a, detail=False), "run_b": run_view(db, b, detail=False), "targets": rows, "proposals": props}


# ------------------------------------------------------------------ proposal decision (SELECTED / REJECTED, thủ công, không thực thi)
def decide_proposal(db: Session, user: User, proposal_id: int, decision: str, reason: str) -> RoadmapProposal:
    p = db.get(RoadmapProposal, proposal_id)
    if p is None:
        raise HTTPException(404, "Không tìm thấy proposal")
    if decision not in PROPOSAL_DECISIONS:
        raise HTTPException(422, f"decision phải là một trong {PROPOSAL_DECISIONS}")
    if not (reason or "").strip():
        raise HTTPException(422, "Chọn/loại proposal bắt buộc có reason")
    if p.decision_status == decision:
        raise HTTPException(409, f"Proposal đã ở trạng thái {decision}")
    run = get_run(db, p.run_id)
    s = db.get(RoadmapScenario, rm.get_version(db, run.version_id).scenario_id)
    if s.status == "ARCHIVED":
        raise HTTPException(409, "Scenario đã ARCHIVED")
    frm = p.decision_status or p.calc_status
    now = utcnow()
    p.decision_status, p.decision_reason, p.decision_by, p.decision_at = decision, reason.strip()[:300], user.username, now  # nội dung proposal KHÔNG đổi
    db.add(RoadmapProposalDecisionHistory(proposal_id=p.id, from_status=frm, to_status=decision, reason=reason.strip()[:300], actor=user.username, at=now))
    db.commit()
    write_audit("ROADMAP_PROPOSAL_DECISION", user=user, object_type="RoadmapProposal", object_id=str(p.id), detail=f"{p.proposal_type} {frm} -> {decision} (không thực thi procurement/recruitment/capacity)")
    return p


def proposal_history(db: Session, proposal_id: int) -> list[dict]:
    if db.get(RoadmapProposal, proposal_id) is None:
        raise HTTPException(404, "Không tìm thấy proposal")
    rows = db.query(RoadmapProposalDecisionHistory).filter_by(proposal_id=proposal_id).order_by(RoadmapProposalDecisionHistory.id).all()
    return [{"id": h.id, "from_status": h.from_status, "to_status": h.to_status, "reason": h.reason, "actor": h.actor, "at": _iso(h.at)} for h in rows]
