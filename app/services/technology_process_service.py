"""Quy trình công nghệ 3 tầng — service layer (Task 1, Issue #3).

Nguồn sự thật: Style/Model -> TechnologyProcess -> TechnologyProcessVersion (theo Layer) -> Operation (Machine + Manpower + SAM + Evidence).
SAM là chỉ số đi theo Version (BR-002), Total SAM = SUM(sam_minutes của operation active) (BR-016), không hidden efficiency factor,
không hard-code hệ số. Nếu operation thiếu SAM thì version ở trạng thái INCOMPLETE, không lấy median/default Style khác lấp vào (BR-017).

KHÔNG đọc/ghi `StyleSam` — bảng đó được giữ nguyên làm nguồn ước lượng tạm thời riêng biệt (Issue #3 §4, xác nhận GPT mục 8).
"""

from __future__ import annotations

import hashlib

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import User
from app.models.resources import MachineModel, MachineType
from app.models.technology_process import (
    LAYER_LABEL,
    LAYERS,
    SOURCE_TYPES,
    VERSION_STATUSES,
    TechnologyProcess,
    TechnologyProcessOperation,
    TechnologyProcessVersion,
)
from app.services.audit import write_audit

MACHINE_MODEL_STATUSES = ("CANDIDATE", "TRIAL", "APPROVED", "REJECTED")

# Forward-only workflow (Issue #3 review mục 6): permission nào gác bước nào được enforce ở API (require_perm),
# service chỉ kiểm tra tính hợp lệ của bước chuyển.
_TRANSITIONS = {
    "review": {"from": ("DRAFT", "SIMULATED"), "to": "REVIEWED"},
    "approve": {"from": ("REVIEWED",), "to": "APPROVED"},
    "retire": {"from": ("APPROVED",), "to": "RETIRED"},
}
_EDITABLE_STATUSES = ("DRAFT", "SIMULATED", "REVIEWED")  # APPROVED/RETIRED bất biến (V-007 + hệ quả tất yếu của RETIRED)


def _bad(msg: str) -> HTTPException:
    return HTTPException(422, msg)


# ------------------------------------------------------------------ view helpers
def operation_view(op: TechnologyProcessOperation) -> dict:
    return {
        "id": op.id, "process_version_id": op.process_version_id, "sequence_no": op.sequence_no, "operation_code": op.operation_code, "operation_name": op.operation_name,
        "machine_type_code": op.machine_type_code, "machine_model_id": op.machine_model_id, "operator_count": op.operator_count, "helper_count": op.helper_count,
        "sam_minutes": op.sam_minutes, "cycle_time_seconds": op.cycle_time_seconds, "expected_output_per_day": op.expected_output_per_day, "automation_level": op.automation_level,
        "setup_changeover_minutes": op.setup_changeover_minutes, "expected_defect_rate": op.expected_defect_rate, "source_type": op.source_type, "evidence_note": op.evidence_note,
        "evidence_ref": op.evidence_ref, "source_date": op.source_date.isoformat() if op.source_date else None, "is_active": op.is_active,
        "created_by": op.created_by, "created_at": op.created_at.isoformat() if op.created_at else None, "updated_by": op.updated_by,
        "updated_at": op.updated_at.isoformat() if op.updated_at else None,
    }


