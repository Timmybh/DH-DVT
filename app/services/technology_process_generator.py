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
from app.models.tech_compatibility import COMPATIBILITY_STATUSES, OperationMachineCompatibility
from app.models.technology_process import TechnologyProcessVersion
from app.services import technology_process_service as tps
from app.services.audit import write_audit

log = logging.getLogger(__name__)

GENERATOR_RULE_VERSION = "OCT_GEN_V1"
DECISION_STATES = ("UNCHANGED", "MACHINE_SUBSTITUTION", "MULTIPLE_CANDIDATES", "UNVERIFIED_CANDIDATE_AVAILABLE")


# ------------------------------------------------------------------ candidate lookup (chỉ đọc)
def _candidate_machine_type_ok(db: Session, machine_type_code: str) -> bool:
    mt = db.get(MachineType, machine_type_code)
    return mt is not None and mt.status == "ACTIVE"


def _candidate_machine_model_selectable(db: Session, row: OperationMachineCompatibility) -> bool:
    """Model REJECTED hoặc thuộc sai loại máy (mismatch) không phải candidate hợp lệ dù chỉ để user chọn tay
    (GPT review round 1 mục 3) — chỉ CANDIDATE/TRIAL/APPROVED thuộc đúng candidate_machine_type_code mới hiện."""
    if row.candidate_machine_model_id is None:
        return True  # type-level, không có model cụ thể
    mm = db.get(MachineModel, row.candidate_machine_model_id)
    return mm is not None and mm.status != "REJECTED" and mm.machine_type_code == row.candidate_machine_type_code


def _candidates_for_operation(db: Session, operation_code: str, current_machine_type_code: str | None) -> list[OperationMachineCompatibility]:
    """Candidate hợp lệ để hiện/preview/select — không gồm REJECTED, không gồm MachineType inactive, không gồm
    MachineModel REJECTED/mismatch (GPT review round 1 mục 3: những trường hợp này không phải 'unverified candidate'
    hợp lệ, kể cả để user chọn tay)."""
    if not operation_code:
        return []
    rows = (
        db.query(OperationMachineCompatibility)
        .filter(OperationMachineCompatibility.operation_code == operation_code, OperationMachineCompatibility.compatibility_status != "REJECTED")
        .all()
    )
    rows = [r for r in rows if r.source_machine_type_code is None or r.source_machine_type_code == current_machine_type_code]
    rows = [r for r in rows if _candidate_machine_type_ok(db, r.candidate_machine_type_code)]
    rows = [r for r in rows if _candidate_machine_model_selectable(db, r)]
    return rows


