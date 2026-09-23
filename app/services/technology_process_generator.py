"""Optimized Current Technology Proposal Generator (Task 3 — Issue #7, GPT APPROVED_TO_IMPLEMENT 2026-09-23).

Nguyên tắc đã chốt:
- BR-301: Layer 2 luôn derive từ 1 TechnologyProcessVersion nguồn layer=CURRENT_PROCESS (lineage qua derived_from_version_id).
- BR-302/V-303: generator chỉ tạo DRAFT, không auto REVIEWED/APPROVED.
- BR-303/BR-312/V-306: KHÔNG tự bịa SAM/cycle/output/operator khi substitution — luôn copy giá trị hiện tại
  (thường null) trừ khi có rule mapping riêng được duyệt (chưa có trong Task 3).
- BR-307/308/309: candidate chỉ lấy từ `OperationMachineCompatibility` (mapping quản trị mới) + `MachineModel`,
  KHÔNG suy đoán theo tên. Auto-apply CHỈ khi compatibility_status=APPROVED VÀ (candidate model rỗng nghĩa là
  type-level + MachineType active) HOẶC (candidate model có + model.status IN (APPROVED, TRIAL)).
- review vòng khảo sát mục 2: nếu >1 candidate đủ điều kiện ngang nhau -> KHÔNG tự chọn (MULTIPLE_CANDIDATES),
  chờ user chọn tường minh qua `selections` khi generate.
- review mục 3: MachineModel.status=CANDIDATE hiển thị nhưng không tự áp; nếu user chủ động chọn, operation vẫn
  MACHINE_SUBSTITUTION nhưng evidence đánh dấu USER_SELECTED_UNVERIFIED_CANDIDATE, version vẫn chỉ DRAFT.
- review mục 5: KHÔNG dùng chung bootstrap_fingerprint — dùng cột riêng `generation_fingerprint`, hash canonical
  snapshot THỰC TẾ của source operations (không chỉ id/bootstrap_fingerprint nguồn) + rule version + compatibility
  snapshot liên quan + lựa chọn người dùng.
- review mục 7: KHÔNG gọi `derive_version()` public trực tiếp (không atomic — 1 transaction duy nhất, dùng lại
  helper flush-only `_build_draft_version_flush`/`_clone_operations_flush` đã tách từ Task 1).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import User
from app.models.resources import MachineModel, MachineType
from app.models.tech_compatibility import OperationMachineCompatibility
from app.models.technology_process import TechnologyProcessVersion
from app.services import technology_process_service as tps
from app.services.audit import write_audit

log = logging.getLogger(__name__)

GENERATOR_RULE_VERSION = "OCT_GEN_V1"
DECISION_STATES = ("UNCHANGED", "MACHINE_SUBSTITUTION", "MULTIPLE_CANDIDATES", "UNVERIFIED_CANDIDATE_AVAILABLE")


# ------------------------------------------------------------------ candidate lookup (chỉ đọc)
def _candidates_for_operation(db: Session, operation_code: str, current_machine_type_code: str | None) -> list[OperationMachineCompatibility]:
    if not operation_code:
        return []
    rows = (
        db.query(OperationMachineCompatibility)
        .filter(OperationMachineCompatibility.operation_code == operation_code, OperationMachineCompatibility.compatibility_status != "REJECTED")
        .all()
    )
    return [r for r in rows if r.source_machine_type_code is None or r.source_machine_type_code == current_machine_type_code]


def _is_eligible(db: Session, row: OperationMachineCompatibility) -> bool:
    if row.compatibility_status != "APPROVED":
        return False
    if row.candidate_machine_model_id is None:
        mt = db.get(MachineType, row.candidate_machine_type_code)
        return mt is not None and mt.status == "ACTIVE"
    mm = db.get(MachineModel, row.candidate_machine_model_id)
    return mm is not None and mm.status in ("APPROVED", "TRIAL")


def _decide(db: Session, op, candidates: list[OperationMachineCompatibility]) -> tuple[str, OperationMachineCompatibility | None]:
    """Trả (decision, auto_candidate|None). auto_candidate chỉ có khi decision=MACHINE_SUBSTITUTION tự động
    (đúng 1 candidate đủ điều kiện) — MULTIPLE_CANDIDATES/UNVERIFIED_CANDIDATE_AVAILABLE cần user chọn."""
    if op.machine_type_code is None or not (op.operation_code or "").strip():
        return "UNCHANGED", None  # MAN/không có máy, hoặc operation_code rỗng (chưa map catalog) -> không tra cứu
    eligible = [c for c in candidates if _is_eligible(db, c)]
    if len(eligible) == 1:
        return "MACHINE_SUBSTITUTION", eligible[0]
    if len(eligible) > 1:
        return "MULTIPLE_CANDIDATES", None
    if len(candidates) == 1:
        return "UNVERIFIED_CANDIDATE_AVAILABLE", None
    if len(candidates) > 1:
        return "MULTIPLE_CANDIDATES", None
    return "UNCHANGED", None


def _candidate_out(db: Session, row: OperationMachineCompatibility) -> dict:
    mm = db.get(MachineModel, row.candidate_machine_model_id) if row.candidate_machine_model_id else None
    return {
        "id": row.id, "candidate_machine_type_code": row.candidate_machine_type_code, "candidate_machine_model_id": row.candidate_machine_model_id,
        "machine_model_status": mm.status if mm else None, "compatibility_status": row.compatibility_status,
        "evidence_ref": row.evidence_ref, "evidence_note": row.evidence_note, "eligible": _is_eligible(db, row),
    }


# ------------------------------------------------------------------ Preview (KHÔNG ghi gì)
def preview_optimized_proposal(db: Session, source_version_id: int) -> dict:
    src = tps.get_version(db, source_version_id)
    if src.layer != "CURRENT_PROCESS":
        raise HTTPException(422, "Source version phải thuộc layer CURRENT_PROCESS")  # V-301

    rows = []
    for op in sorted((o for o in src.operations if o.is_active), key=lambda o: o.sequence_no):
        candidates = _candidates_for_operation(db, op.operation_code, op.machine_type_code)
        decision, auto = _decide(db, op, candidates)
        rows.append({
            "sequence_no": op.sequence_no, "operation_code": op.operation_code, "operation_name": op.operation_name,
            "current_machine_type_code": op.machine_type_code, "current_machine_model_id": op.machine_model_id,
            "decision": decision, "auto_candidate_id": auto.id if auto else None,
            "candidates": [_candidate_out(db, c) for c in candidates],
        })
    return {"source_version_id": src.id, "source_layer": src.layer, "operations": rows}


# ------------------------------------------------------------------ fingerprint (review mục 5)
def _canon_val(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


_OP_SNAPSHOT_FIELDS = (
    "sequence_no", "operation_code", "operation_name", "machine_type_code", "machine_model_id", "operator_count", "helper_count",
    "sam_minutes", "cycle_time_seconds", "expected_output_per_day", "automation_level", "setup_changeover_minutes", "expected_defect_rate",
)


def compute_generation_fingerprint(src: TechnologyProcessVersion, decisions: list[dict], selections: dict) -> str:
    ops_snapshot = [
        {f: _canon_val(getattr(o, f)) for f in _OP_SNAPSHOT_FIELDS}
        for o in sorted((o for o in src.operations if o.is_active), key=lambda o: o.sequence_no)
    ]
    payload = {
        "source_version_id": src.id, "source_layer": src.layer, "source_operations": ops_snapshot,
        "generator_rule_version": GENERATOR_RULE_VERSION, "decisions": decisions, "selections": selections or {},
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


# ------------------------------------------------------------------ Generate (ghi thật, atomic MỘT transaction)
def generate_optimized_proposal(db: Session, user: User, source_version_id: int, selections: dict[str, int] | None = None) -> dict:
    """selections: {str(sequence_no): compatibility_row_id} — lựa chọn tường minh của user cho operation đang
    MULTIPLE_CANDIDATES/UNVERIFIED_CANDIDATE_AVAILABLE. Không truyền = giữ UNCHANGED cho các operation đó."""
    src = tps.get_version(db, source_version_id)
    if src.layer != "CURRENT_PROCESS":
        raise HTTPException(422, "Source version phải thuộc layer CURRENT_PROCESS")  # V-301
    selections = selections or {}

    active_ops = sorted((o for o in src.operations if o.is_active), key=lambda o: o.sequence_no)
    decisions: list[dict] = []
    for op in active_ops:
        candidates = _candidates_for_operation(db, op.operation_code, op.machine_type_code)
        decision, auto = _decide(db, op, candidates)
        chosen = auto
        user_selected = False
        sel_id = selections.get(str(op.sequence_no))
        if sel_id is not None:
            match = next((c for c in candidates if c.id == sel_id), None)
            if match is None:
                raise HTTPException(422, f"Candidate id {sel_id} không hợp lệ cho operation seq {op.sequence_no}")  # V-304/V-305
            chosen, user_selected, decision = match, True, "MACHINE_SUBSTITUTION"
        decisions.append({
            "sequence_no": op.sequence_no, "operation_code": op.operation_code, "decision": decision,
            "chosen_candidate_id": chosen.id if chosen else None,
            "chosen_compatibility_status": chosen.compatibility_status if chosen else None,
            "user_selected": user_selected,
        })

    fp = compute_generation_fingerprint(src, decisions, selections)

    # V-308 / BR-316 — same source + rule + mapping snapshot + selections -> no-op, không tạo duplicate
    existing = (
        db.query(TechnologyProcessVersion)
        .filter(TechnologyProcessVersion.derived_from_version_id == src.id, TechnologyProcessVersion.layer == "OPTIMIZED_CURRENT_TECHNOLOGY", TechnologyProcessVersion.generation_fingerprint == fp)
        .first()
    )
    if existing:
        return {"created": False, "version": tps.version_view(existing, with_operations=True)}

    try:
        p = tps.get_process(db, src.technology_process_id)
        new_v = tps._build_draft_version_flush(db, user, p, {
            "layer": "OPTIMIZED_CURRENT_TECHNOLOGY", "source_type": "AUTO_GENERATED",
            "source_ref": f"Generated from version #{src.id}", "derived_from_version_id": src.id, "note": "",
        })
        cloned_ops = tps._clone_operations_flush(db, user, src, new_v)
        by_seq = {o.sequence_no: o for o in cloned_ops}

        for dec in decisions:
            new_op = by_seq[dec["sequence_no"]]
            if dec["chosen_candidate_id"] is None:
                new_op.change_type = "UNCHANGED"
                continue
            cand = db.get(OperationMachineCompatibility, dec["chosen_candidate_id"])
            new_op.machine_type_code = cand.candidate_machine_type_code
            new_op.machine_model_id = cand.candidate_machine_model_id
            new_op.change_type = "MACHINE_SUBSTITUTION"
            # BR-312/V-306: KHÔNG tự tính sam/cycle/operator từ MachineModel — giữ nguyên giá trị đã copy từ source
            # "unverified" phải dựa trên eligibility THẬT (gồm cả MachineModel.status), không chỉ compatibility_status —
            # candidate có compatibility_status=APPROVED nhưng MachineModel còn CANDIDATE vẫn là chưa kiểm chứng.
            unverified = dec["user_selected"] and not _is_eligible(db, cand)
            note = f"OperationMachineCompatibility#{cand.id} -> {cand.candidate_machine_type_code}"
            if cand.candidate_machine_model_id:
                note += f"/model#{cand.candidate_machine_model_id}"
            if unverified:
                note += " (USER_SELECTED_UNVERIFIED_CANDIDATE)"
            new_op.evidence_note = note[:300]
            new_op.evidence_ref = f"OperationMachineCompatibility#{cand.id}"

        new_v.total_sam_minutes, new_v.sam_status = tps._sam_summary(cloned_ops)
        new_v.generation_fingerprint = fp
        new_v.assumptions_json = {
            "generator_rule_version": GENERATOR_RULE_VERSION, "generated_at": utcnow().isoformat(), "generated_by": user.username,
            "source_version_id": src.id, "generation_fingerprint": fp, "decisions": decisions, "selections": selections,
        }
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(new_v)
    write_audit("TECH_PROCESS_OPTIMIZED_GENERATE", user=user, object_type="TechnologyProcessVersion", object_id=str(new_v.id), detail=f"from version #{src.id} (CURRENT_PROCESS) -> OPTIMIZED_CURRENT_TECHNOLOGY")
    return {"created": True, "version": tps.version_view(new_v, with_operations=True)}


def compare_with_source(db: Session, optimized_version_id: int) -> dict:
    """So sánh 1 version Optimized với đúng version Current Process đã derive ra nó (không cần truyền tay 2 id)."""
    vb = tps.get_version(db, optimized_version_id)
    if not vb.derived_from_version_id:
        raise HTTPException(422, "Version này không có lineage (derived_from_version_id) để so sánh")
    return compare_current_vs_optimized(db, vb.derived_from_version_id, optimized_version_id)


# ------------------------------------------------------------------ Compare (mục 7 Issue #7)
def compare_current_vs_optimized(db: Session, version_a_id: int, version_b_id: int) -> dict:
    va = tps.get_version(db, version_a_id)
    vb = tps.get_version(db, version_b_id)
    if va.technology_process_id != vb.technology_process_id:
        raise HTTPException(422, "Chỉ so sánh được các version của cùng một Technology Process")
    ops_b = [o for o in vb.operations if o.is_active]
    return {
        "version_a": tps.version_view(va), "version_b": tps.version_view(vb),
        "operation_changed_count": sum(1 for o in ops_b if o.change_type and o.change_type != "UNCHANGED"),
        "machine_substitution_count": sum(1 for o in ops_b if o.change_type == "MACHINE_SUBSTITUTION"),
        "automation_change_count": sum(1 for o in ops_b if o.change_type == "AUTOMATION_UPGRADE"),
        "total_sam_minutes": {"a": va.total_sam_minutes, "b": vb.total_sam_minutes},
        "sam_status": {"a": va.sam_status, "b": vb.sam_status},
        "required_labor": {"a": va.required_labor, "b": vb.required_labor},
        "expected_output_per_day": {"a": va.expected_output_per_day, "b": vb.expected_output_per_day},
    }


# ------------------------------------------------------------------ Compatibility mapping quản trị (BR-309)
def list_compatibility(db: Session, operation_code: str = "") -> list[OperationMachineCompatibility]:
    q = db.query(OperationMachineCompatibility)
    if operation_code:
        q = q.filter(OperationMachineCompatibility.operation_code == operation_code)
    return q.order_by(OperationMachineCompatibility.operation_code, OperationMachineCompatibility.id).all()


def compatibility_view(row: OperationMachineCompatibility) -> dict:
    return {
        "id": row.id, "operation_code": row.operation_code, "source_machine_type_code": row.source_machine_type_code,
        "candidate_machine_type_code": row.candidate_machine_type_code, "candidate_machine_model_id": row.candidate_machine_model_id,
        "compatibility_status": row.compatibility_status, "evidence_ref": row.evidence_ref, "evidence_note": row.evidence_note,
        "created_by": row.created_by, "updated_by": row.updated_by,
    }


def save_compatibility(db: Session, user: User, d: dict, row_id: int | None = None) -> OperationMachineCompatibility:
    if row_id is None:
        if not (d.get("operation_code") or "").strip():
            raise HTTPException(422, "Cần operation_code")  # bắt buộc, không suy đoán theo tên (BR-309)
        if not (d.get("candidate_machine_type_code") or "").strip():
            raise HTTPException(422, "Cần candidate_machine_type_code")
        if not db.get(MachineType, d["candidate_machine_type_code"]):
            raise HTTPException(422, f"Loại máy '{d['candidate_machine_type_code']}' không tồn tại")  # V-304
        row = OperationMachineCompatibility(
            operation_code=d["operation_code"].strip(), source_machine_type_code=d.get("source_machine_type_code") or None,
            candidate_machine_type_code=d["candidate_machine_type_code"], candidate_machine_model_id=d.get("candidate_machine_model_id") or None,
            compatibility_status=d.get("compatibility_status") or "PROPOSED", evidence_ref=d.get("evidence_ref"), evidence_note=d.get("evidence_note") or "",
            created_by=user.username,
        )
        db.add(row)
    else:
        row = db.get(OperationMachineCompatibility, row_id)
        if row is None:
            raise HTTPException(404, "Không tìm thấy compatibility mapping")
        if d.get("candidate_machine_type_code") is not None and not db.get(MachineType, d["candidate_machine_type_code"]):
            raise HTTPException(422, f"Loại máy '{d['candidate_machine_type_code']}' không tồn tại")
        for k in ("source_machine_type_code", "candidate_machine_type_code", "candidate_machine_model_id", "compatibility_status", "evidence_ref", "evidence_note"):
            if k in d:
                setattr(row, k, d[k])
        row.updated_by, row.updated_at = user.username, utcnow()
    db.commit()
    write_audit("TECH_PROCESS_COMPATIBILITY_SAVE", user=user, object_type="OperationMachineCompatibility", object_id=str(row.id), detail=f"{row.operation_code} -> {row.candidate_machine_type_code} ({row.compatibility_status})")
    return row