def version_view(v: TechnologyProcessVersion, with_operations: bool = False) -> dict:
    out = {
        "id": v.id, "technology_process_id": v.technology_process_id, "layer": v.layer, "layer_label": LAYER_LABEL.get(v.layer, v.layer), "version_no": v.version_no,
        "status": v.status, "source_type": v.source_type, "source_ref": v.source_ref, "source_date": v.source_date.isoformat() if v.source_date else None,
        "derived_from_version_id": v.derived_from_version_id, "effective_from": v.effective_from.isoformat() if v.effective_from else None,
        "effective_to": v.effective_to.isoformat() if v.effective_to else None, "total_sam_minutes": v.total_sam_minutes, "sam_status": v.sam_status,
        "expected_output_per_day": v.expected_output_per_day, "required_labor": v.required_labor, "assumptions_json": v.assumptions_json or {}, "note": v.note,
        "created_by": v.created_by, "created_at": v.created_at.isoformat() if v.created_at else None, "reviewed_by": v.reviewed_by,
        "reviewed_at": v.reviewed_at.isoformat() if v.reviewed_at else None, "approved_by": v.approved_by, "approved_at": v.approved_at.isoformat() if v.approved_at else None,
        "retired_by": v.retired_by, "retired_at": v.retired_at.isoformat() if v.retired_at else None, "editable": v.status in _EDITABLE_STATUSES,
        "operation_count": sum(1 for op in v.operations if op.is_active),
    }
    if with_operations:
        out["operations"] = [operation_view(op) for op in sorted(v.operations, key=lambda o: (not o.is_active, o.sequence_no))]
    return out


def process_view(p: TechnologyProcess, with_versions: bool = False) -> dict:
    out = {"id": p.id, "process_code": p.process_code, "style_cc": p.style_cc, "model_code": p.model_code, "product_family": p.product_family, "description": p.description,
           "status": p.status, "created_by": p.created_by, "created_at": p.created_at.isoformat() if p.created_at else None}
    if with_versions:
        out["versions"] = [version_view(v) for v in p.versions]
    return out


def machine_model_view(m: MachineModel) -> dict:
    return {"id": m.id, "machine_type_code": m.machine_type_code, "brand": m.brand, "model": m.model, "automation_level": m.automation_level, "reference_output": m.reference_output,
            "reference_cycle_time": m.reference_cycle_time, "required_operator": m.required_operator, "source": m.source, "status": m.status, "note": m.note,
            "created_by": m.created_by, "updated_by": m.updated_by}


# ------------------------------------------------------------------ TechnologyProcess
def _process_code(style_cc: str, model_code: str) -> str:
    base = f"TP-{style_cc}" + (f"-{model_code}" if model_code else "")
    return base.strip().upper()[:60]


def create_process(db: Session, user: User, d: dict) -> TechnologyProcess:
    style_cc = (d.get("style_cc") or "").strip()
    model_code = (d.get("model_code") or "").strip()
    if not style_cc:
        raise _bad("Cần Style/CC")
    if db.query(TechnologyProcess).filter(TechnologyProcess.style_cc == style_cc, TechnologyProcess.model_code == model_code).first():
        raise HTTPException(409, f"Đã có Technology Process cho Style {style_cc}" + (f" / Model {model_code}" if model_code else ""))
    p = TechnologyProcess(process_code=_process_code(style_cc, model_code), style_cc=style_cc, model_code=model_code, product_family=(d.get("product_family") or None),
                          description=d.get("description") or "", created_by=user.username)
    db.add(p)
    db.commit()
    write_audit("TECH_PROCESS_CREATE", user=user, object_type="TechnologyProcess", object_id=p.process_code, detail=f"{style_cc}/{model_code or '-'}")
    return p


def get_process(db: Session, process_id: int) -> TechnologyProcess:
    p = db.get(TechnologyProcess, process_id)
    if p is None:
        raise HTTPException(404, "Không tìm thấy Technology Process")
    return p


def get_or_create_process(db: Session, user: User, style_cc: str, model_code: str, product_family: str | None = None) -> TechnologyProcess:
    style_cc, model_code = style_cc.strip(), (model_code or "").strip()
    p = db.query(TechnologyProcess).filter(TechnologyProcess.style_cc == style_cc, TechnologyProcess.model_code == model_code).first()
    if p is not None:
        return p
    return create_process(db, user, {"style_cc": style_cc, "model_code": model_code, "product_family": product_family})