def _is_eligible(db: Session, row: OperationMachineCompatibility) -> bool:
    """Đủ điều kiện auto-apply. Defense-in-depth: kiểm tra lại cả MachineType active + MachineModel thuộc đúng
    loại máy (GPT review round 1 mục 2), không chỉ dựa vào việc row đã lọt qua `_candidates_for_operation`."""
    if row.compatibility_status != "APPROVED":
        return False
    if not _candidate_machine_type_ok(db, row.candidate_machine_type_code):
        return False
    if row.candidate_machine_model_id is None:
        return True
    mm = db.get(MachineModel, row.candidate_machine_model_id)
    return mm is not None and mm.status in ("APPROVED", "TRIAL") and mm.machine_type_code == row.candidate_machine_type_code


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
    """Snapshot đầy đủ 1 candidate tại thời điểm gọi — dùng cho cả preview và Generation Evidence
    (`candidates_considered`, GPT review round 2 mục 2: phải đủ để giải thích sau này vì sao được/không được chọn
    dù compatibility mapping bị sửa tiếp)."""
    mt = db.get(MachineType, row.candidate_machine_type_code)
    mm = db.get(MachineModel, row.candidate_machine_model_id) if row.candidate_machine_model_id else None
    return {
        "id": row.id, "candidate_machine_type_code": row.candidate_machine_type_code, "candidate_machine_model_id": row.candidate_machine_model_id,
        "candidate_machine_type_status": mt.status if mt else None, "machine_model_status": mm.status if mm else None,
        "compatibility_status": row.compatibility_status, "evidence_ref": row.evidence_ref, "evidence_note": row.evidence_note,
        "eligible": _is_eligible(db, row), "selectable": True,  # đã qua _candidates_for_operation nên luôn selectable
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


# ------------------------------------------------------------------ fingerprint (review mục 5; sửa round 1 mục 1)
def _canon_val(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _hash_json(payload) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


_OP_SNAPSHOT_FIELDS = (
    "sequence_no", "operation_code", "operation_name", "machine_type_code", "machine_model_id", "operator_count", "helper_count",
    "sam_minutes", "cycle_time_seconds", "expected_output_per_day", "automation_level", "setup_changeover_minutes", "expected_defect_rate",
)


def _source_snapshot(src: TechnologyProcessVersion) -> list[dict]:
    return [
        {f: _canon_val(getattr(o, f)) for f in _OP_SNAPSHOT_FIELDS}
        for o in sorted((o for o in src.operations if o.is_active), key=lambda o: o.sequence_no)
    ]


def _compatibility_snapshot(db: Session, active_ops: list) -> list[dict]:
    """Canonical snapshot của các compatibility rows THỰC SỰ có thể ảnh hưởng operation hiện tại — cùng scope với
    `_candidates_for_operation()`: operation_code khớp VÀ (source_machine_type_code null HOẶC khớp machine_type_code
    hiện tại của operation đó) (GPT review round 2 mục 1 — sửa lỗi round 1: trước đó lấy TẤT CẢ row cùng
    operation_code kể cả mapping không liên quan tới source_machine_type hiện tại, gây false new-proposal khi
    sửa 1 mapping không liên quan). Vẫn giữ row REJECTED/inactive/model REJECTED trong scope nếu source khớp,
    vì đổi status của chính row đó có thể làm eligibility thay đổi. Gồm cả field ảnh hưởng eligibility
    (MachineType/MachineModel status) để đổi target trên CÙNG row cũng làm đổi fingerprint (round 1 mục 1)."""
    op_codes = sorted({(o.operation_code or "").strip() for o in active_ops if (o.operation_code or "").strip()})
    if not op_codes:
        return []
    allowed_source_types: dict[str, set] = {}
    for o in active_ops:
        code = (o.operation_code or "").strip()
        if code:
            allowed_source_types.setdefault(code, set()).add(o.machine_type_code)
    rows = (
        db.query(OperationMachineCompatibility)
        .filter(OperationMachineCompatibility.operation_code.in_(op_codes))
        .order_by(OperationMachineCompatibility.id)
        .all()
    )
    out = []
    for r in rows:
        if r.source_machine_type_code is not None and r.source_machine_type_code not in allowed_source_types.get(r.operation_code, set()):
            continue
        mt = db.get(MachineType, r.candidate_machine_type_code)
        mm = db.get(MachineModel, r.candidate_machine_model_id) if r.candidate_machine_model_id else None
        out.append({
            "id": r.id, "operation_code": r.operation_code, "source_machine_type_code": r.source_machine_type_code,
            "candidate_machine_type_code": r.candidate_machine_type_code, "candidate_machine_model_id": r.candidate_machine_model_id,
            "compatibility_status": r.compatibility_status, "evidence_ref": r.evidence_ref, "evidence_note": r.evidence_note,
            "candidate_machine_type_status": mt.status if mt else None,
            "candidate_machine_model_status": mm.status if mm else None,
            "candidate_machine_model_type_code": mm.machine_type_code if mm else None,
        })
    return out


def compute_generation_fingerprint(db: Session, src: TechnologyProcessVersion, decisions: list[dict], selections: dict) -> tuple[str, str, str]:
    """Trả (generation_fingerprint, source_snapshot_hash, compatibility_snapshot_hash)."""
    active_ops = sorted((o for o in src.operations if o.is_active), key=lambda o: o.sequence_no)
    source_hash = _hash_json(_source_snapshot(src))
    compat_hash = _hash_json(_compatibility_snapshot(db, active_ops))
    payload = {
        "source_version_id": src.id, "source_layer": src.layer, "source_snapshot_hash": source_hash,
        "compatibility_snapshot_hash": compat_hash, "generator_rule_version": GENERATOR_RULE_VERSION,
        "decisions": decisions, "selections": selections or {},
    }
    return _hash_json(payload), source_hash, compat_hash


def _validate_selections(active_ops: list, selections: dict) -> dict[str, int]:
    """Chuẩn hóa + validate `selections` TRƯỚC khi build decisions/fingerprint — key rác/không tồn tại/không phải
    sequence_no active phải bị 422 ngay, không được lọt vào fingerprint (GPT review round 3 mục 1: nếu không,
    cùng source + cùng mapping + cùng quyết định thực tế vẫn có thể tạo proposal mới chỉ vì request có key rác,
    trái BR-316/V-308)."""
    valid_seqs = {op.sequence_no for op in active_ops}
    validated: dict[str, int] = {}
    for k, v in (selections or {}).items():
        try:
            seq = int(k)
        except (TypeError, ValueError):
            raise HTTPException(422, f"Selection key '{k}' không hợp lệ — phải là sequence_no dạng số")
        if seq not in valid_seqs:
            raise HTTPException(422, f"Selection key '{k}' không khớp sequence_no nào đang active trong source")
        if not isinstance(v, int) or isinstance(v, bool):
            raise HTTPException(422, f"Giá trị selection cho sequence_no {seq} phải là compatibility id dạng số nguyên")
        validated[str(seq)] = v
    return validated


# ------------------------------------------------------------------ Generate (ghi thật, atomic MỘT transaction)
def generate_optimized_proposal(db: Session, user: User, source_version_id: int, selections: dict[str, int] | None = None) -> dict:
    """selections: {str(sequence_no): compatibility_row_id} — lựa chọn tường minh của user cho operation đang
    MULTIPLE_CANDIDATES/UNVERIFIED_CANDIDATE_AVAILABLE. Không truyền = giữ UNCHANGED cho các operation đó."""
    src = tps.get_version(db, source_version_id)
    if src.layer != "CURRENT_PROCESS":
        raise HTTPException(422, "Source version phải thuộc layer CURRENT_PROCESS")  # V-301

    active_ops = sorted((o for o in src.operations if o.is_active), key=lambda o: o.sequence_no)
    selections = _validate_selections(active_ops, selections)
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
        chosen_mm = db.get(MachineModel, chosen.candidate_machine_model_id) if chosen and chosen.candidate_machine_model_id else None
        decisions.append({
            "sequence_no": op.sequence_no, "operation_code": op.operation_code, "decision": decision,
            "chosen_candidate_id": chosen.id if chosen else None,
            "chosen_compatibility_status": chosen.compatibility_status if chosen else None,
            "chosen_machine_model_status": chosen_mm.status if chosen_mm else None,
            "chosen_eligible": _is_eligible(db, chosen) if chosen else None,
            "user_selected": user_selected,
            # snapshot TẤT CẢ candidate đã xét (không chỉ candidate được chọn) tại thời điểm generate — để sau này
            # compatibility mapping bị sửa tiếp vẫn giải thích được vì sao lúc đó A được chọn còn B thì không
            # (GPT review round 2 mục 2)
            "candidates_considered": [_candidate_out(db, c) for c in candidates],
        })

    fp, source_hash, compat_hash = compute_generation_fingerprint(db, src, decisions, selections)

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
        metric_completeness = {
            # AC-305 — chỉ rõ metric nào thiếu/chưa xác định tại thời điểm generate, không tự bịa (GPT review round 2 mục 2)
            "total_sam_minutes": new_v.sam_status,  # EMPTY | COMPLETE | INCOMPLETE (BR-017)
            "expected_output_per_day": "AVAILABLE" if new_v.expected_output_per_day is not None else "N/A",
            "required_labor": "AVAILABLE" if new_v.required_labor is not None else "N/A",
            "setup_changeover_minutes": "AVAILABLE" if cloned_ops and all(o.setup_changeover_minutes is not None for o in cloned_ops) else "N/A",
            # Task 3 không có dữ liệu/công thức nào để tính bottleneck/utilization — luôn N/A, không tự bịa (GPT review round 3 mục 2)
            "bottleneck": "N/A",
            "utilization": "N/A",
        }
        new_v.assumptions_json = {
            "generator_rule_version": GENERATOR_RULE_VERSION, "generated_at": utcnow().isoformat(), "generated_by": user.username,
            "source_version_id": src.id, "generation_fingerprint": fp,
            "source_snapshot_hash": source_hash, "compatibility_snapshot_hash": compat_hash,
            "sam_status": new_v.sam_status, "metric_completeness": metric_completeness,
            "decisions": decisions, "selections": selections,
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


# ------------------------------------------------------------------ Compare (mục 7 Issue #7; guard sửa round 1 mục 4)
def compare_current_vs_optimized(db: Session, version_a_id: int, version_b_id: int) -> dict:
    va = tps.get_version(db, version_a_id)
    vb = tps.get_version(db, version_b_id)
    if va.technology_process_id != vb.technology_process_id:
        raise HTTPException(422, "Chỉ so sánh được các version của cùng một Technology Process")
    if va.layer != "CURRENT_PROCESS":
        raise HTTPException(422, "version_a phải thuộc layer CURRENT_PROCESS")
    if vb.layer != "OPTIMIZED_CURRENT_TECHNOLOGY":
        raise HTTPException(422, "version_b phải thuộc layer OPTIMIZED_CURRENT_TECHNOLOGY")
    if vb.derived_from_version_id != va.id:
        raise HTTPException(422, "version_b không phải được derive từ version_a — endpoint này chỉ so Current gốc với đúng Optimized của nó")
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


_COMPATIBILITY_REQUIRED_FIELDS = ("operation_code", "candidate_machine_type_code", "compatibility_status")


def _validate_compatibility_final_state(db: Session, operation_code: str, source_mtc: str | None, candidate_mtc: str, candidate_model_id: int | None, status: str | None) -> None:
    """Validate trạng thái CUỐI của row (không chỉ field vừa truyền) — GPT review round 1 mục 2."""
    if not (operation_code or "").strip():
        raise HTTPException(422, "Cần operation_code")  # bắt buộc, không suy đoán theo tên (BR-309)
    if not (candidate_mtc or "").strip():
        raise HTTPException(422, "Cần candidate_machine_type_code")
    if not db.get(MachineType, candidate_mtc):
        raise HTTPException(422, f"Loại máy '{candidate_mtc}' không tồn tại")  # V-304
    if source_mtc and not db.get(MachineType, source_mtc):
        raise HTTPException(422, f"Loại máy nguồn '{source_mtc}' không tồn tại")
    if status not in COMPATIBILITY_STATUSES:
        raise HTTPException(422, f"compatibility_status không hợp lệ: {status!r} (phải thuộc {COMPATIBILITY_STATUSES})")
    if candidate_model_id is not None:
        mm = db.get(MachineModel, candidate_model_id)
        if mm is None:
            raise HTTPException(422, f"MachineModel id {candidate_model_id} không tồn tại")
        if mm.machine_type_code != candidate_mtc:
            raise HTTPException(422, f"MachineModel #{candidate_model_id} thuộc loại máy '{mm.machine_type_code}', không khớp candidate_machine_type_code '{candidate_mtc}'")  # V-009


def save_compatibility(db: Session, user: User, d: dict, row_id: int | None = None) -> OperationMachineCompatibility:
    if row_id is None:
        operation_code = (d.get("operation_code") or "").strip()
        source_mtc = d.get("source_machine_type_code") or None
        candidate_mtc = (d.get("candidate_machine_type_code") or "").strip()
        candidate_model_id = d.get("candidate_machine_model_id") or None
        status = d.get("compatibility_status") or "PROPOSED"
        _validate_compatibility_final_state(db, operation_code, source_mtc, candidate_mtc, candidate_model_id, status)
        row = OperationMachineCompatibility(
            operation_code=operation_code, source_machine_type_code=source_mtc,
            candidate_machine_type_code=candidate_mtc, candidate_machine_model_id=candidate_model_id,
            compatibility_status=status, evidence_ref=d.get("evidence_ref"), evidence_note=d.get("evidence_note") or "",
            created_by=user.username,
        )
        db.add(row)
    else:
        row = db.get(OperationMachineCompatibility, row_id)
        if row is None:
            raise HTTPException(404, "Không tìm thấy compatibility mapping")
        # explicit null cho field bắt buộc khi update -> 422 tường minh, không để rơi xuống DB IntegrityError/500
        for k in _COMPATIBILITY_REQUIRED_FIELDS:
            if k in d and (d[k] is None or (isinstance(d[k], str) and not d[k].strip())):
                raise HTTPException(422, f"{k} không được để trống")
        final_operation_code = d["operation_code"].strip() if "operation_code" in d else row.operation_code
        final_source_mtc = d["source_machine_type_code"] if "source_machine_type_code" in d else row.source_machine_type_code
        final_candidate_mtc = d["candidate_machine_type_code"].strip() if "candidate_machine_type_code" in d else row.candidate_machine_type_code
        final_candidate_model_id = d["candidate_machine_model_id"] if "candidate_machine_model_id" in d else row.candidate_machine_model_id
        final_status = d["compatibility_status"] if "compatibility_status" in d else row.compatibility_status
        _validate_compatibility_final_state(db, final_operation_code, final_source_mtc, final_candidate_mtc, final_candidate_model_id, final_status)
        row.operation_code, row.source_machine_type_code = final_operation_code, final_source_mtc
        row.candidate_machine_type_code, row.candidate_machine_model_id = final_candidate_mtc, final_candidate_model_id
        row.compatibility_status = final_status
        if "evidence_ref" in d:
            row.evidence_ref = d["evidence_ref"]
        if "evidence_note" in d:
            row.evidence_note = d["evidence_note"] or ""
        row.updated_by, row.updated_at = user.username, utcnow()
    db.commit()
    write_audit("TECH_PROCESS_COMPATIBILITY_SAVE", user=user, object_type="OperationMachineCompatibility", object_id=str(row.id), detail=f"{row.operation_code} -> {row.candidate_machine_type_code} ({row.compatibility_status})")
    return row
