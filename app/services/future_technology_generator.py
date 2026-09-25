"""Future Technology Proposal Generator (Task 4 — Issue #9, GPT APPROVED_TO_IMPLEMENT 2026-09-25).

Quyết định đã chốt (Issue #9 review):
- Source layer CHỈ CURRENT_PROCESS hoặc OPTIMIZED_CURRENT_TECHNOLOGY; source status ∈ DRAFT/SIMULATED/REVIEWED/APPROVED, chặn RETIRED;
  không FUTURE -> FUTURE. Target đúng FUTURE_TECHNOLOGY, DRAFT-only, source_type=TECHNOLOGY_SCOUTING.
- Selectable: DISCOVERED/UNDER_REVIEW = preview-only; TRIAL = user chọn tay (USER_SELECTED_UNVERIFIED_CANDIDATE), không auto;
  APPROVED_FOR_FUTURE = selectable, auto-apply CHỈ khi đúng 1 candidate eligible + compatibility APPROVED; REJECTED/INACTIVE loại hẳn.
  Nhiều eligible => MULTIPLE_CANDIDATES, không tie-break.
- KHÔNG áp bất kỳ thay đổi numeric nào (SAM/cycle/output/operator/labor/machine quantity/utilization/bottleneck). Evidence numeric chỉ
  lưu + hiển thị + fingerprint/evidence trace.
- Substitution: set machine_type_code (+ machine_model_id nếu candidate có link), change_type luôn MACHINE_SUBSTITUTION; copy
  automation_level của candidate nếu có giá trị rõ (mô tả, không phải numeric); automation delta ghi trong Generation Evidence.
- Atomic MỘT transaction (dùng lại helper flush-only của Task 1/3). Idempotent qua generation_fingerprint (rule FUT_GEN_V1).
- Generation Evidence snapshot candidate/status/evidence summary tại thời điểm generate (không chỉ hash).
- Compare dùng endpoint riêng, verify direct lineage; không nới guard compare Task 3.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import User
from app.models.future_technology import FutureTechnologyCandidate, FutureTechnologyCompatibility, FutureTechnologyEvidence
from app.models.resources import MachineModel, MachineType
from app.models.technology_process import TechnologyProcessVersion
from app.services import technology_process_service as tps
from app.services.audit import write_audit
from app.services.technology_process_generator import _canon_val, _hash_json, _source_snapshot, _validate_selections

log = logging.getLogger(__name__)

FUTURE_RULE_VERSION = "FUT_GEN_V1"
ALLOWED_SOURCE_LAYERS = ("CURRENT_PROCESS", "OPTIMIZED_CURRENT_TECHNOLOGY")
TARGET_LAYER = "FUTURE_TECHNOLOGY"
SELECTABLE_STATUSES = ("TRIAL", "APPROVED_FOR_FUTURE")
PREVIEW_ONLY_STATUSES = ("DISCOVERED", "UNDER_REVIEW")
EXCLUDED_STATUSES = ("REJECTED", "INACTIVE")


def _check_source(src: TechnologyProcessVersion) -> None:
    if src.layer not in ALLOWED_SOURCE_LAYERS:
        raise HTTPException(422, f"Source version phải thuộc layer {ALLOWED_SOURCE_LAYERS} (không cho FUTURE -> FUTURE)")
    if src.status == "RETIRED":
        raise HTTPException(409, "Source version đã RETIRED — không dùng làm nguồn tạo Future Technology proposal")


def _root_current_version_id(db: Session, src: TechnologyProcessVersion) -> int | None:
    v, hops = src, 0
    while v is not None and hops < 10:
        if v.layer == "CURRENT_PROCESS":
            return v.id
        v = db.get(TechnologyProcessVersion, v.derived_from_version_id) if v.derived_from_version_id else None
        hops += 1
    return None


# ------------------------------------------------------------------ candidate lookup (chỉ đọc)
def _structure_ok(db: Session, cand: FutureTechnologyCandidate) -> bool:
    """MachineType ACTIVE; nếu có model liên kết thì model tồn tại, không REJECTED và đúng loại máy."""
    mt = db.get(MachineType, cand.machine_type_code)
    if mt is None or mt.status != "ACTIVE":
        return False
    if cand.machine_model_id is not None:
        mm = db.get(MachineModel, cand.machine_model_id)
        if mm is None or mm.status == "REJECTED" or mm.machine_type_code != cand.machine_type_code:
            return False
    return True


def _evidence_rows(db: Session, candidate_id: int) -> list[FutureTechnologyEvidence]:
    return db.query(FutureTechnologyEvidence).filter_by(candidate_id=candidate_id).order_by(FutureTechnologyEvidence.id).all()


def _entry(db: Session, comp: FutureTechnologyCompatibility, cand: FutureTechnologyCandidate) -> dict:
    mt = db.get(MachineType, cand.machine_type_code)
    mm = db.get(MachineModel, cand.machine_model_id) if cand.machine_model_id else None
    ev = _evidence_rows(db, cand.id)
    selectable = cand.status in SELECTABLE_STATUSES
    return {
        "compatibility_id": comp.id, "compatibility_status": comp.compatibility_status,
        "candidate_id": cand.id, "candidate_code": cand.candidate_code, "candidate_status": cand.status,
        "machine_type_code": cand.machine_type_code, "machine_type_status": mt.status if mt else None,
        "machine_model_id": cand.machine_model_id, "machine_model_status": mm.status if mm else None,
        "brand": cand.brand, "model_name": cand.model_name, "technology_name": cand.technology_name, "automation_level": cand.automation_level,
        "selectable": selectable, "auto_eligible": selectable and cand.status == "APPROVED_FOR_FUTURE" and comp.compatibility_status == "APPROVED" and len(ev) > 0,  # cần evidence (PR #10 review mục 1)
        "evidence_count": len(ev),
        "evidence": [{"id": e.id, "source_kind": e.source_kind, "basis": e.basis, "metric_code": e.metric_code, "value": e.value, "unit": e.unit,
                      "evidence_date": _canon_val(e.evidence_date), "source_ref": e.source_ref} for e in ev],
    }


def _entries_for_operation(db: Session, op) -> list[dict]:
    """Candidate thấy được cho operation: compat khớp operation_code + scope source machine, compat không REJECTED, candidate không
    REJECTED/INACTIVE, cấu trúc (MachineType/model) hợp lệ. DISCOVERED/UNDER_REVIEW vẫn hiện nhưng selectable=False (preview-only)."""
    code = (op.operation_code or "").strip()
    if not code:
        return []
    rows = (
        db.query(FutureTechnologyCompatibility)
        .filter(FutureTechnologyCompatibility.operation_code == code, FutureTechnologyCompatibility.compatibility_status != "REJECTED")
        .order_by(FutureTechnologyCompatibility.id)
        .all()
    )
    out = []
    for r in rows:
        if r.source_machine_type_code is not None and r.source_machine_type_code != op.machine_type_code:
            continue
        cand = db.get(FutureTechnologyCandidate, r.candidate_id)
        if cand is None or cand.status in EXCLUDED_STATUSES or not _structure_ok(db, cand):
            continue
        out.append(_entry(db, r, cand))
    return out


def _decide(op, entries: list[dict]) -> tuple[str, dict | None]:
    if op.machine_type_code is None or not (op.operation_code or "").strip():
        return "UNCHANGED", None  # MAN / chưa map catalog -> không tra cứu
    selectable = [e for e in entries if e["selectable"]]
    eligible = [e for e in selectable if e["auto_eligible"]]
    if len(eligible) == 1:
        return "MACHINE_SUBSTITUTION", eligible[0]
    if len(eligible) > 1:
        return "MULTIPLE_CANDIDATES", None  # BR-411 — không tie-break
    if len(selectable) == 1:
        return "UNVERIFIED_CANDIDATE_AVAILABLE", None
    if len(selectable) > 1:
        return "MULTIPLE_CANDIDATES", None
    return "UNCHANGED", None  # không có candidate selectable (kể cả chỉ có DISCOVERED/UNDER_REVIEW preview-only)


# ------------------------------------------------------------------ Preview (KHÔNG ghi gì)
def preview_future_proposal(db: Session, source_version_id: int) -> dict:
    src = tps.get_version(db, source_version_id)
    _check_source(src)
    rows = []
    for op in sorted((o for o in src.operations if o.is_active), key=lambda o: o.sequence_no):
        entries = _entries_for_operation(db, op)
        decision, auto = _decide(op, entries)
        rows.append({
            "sequence_no": op.sequence_no, "operation_code": op.operation_code, "operation_name": op.operation_name,
            "current_machine_type_code": op.machine_type_code, "current_machine_model_id": op.machine_model_id, "current_automation_level": op.automation_level,
            "decision": decision, "auto_compatibility_id": auto["compatibility_id"] if auto else None, "candidates": entries,
        })
    return {"source_version_id": src.id, "source_layer": src.layer, "source_status": src.status, "operations": rows}


# ------------------------------------------------------------------ fingerprint (source + rule + candidate + evidence + compat + selections)
def _scoped_compat_rows(db: Session, active_ops: list) -> list[FutureTechnologyCompatibility]:
    """Cùng scope với _entries_for_operation (operation_code + source machine); giữ cả row REJECTED/candidate REJECTED trong scope vì
    đổi status của chính chúng có thể làm eligibility đổi về sau (bài học Task 3 review round 2)."""
    allowed: dict[str, set] = {}
    for o in active_ops:
        code = (o.operation_code or "").strip()
        if code:
            allowed.setdefault(code, set()).add(o.machine_type_code)
    if not allowed:
        return []
    rows = (
        db.query(FutureTechnologyCompatibility)
        .filter(FutureTechnologyCompatibility.operation_code.in_(sorted(allowed)))
        .order_by(FutureTechnologyCompatibility.id)
        .all()
    )
    return [r for r in rows if r.source_machine_type_code is None or r.source_machine_type_code in allowed.get(r.operation_code, set())]


def _snapshots(db: Session, active_ops: list) -> tuple[list[dict], list[dict], list[dict]]:
    rows = _scoped_compat_rows(db, active_ops)
    compat_snap = [
        {"id": r.id, "candidate_id": r.candidate_id, "operation_code": r.operation_code, "source_machine_type_code": r.source_machine_type_code,
         "compatibility_status": r.compatibility_status, "evidence_ref": r.evidence_ref, "evidence_note": r.evidence_note}
        for r in rows
    ]
    cand_ids = sorted({r.candidate_id for r in rows})
    cand_snap, ev_snap = [], []
    for cid in cand_ids:
        c = db.get(FutureTechnologyCandidate, cid)
        if c is None:
            continue
        mt = db.get(MachineType, c.machine_type_code)
        mm = db.get(MachineModel, c.machine_model_id) if c.machine_model_id else None
        cand_snap.append({
            "id": c.id, "candidate_code": c.candidate_code, "machine_type_code": c.machine_type_code, "machine_model_id": c.machine_model_id,
            "brand": c.brand, "model_name": c.model_name, "technology_name": c.technology_name, "automation_level": c.automation_level, "status": c.status,
            "machine_type_status": mt.status if mt else None, "machine_model_status": mm.status if mm else None,
            "machine_model_type_code": mm.machine_type_code if mm else None,
        })
        for e in _evidence_rows(db, cid):
            ev_snap.append({
                "id": e.id, "candidate_id": e.candidate_id, "source_ref": e.source_ref, "source_kind": e.source_kind, "basis": e.basis, "metric_code": e.metric_code,
                "value": e.value, "unit": e.unit, "evidence_date": _canon_val(e.evidence_date), "note": e.note,
            })
    return compat_snap, cand_snap, ev_snap


def compute_future_fingerprint(db: Session, src: TechnologyProcessVersion, decisions: list[dict], selections: dict) -> tuple[str, dict]:
    active_ops = sorted((o for o in src.operations if o.is_active), key=lambda o: o.sequence_no)
    compat_snap, cand_snap, ev_snap = _snapshots(db, active_ops)
    hashes = {
        "source_snapshot_hash": _hash_json(_source_snapshot(src)), "compatibility_snapshot_hash": _hash_json(compat_snap),
        "candidate_snapshot_hash": _hash_json(cand_snap), "evidence_snapshot_hash": _hash_json(ev_snap),
    }
    payload = {"source_version_id": src.id, "source_layer": src.layer, "generator_rule_version": FUTURE_RULE_VERSION, **hashes,
               "decisions": decisions, "selections": selections or {}}
    return _hash_json(payload), hashes


# ------------------------------------------------------------------ Generate (ghi thật, atomic MỘT transaction)
def generate_future_proposal(db: Session, user: User, source_version_id: int, selections: dict[str, int] | None = None) -> dict:
    """selections: {str(sequence_no): FutureTechnologyCompatibility id} — chọn tường minh. Không chọn = giữ UNCHANGED (trừ auto duy nhất)."""
    src = tps.get_version(db, source_version_id)
    _check_source(src)
    active_ops = sorted((o for o in src.operations if o.is_active), key=lambda o: o.sequence_no)
    selections = _validate_selections(active_ops, selections)

    decisions: list[dict] = []
    chosen_entries: dict[int, tuple[dict, bool]] = {}  # sequence_no -> (entry, user_selected)
    for op in active_ops:
        entries = _entries_for_operation(db, op)
        decision, auto = _decide(op, entries)
        chosen, user_selected = auto, False
        sel_id = selections.get(str(op.sequence_no))
        if sel_id is not None:
            match = next((e for e in entries if e["compatibility_id"] == sel_id), None)
            if match is None:
                raise HTTPException(422, f"Future compatibility id {sel_id} không hợp lệ cho operation seq {op.sequence_no}")
            if not match["selectable"]:
                raise HTTPException(422, f"Candidate {match['candidate_code']} đang {match['candidate_status']} — chỉ preview, chưa được chọn (cần TRIAL hoặc APPROVED_FOR_FUTURE)")
            chosen, user_selected, decision = match, True, "MACHINE_SUBSTITUTION"
        if chosen is not None:
            chosen_entries[op.sequence_no] = (chosen, user_selected)
        decisions.append({
            "sequence_no": op.sequence_no, "operation_code": op.operation_code, "decision": decision,
            "chosen_compatibility_id": chosen["compatibility_id"] if chosen else None,
            "chosen_candidate_id": chosen["candidate_id"] if chosen else None,
            "chosen_candidate_code": chosen["candidate_code"] if chosen else None,
            "chosen_candidate_status": chosen["candidate_status"] if chosen else None,
            "chosen_compatibility_status": chosen["compatibility_status"] if chosen else None,
            "chosen_auto_eligible": chosen["auto_eligible"] if chosen else None,
            "user_selected": user_selected,
            "candidates_considered": entries,  # snapshot đầy đủ candidate/status/evidence summary tại thời điểm generate
        })

    fp, hashes = compute_future_fingerprint(db, src, decisions, selections)
    existing = (
        db.query(TechnologyProcessVersion)
        .filter(TechnologyProcessVersion.derived_from_version_id == src.id, TechnologyProcessVersion.layer == TARGET_LAYER, TechnologyProcessVersion.generation_fingerprint == fp)
        .first()
    )
    if existing:
        return {"created": False, "version": tps.version_view(existing, with_operations=True)}

    try:
        p = tps.get_process(db, src.technology_process_id)
        new_v = tps._build_draft_version_flush(db, user, p, {
            "layer": TARGET_LAYER, "source_type": "TECHNOLOGY_SCOUTING", "source_ref": f"Generated from version #{src.id} ({src.layer})",
            "derived_from_version_id": src.id, "note": "",
        })
        cloned = tps._clone_operations_flush(db, user, src, new_v)
        by_seq = {o.sequence_no: o for o in cloned}
        automation_deltas: list[dict] = []

        for seq, (entry, user_selected) in sorted(chosen_entries.items()):
            new_op = by_seq[seq]
            new_op.machine_type_code = entry["machine_type_code"]
            new_op.machine_model_id = entry["machine_model_id"]
            new_op.change_type = "MACHINE_SUBSTITUTION"  # giữ nguyên classification kể cả khi đổi cả automation (GPT chốt)
            after = (entry["automation_level"] or "").strip()
            if after:
                if after != (new_op.automation_level or ""):
                    automation_deltas.append({"sequence_no": seq, "before": new_op.automation_level or "", "after": after})
                new_op.automation_level = after
            unverified = user_selected and not entry["auto_eligible"]
            note = f"FutureTechnologyCandidate#{entry['candidate_code']}/compat#{entry['compatibility_id']} -> {entry['machine_type_code']}"
            if entry["machine_model_id"]:
                note += f"/model#{entry['machine_model_id']}"
            if unverified:
                note += " (USER_SELECTED_UNVERIFIED_CANDIDATE)"
            new_op.evidence_note = note[:300]
            new_op.evidence_ref = f"FutureTechnologyCandidate#{entry['candidate_code']}"
        for o in cloned:
            if o.change_type is None:
                o.change_type = "UNCHANGED"
        # BR-409 — KHÔNG đụng sam/cycle/output/operator/labor/quantity: giữ nguyên giá trị đã clone từ baseline.

        new_v.total_sam_minutes, new_v.sam_status = tps._sam_summary(cloned)
        new_v.generation_fingerprint = fp
        new_v.assumptions_json = {
            "generator_rule_version": FUTURE_RULE_VERSION, "generated_at": utcnow().isoformat(), "generated_by": user.username,
            "source_version_id": src.id, "source_layer": src.layer, "source_status": src.status,
            "root_current_version_id": _root_current_version_id(db, src), "generation_fingerprint": fp, **hashes,
            "numeric_performance_applied": False,  # Task 4 không có formula duyệt — evidence numeric chỉ lưu/hiển thị (BR-409/410)
            "sam_status": new_v.sam_status,
            "metric_completeness": {
                "total_sam_minutes": new_v.sam_status,
                "expected_output_per_day": "N/A", "required_labor": "N/A", "machine_quantity": "N/A", "bottleneck": "N/A", "utilization": "N/A",
                "setup_changeover_minutes": "AVAILABLE" if cloned and all(o.setup_changeover_minutes is not None for o in cloned) else "N/A",
            },
            "automation_deltas": automation_deltas, "decisions": decisions, "selections": selections,
        }
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(new_v)
    write_audit("FUTURE_PROPOSAL_GENERATE", user=user, object_type="TechnologyProcessVersion", object_id=str(new_v.id), detail=f"from version #{src.id} ({src.layer}) -> {TARGET_LAYER}")
    return {"created": True, "version": tps.version_view(new_v, with_operations=True)}


# ------------------------------------------------------------------ Compare baseline vs Future (endpoint riêng, direct lineage)
def compare_with_baseline(db: Session, future_version_id: int) -> dict:
    vb = tps.get_version(db, future_version_id)
    if not vb.derived_from_version_id:
        raise HTTPException(422, "Version này không có lineage (derived_from_version_id) để so sánh")
    return compare_baseline_vs_future(db, vb.derived_from_version_id, future_version_id)


def compare_baseline_vs_future(db: Session, baseline_id: int, future_id: int) -> dict:
    va, vb = tps.get_version(db, baseline_id), tps.get_version(db, future_id)
    if va.technology_process_id != vb.technology_process_id:
        raise HTTPException(422, "Chỉ so sánh được các version của cùng một Technology Process")
    if va.layer not in ALLOWED_SOURCE_LAYERS:
        raise HTTPException(422, f"Baseline phải thuộc layer {ALLOWED_SOURCE_LAYERS}")
    if vb.layer != TARGET_LAYER:
        raise HTTPException(422, f"Version so sánh phải thuộc layer {TARGET_LAYER}")
    if vb.derived_from_version_id != va.id:
        raise HTTPException(422, "Future version không được derive trực tiếp từ baseline này — chỉ so với đúng baseline nguồn của nó")

    ops_a = {o.sequence_no: o for o in va.operations if o.is_active}
    ops_b = {o.sequence_no: o for o in vb.operations if o.is_active}
    machine_changes, automation_changes = [], 0
    for seq, ob in sorted(ops_b.items()):
        oa = ops_a.get(seq)
        if oa is None:
            continue
        if (oa.machine_type_code, oa.machine_model_id) != (ob.machine_type_code, ob.machine_model_id):
            machine_changes.append({"sequence_no": seq, "before": {"machine_type_code": oa.machine_type_code, "machine_model_id": oa.machine_model_id},
                                    "after": {"machine_type_code": ob.machine_type_code, "machine_model_id": ob.machine_model_id}})
        if (oa.automation_level or "") != (ob.automation_level or ""):
            automation_changes += 1  # field-delta, không phụ thuộc change_type (GPT chốt)

    assumptions = vb.assumptions_json or {}
    ev_rows = []
    for d in assumptions.get("decisions", []):
        if d.get("chosen_candidate_id") is None:
            continue
        cons = next((c for c in d.get("candidates_considered", []) if c.get("compatibility_id") == d.get("chosen_compatibility_id")), {})
        bases = sorted({e["basis"] for e in cons.get("evidence", [])})
        ev_rows.append({
            "sequence_no": d["sequence_no"], "candidate_code": d.get("chosen_candidate_code"), "candidate_status": d.get("chosen_candidate_status"),
            "evidence_count": cons.get("evidence_count", 0), "bases": bases, "has_observed_or_trialed": bool({"OBSERVED", "TRIALED"} & set(bases)),
            "approved_for_future": d.get("chosen_candidate_status") == "APPROVED_FOR_FUTURE", "user_selected": d.get("user_selected", False),
        })
    unknown = [k for k, v in (assumptions.get("metric_completeness") or {}).items() if v in ("N/A", "INCOMPLETE", "EMPTY")]
    return {
        "version_a": tps.version_view(va), "version_b": tps.version_view(vb),
        "baseline_layer": va.layer,
        "operation_changed_count": sum(1 for o in ops_b.values() if o.change_type and o.change_type != "UNCHANGED"),
        "machine_substitution_count": sum(1 for o in ops_b.values() if o.change_type == "MACHINE_SUBSTITUTION"),
        "automation_change_count": automation_changes,
        "machine_config_changes": machine_changes,
        "machine_count": "NOT_AVAILABLE",  # operation không có số lượng máy — không tính giả
        "total_sam_minutes": {"a": va.total_sam_minutes, "b": vb.total_sam_minutes},
        "sam_status": {"a": va.sam_status, "b": vb.sam_status},
        "required_labor": {"a": va.required_labor, "b": vb.required_labor},
        "expected_output_per_day": {"a": va.expected_output_per_day, "b": vb.expected_output_per_day},
        "bottleneck": "N/A", "utilization": "N/A",
        "unknown_or_incomplete_metrics": unknown,
        "evidence_completeness": {"substituted_operations": ev_rows,
                                  "all_substitutions_have_evidence": all(r["evidence_count"] > 0 for r in ev_rows) if ev_rows else None},
    }