def list_versions(db: Session, style: str = "", model: str = "", layer: str = "", status: str = "", q: str = "", limit: int = 500) -> list[dict]:
    """Danh sách phẳng cho màn hình list: mỗi dòng = một version, kèm Style/Model/Process (§13 màn hình danh sách)."""
    query = db.query(TechnologyProcessVersion).join(TechnologyProcess, TechnologyProcessVersion.technology_process_id == TechnologyProcess.id)
    if style:
        query = query.filter(TechnologyProcess.style_cc.ilike(f"%{style}%"))
    if model:
        query = query.filter(TechnologyProcess.model_code.ilike(f"%{model}%"))
    if layer:
        query = query.filter(TechnologyProcessVersion.layer == layer)
    if status:
        if status not in VERSION_STATUSES:
            raise _bad(f"status phải là một trong {VERSION_STATUSES}")
        query = query.filter(TechnologyProcessVersion.status == status)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(TechnologyProcess.style_cc.ilike(like) | TechnologyProcess.model_code.ilike(like) | TechnologyProcess.process_code.ilike(like))
    rows = query.order_by(TechnologyProcess.style_cc, TechnologyProcess.model_code, TechnologyProcessVersion.layer, TechnologyProcessVersion.version_no.desc()).limit(limit).all()
    out = []
    for v in rows:
        row = version_view(v)
        row.update({"process_code": v.technology_process.process_code, "style_cc": v.technology_process.style_cc, "model_code": v.technology_process.model_code,
                    "updated_at": (v.approved_at or v.reviewed_at or v.created_at).isoformat() if (v.approved_at or v.reviewed_at or v.created_at) else None})
        out.append(row)
    return out


# ------------------------------------------------------------------ Version
def _next_version_no(db: Session, process_id: int, layer: str) -> int:
    last = db.query(TechnologyProcessVersion).filter(TechnologyProcessVersion.technology_process_id == process_id, TechnologyProcessVersion.layer == layer).order_by(TechnologyProcessVersion.version_no.desc()).first()
    return (last.version_no + 1) if last else 1


def get_version(db: Session, version_id: int) -> TechnologyProcessVersion:
    v = db.get(TechnologyProcessVersion, version_id)
    if v is None:
        raise HTTPException(404, "Không tìm thấy Technology Process Version")
    return v


def _validate_version_fields(d: dict) -> None:
    if d.get("layer") not in LAYERS:
        raise _bad(f"layer phải là một trong {LAYERS}")  # V-001
    if d.get("source_type") is not None and d["source_type"] not in SOURCE_TYPES:
        raise _bad(f"source_type phải là một trong {SOURCE_TYPES}")
    if d.get("effective_from") and d.get("effective_to") and d["effective_to"] < d["effective_from"]:
        raise _bad("effective_to phải >= effective_from")  # V-006


def create_draft_version(db: Session, user: User, process_id: int, d: dict) -> TechnologyProcessVersion:
    p = get_process(db, process_id)
    d = {**d, "layer": d.get("layer")}
    _validate_version_fields(d)
    v = TechnologyProcessVersion(
        technology_process_id=p.id, layer=d["layer"], version_no=_next_version_no(db, p.id, d["layer"]), status="DRAFT",
        source_type=d.get("source_type") or "MANUAL", source_ref=d.get("source_ref") or None, source_date=d.get("source_date"),
        derived_from_version_id=d.get("derived_from_version_id"), effective_from=d.get("effective_from"), effective_to=d.get("effective_to"),
        expected_output_per_day=d.get("expected_output_per_day"), required_labor=d.get("required_labor"), assumptions_json=d.get("assumptions_json") or {},
        note=d.get("note") or "", created_by=user.username,
    )
    db.add(v)
    db.commit()
    write_audit("TECH_PROCESS_VERSION_CREATE", user=user, object_type="TechnologyProcessVersion", object_id=str(v.id), detail=f"{p.process_code} {v.layer} v{v.version_no}")
    return v


def derive_version(db: Session, user: User, source_version_id: int, target_layer: str, d: dict | None = None) -> TechnologyProcessVersion:
    """Clone/derive (BR-006): tạo version DRAFT mới ở `target_layer`, copy các operation ACTIVE của version nguồn. Không auto-sync sau khi tạo."""
    d = d or {}
    src = get_version(db, source_version_id)
    if target_layer not in LAYERS:
        raise _bad(f"layer phải là một trong {LAYERS}")
    new_v = create_draft_version(db, user, src.technology_process_id, {
        "layer": target_layer, "source_type": d.get("source_type") or "ENGINEERING", "source_ref": d.get("source_ref") or f"Derived from version #{src.id}",
        "derived_from_version_id": src.id, "note": d.get("note") or "",
    })
    for op in sorted((o for o in src.operations if o.is_active), key=lambda o: o.sequence_no):
        db.add(TechnologyProcessOperation(
            process_version_id=new_v.id, sequence_no=op.sequence_no, operation_code=op.operation_code, operation_name=op.operation_name,
            machine_type_code=op.machine_type_code, machine_model_id=op.machine_model_id, operator_count=op.operator_count, helper_count=op.helper_count,
            sam_minutes=op.sam_minutes, cycle_time_seconds=op.cycle_time_seconds, expected_output_per_day=op.expected_output_per_day, automation_level=op.automation_level,
            setup_changeover_minutes=op.setup_changeover_minutes, expected_defect_rate=op.expected_defect_rate, source_type=op.source_type,
            evidence_note=op.evidence_note, evidence_ref=op.evidence_ref, source_date=op.source_date, created_by=user.username,
        ))
    db.commit()
    db.refresh(new_v)
    recalc_total_sam(db, new_v)
    write_audit("TECH_PROCESS_VERSION_DERIVE", user=user, object_type="TechnologyProcessVersion", object_id=str(new_v.id), detail=f"from version #{src.id} ({src.layer}) -> {target_layer}")
    return new_v


def update_version(db: Session, user: User, version_id: int, d: dict) -> TechnologyProcessVersion:
    v = get_version(db, version_id)
    if v.status not in _EDITABLE_STATUSES:
        raise HTTPException(409, f"Version đang {v.status} — bất biến, hãy tạo version mới")  # V-007
    if "effective_from" in d or "effective_to" in d:
        ef = d.get("effective_from", v.effective_from)
        et = d.get("effective_to", v.effective_to)
        if ef and et and et < ef:
            raise _bad("effective_to phải >= effective_from")
    for k in ("source_ref", "source_date", "effective_from", "effective_to", "expected_output_per_day", "required_labor", "assumptions_json", "note"):
        if k in d:
            setattr(v, k, d[k])
    db.commit()
    write_audit("TECH_PROCESS_VERSION_UPDATE", user=user, object_type="TechnologyProcessVersion", object_id=str(v.id), detail="cập nhật thông tin version")
    return v


# ------------------------------------------------------------------ Total SAM (BR-016, BR-017)
def recalc_total_sam(db: Session, v: TechnologyProcessVersion) -> TechnologyProcessVersion:
    active = [op for op in v.operations if op.is_active]
    if not active:
        v.total_sam_minutes, v.sam_status = None, "EMPTY"
    elif any(op.sam_minutes is None for op in active):
        v.total_sam_minutes, v.sam_status = None, "INCOMPLETE"  # BR-017 — không lấy median/default Style khác lấp vào
    else:
        v.total_sam_minutes, v.sam_status = round(sum(op.sam_minutes for op in active), 4), "COMPLETE"
    db.commit()
    return v


# ------------------------------------------------------------------ Operation
def _validate_operation(db: Session, d: dict) -> None:
    if d.get("sam_minutes") is not None and not float(d["sam_minutes"]) > 0:
        raise _bad("SAM phải > 0 nếu có giá trị")  # V-004
    if d.get("operator_count") is not None and int(d["operator_count"]) < 0:
        raise _bad("operator_count phải >= 0")  # V-005
    if d.get("helper_count") is not None and int(d["helper_count"]) < 0:
        raise _bad("helper_count phải >= 0")
    if d.get("machine_type_code") and not db.get(MachineType, d["machine_type_code"]):
        raise _bad(f"Loại máy '{d['machine_type_code']}' không tồn tại")
    if d.get("machine_model_id"):
        mm = db.get(MachineModel, d["machine_model_id"])
        if mm is None:
            raise _bad("Machine Model không tồn tại")
        if d.get("machine_type_code") and mm.machine_type_code != d["machine_type_code"]:
            raise _bad(f"Machine Model '{mm.model}' không thuộc loại máy '{d['machine_type_code']}'")  # V-009


def _guard_editable(v: TechnologyProcessVersion) -> None:
    if v.status not in _EDITABLE_STATUSES:
        raise HTTPException(409, f"Version đang {v.status} — bất biến, không thể sửa operation. Hãy tạo version mới (derive/clone).")


def add_operation(db: Session, user: User, version_id: int, d: dict) -> TechnologyProcessOperation:
    v = get_version(db, version_id)
    _guard_editable(v)
    _validate_operation(db, d)
    seq = d.get("sequence_no")
    if seq is None:
        seq = (max((op.sequence_no for op in v.operations if op.is_active), default=0)) + 1
    elif any(op.sequence_no == seq and op.is_active for op in v.operations):
        raise _bad(f"Thứ tự công đoạn {seq} đã tồn tại trong version này")  # V-003
    op = TechnologyProcessOperation(
        process_version_id=v.id, sequence_no=seq, operation_code=d.get("operation_code") or "", operation_name=d.get("operation_name") or "",
        machine_type_code=d.get("machine_type_code") or None, machine_model_id=d.get("machine_model_id") or None, operator_count=int(d.get("operator_count") or 0),
        helper_count=d.get("helper_count"), sam_minutes=d.get("sam_minutes"), cycle_time_seconds=d.get("cycle_time_seconds"), expected_output_per_day=d.get("expected_output_per_day"),
        automation_level=d.get("automation_level") or "", setup_changeover_minutes=d.get("setup_changeover_minutes"), expected_defect_rate=d.get("expected_defect_rate"),
        source_type=d.get("source_type") or "MANUAL", evidence_note=d.get("evidence_note") or "", evidence_ref=d.get("evidence_ref"), source_date=d.get("source_date"),
        created_by=user.username,
    )
    db.add(op)
    db.commit()
    recalc_total_sam(db, v)
    write_audit("TECH_PROCESS_OPERATION_ADD", user=user, object_type="TechnologyProcessOperation", object_id=str(op.id), detail=f"version #{v.id} seq {op.sequence_no} {op.operation_name}")
    return op


def update_operation(db: Session, user: User, operation_id: int, d: dict) -> TechnologyProcessOperation:
    op = db.get(TechnologyProcessOperation, operation_id)
    if op is None:
        raise HTTPException(404, "Không tìm thấy công đoạn")
    v = get_version(db, op.process_version_id)
    _guard_editable(v)
    merged = {**operation_view(op), **d}
    _validate_operation(db, merged)
    if "sequence_no" in d and d["sequence_no"] != op.sequence_no:
        if any(o.id != op.id and o.sequence_no == d["sequence_no"] and o.is_active for o in v.operations):
            raise _bad(f"Thứ tự công đoạn {d['sequence_no']} đã tồn tại trong version này")
    for k in ("sequence_no", "operation_code", "operation_name", "machine_type_code", "machine_model_id", "operator_count", "helper_count", "sam_minutes", "cycle_time_seconds",
              "expected_output_per_day", "automation_level", "setup_changeover_minutes", "expected_defect_rate", "source_type", "evidence_note", "evidence_ref", "source_date"):
        if k in d:
            setattr(op, k, d[k])
    op.updated_by, op.updated_at = user.username, utcnow()
    db.commit()
    recalc_total_sam(db, v)
    write_audit("TECH_PROCESS_OPERATION_UPDATE", user=user, object_type="TechnologyProcessOperation", object_id=str(op.id), detail=f"version #{v.id} seq {op.sequence_no}")
    return op


def remove_operation(db: Session, user: User, operation_id: int, reason: str = "") -> TechnologyProcessOperation:
    """Gỡ operation = soft (is_active=False), giữ lịch sử/audit. Chỉ cho phép khi version còn editable."""
    op = db.get(TechnologyProcessOperation, operation_id)
    if op is None:
        raise HTTPException(404, "Không tìm thấy công đoạn")
    v = get_version(db, op.process_version_id)
    _guard_editable(v)
    op.is_active, op.updated_by, op.updated_at = False, user.username, utcnow()
    db.commit()
    recalc_total_sam(db, v)
    write_audit("TECH_PROCESS_OPERATION_REMOVE", user=user, object_type="TechnologyProcessOperation", object_id=str(op.id), detail=f"version #{v.id} seq {op.sequence_no}. Lý do: {reason}"[:2000])
    return op


# ------------------------------------------------------------------ Workflow (forward-only, Task 1)
def transition_version(db: Session, user: User, version_id: int, action: str) -> TechnologyProcessVersion:
    v = get_version(db, version_id)
    rule = _TRANSITIONS.get(action)
    if rule is None:
        raise _bad(f"Hành động '{action}' không hợp lệ")
    if v.status not in rule["from"]:
        raise HTTPException(409, f"Không thể '{action}' từ trạng thái {v.status} (cần {', '.join(rule['from'])})")
    v.status = rule["to"]
    now = utcnow()
    if action == "review":
        v.reviewed_by, v.reviewed_at = user.username, now
    elif action == "approve":
        v.approved_by, v.approved_at = user.username, now
    elif action == "retire":
        v.retired_by, v.retired_at = user.username, now
    db.commit()
    write_audit(f"TECH_PROCESS_VERSION_{action.upper()}", user=user, object_type="TechnologyProcessVersion", object_id=str(v.id), detail=f"{v.status}")
    return v


def simulate_version(db: Session, user: User, version_id: int) -> TechnologyProcessVersion:
    """DRAFT -> SIMULATED: đánh dấu version đã có kết quả tính toán/mô phỏng, vẫn là proposal (BR-009), chưa được review."""
    v = get_version(db, version_id)
    if v.status != "DRAFT":
        raise HTTPException(409, f"Chỉ chuyển SIMULATED được từ DRAFT (hiện {v.status})")
    v.status = "SIMULATED"
    db.commit()
    write_audit("TECH_PROCESS_VERSION_SIMULATE", user=user, object_type="TechnologyProcessVersion", object_id=str(v.id), detail="SIMULATED")
    return v


# ------------------------------------------------------------------ Compare (§13)
def compare_versions(db: Session, version_ids: list[int]) -> list[dict]:
    out = []
    for vid in version_ids:
        v = get_version(db, vid)
        active = [op for op in v.operations if op.is_active]
        machines = sorted({(op.machine_type_code or "", op.machine_model_id) for op in active if op.machine_type_code or op.machine_model_id})
        out.append({**version_view(v), "process_code": v.technology_process.process_code, "style_cc": v.technology_process.style_cc, "model_code": v.technology_process.model_code,
                    "operation_count": len(active), "machine_summary": [{"machine_type_code": mt, "machine_model_id": mid} for mt, mid in machines]})
    return out


# ------------------------------------------------------------------ Bootstrap / import Current Process (§11)
# BR: KHÔNG tự query ERP trong Task 1 (Known Gap) — nhận input đã chuẩn hóa qua service/API (manual/controlled bootstrap).
def _fingerprint(style_cc: str, model_code: str, layer: str, source_ref: str, operations: list[dict]) -> str:
    ops_key = "|".join(f"{o.get('operation_code','')}:{o.get('sequence_no','')}:{o.get('sam_minutes','')}:{o.get('machine_type_code','')}" for o in sorted(operations, key=lambda o: o.get("sequence_no", 0)))
    raw = f"{style_cc}::{model_code}::{layer}::{source_ref}::{ops_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def bootstrap_current_process(db: Session, user: User, d: dict) -> dict:
    """Bootstrap thủ công/normalized có kiểm soát cho Current Process (BR-011, BR-015). KHÔNG tự nối ERP sống trong Task 1."""
    style_cc, model_code = (d.get("style_cc") or "").strip(), (d.get("model_code") or "").strip()
    if not style_cc:
        raise _bad("Cần Style/CC")
    operations = d.get("operations") or []
    if not operations:
        raise _bad("Cần ít nhất một operation để bootstrap")
    source_ref = (d.get("source_ref") or "").strip()
    if not source_ref:
        raise _bad("Cần source_ref (bằng chứng nguồn) cho bootstrap — không được để trống")
    fp = _fingerprint(style_cc, model_code, "CURRENT_PROCESS", source_ref, operations)

    p = get_or_create_process(db, user, style_cc, model_code, d.get("product_family"))
    existing = db.query(TechnologyProcessVersion).filter(TechnologyProcessVersion.technology_process_id == p.id, TechnologyProcessVersion.layer == "CURRENT_PROCESS",
                                                           TechnologyProcessVersion.bootstrap_fingerprint == fp).first()
    if existing is not None:  # BR-015 — idempotent: cùng fingerprint không tạo duplicate
        return {"created": False, "process": process_view(p), "version": version_view(existing, True)}

    v = create_draft_version(db, user, p.id, {"layer": "CURRENT_PROCESS", "source_type": "IMPORT", "source_ref": source_ref, "source_date": d.get("source_date"),
                                              "note": d.get("note") or "Bootstrap thủ công — chưa nối live ERP QTCN (Known Gap)"})
    v.bootstrap_fingerprint = fp
    db.commit()
    for i, od in enumerate(operations, start=1):
        add_operation(db, user, v.id, {**od, "sequence_no": od.get("sequence_no", i), "source_type": od.get("source_type") or "IMPORT"})
    db.refresh(v)
    write_audit("TECH_PROCESS_BOOTSTRAP", user=user, object_type="TechnologyProcessVersion", object_id=str(v.id), detail=f"{p.process_code} CURRENT_PROCESS bootstrap ({len(operations)} operation), source_ref={source_ref}")
    return {"created": True, "process": process_view(p), "version": version_view(v, True)}


# ------------------------------------------------------------------ Machine Model / Candidate (§10) — master độc lập, KHÔNG thuộc sở hữu một Process
def save_machine_model(db: Session, user: User, d: dict, model_id: int | None = None) -> MachineModel:
    if d.get("machine_type_code") is not None and not db.get(MachineType, d["machine_type_code"]):
        raise _bad(f"Loại máy '{d['machine_type_code']}' không tồn tại")
    if d.get("status") is not None and d["status"] not in MACHINE_MODEL_STATUSES:
        raise _bad(f"status phải là một trong {MACHINE_MODEL_STATUSES}")
    if model_id is None:
        if not d.get("machine_type_code"):
            raise _bad("Cần loại máy")
        m = MachineModel(machine_type_code=d["machine_type_code"], brand=d.get("brand") or "", model=d.get("model") or "", automation_level=d.get("automation_level") or "",
                         reference_output=d.get("reference_output"), reference_cycle_time=d.get("reference_cycle_time"), required_operator=d.get("required_operator"),
                         source=d.get("source") or "MANUAL", status=d.get("status") or "CANDIDATE", note=d.get("note") or "", created_by=user.username)
        db.add(m)
        action = "MACHINE_MODEL_CREATE"
    else:
        m = db.get(MachineModel, model_id)
        if m is None:
            raise HTTPException(404, "Không tìm thấy Machine Model")
        for k in ("machine_type_code", "brand", "model", "automation_level", "reference_output", "reference_cycle_time", "required_operator", "source", "status", "note"):
            if k in d:
                setattr(m, k, d[k])
        m.updated_by, m.updated_at = user.username, utcnow()
        action = "MACHINE_MODEL_UPDATE"
    db.commit()
    write_audit(action, user=user, object_type="MachineModel", object_id=str(m.id), detail=f"{m.machine_type_code} {m.brand} {m.model} ({m.status})")
    return m


def list_machine_models(db: Session, machine_type: str = "", status: str = "") -> list[MachineModel]:
    q = db.query(MachineModel)
    if machine_type:
        q = q.filter(MachineModel.machine_type_code == machine_type)
    if status:
        q = q.filter(MachineModel.status == status)
    return q.order_by(MachineModel.machine_type_code, MachineModel.brand, MachineModel.model).all()
