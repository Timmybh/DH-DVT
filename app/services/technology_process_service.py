"""Quy trình công nghệ 3 tầng — service layer (Task 1, Issue #3).

Nguồn sự thật: Style/Model -> TechnologyProcess -> TechnologyProcessVersion (theo Layer) -> Operation (Machine + Manpower + SAM + Evidence).
SAM là chỉ số đi theo Version (BR-002), Total SAM = SUM(sam_minutes của operation active) (BR-016), không hidden efficiency factor,
không hard-code hệ số. Nếu operation thiếu SAM thì version ở trạng thái INCOMPLETE, không lấy median/default Style khác lấp vào (BR-017).

KHÔNG đọc/ghi `StyleSam` — bảng đó được giữ nguyên làm nguồn ước lượng tạm thời riêng biệt (Issue #3 §4, xác nhận GPT mục 8).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
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
_EDITABLE_STATUSES = ("DRAFT", "SIMULATED")  # REVIEWED/APPROVED/RETIRED bất biến — sửa lại theo GPT review #4 mục 3: mapping đã chốt là
# `manage` chỉ sửa DRAFT/SIMULATED, `review` chuyển sang REVIEWED (khóa nội dung), `approve` từ REVIEWED. Muốn sửa sau REVIEWED phải derive version mới.


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
def _canon_key(v: str | None) -> str:
    """Business identity canonicalization cho style_cc/model_code (GPT review vòng 2 mục 1): trim + uppercase,
    để 'A100'/'a100' luôn resolve về CÙNG một TechnologyProcess thay vì tạo 2 family khác nhau. Áp dụng đồng nhất
    ở create_process/get_or_create_process/bootstrap — không có đường nào khác tạo TechnologyProcess."""
    return (v or "").strip().upper()


def _process_code_base(style_cc: str, model_code: str) -> str:
    base = f"TP-{style_cc}" + (f"-{model_code}" if model_code else "")
    return base.strip().upper()


def _unique_process_code(db: Session, style_cc: str, model_code: str) -> str:
    """process_code phải là business identity ổn định/bất biến (GPT review #4 mục 6): base tạo từ style/model (đọc được),
    nhưng nếu trùng với process KHÁC sau khi upper-case + cắt 60 ký tự (VD 'ab' vs 'AB', hoặc style/model rất dài trùng
    tiền tố) thì disambiguate bằng hash ngắn, deterministic theo chính style_cc+model_code — không dựa vào random/thời gian."""
    base = _process_code_base(style_cc, model_code)[:60]
    if db.query(TechnologyProcess.id).filter(TechnologyProcess.process_code == base).first() is None:
        return base
    suffix = hashlib.sha1(f"{style_cc}::{model_code}".encode("utf-8")).hexdigest()[:8].upper()
    return f"{base[:51]}-{suffix}"[:60]


def create_process(db: Session, user: User, d: dict) -> TechnologyProcess:
    style_cc = _canon_key(d.get("style_cc"))
    model_code = _canon_key(d.get("model_code"))
    if not style_cc:
        raise _bad("Cần Style/CC")
    if db.query(TechnologyProcess).filter(TechnologyProcess.style_cc == style_cc, TechnologyProcess.model_code == model_code).first():
        raise HTTPException(409, f"Đã có Technology Process cho Style {style_cc}" + (f" / Model {model_code}" if model_code else ""))
    p = TechnologyProcess(process_code=_unique_process_code(db, style_cc, model_code), style_cc=style_cc, model_code=model_code, product_family=(d.get("product_family") or None),
                          description=d.get("description") or "", created_by=user.username)
    db.add(p)
    try:
        db.commit()
    except IntegrityError:
        # an toàn cuối cùng cho race condition (2 request đồng thời cùng style/model) — trả business error, không 500 (GPT review #4 mục 6)
        db.rollback()
        raise HTTPException(409, f"Đã có Technology Process cho Style {style_cc}" + (f" / Model {model_code}" if model_code else "")) from None
    write_audit("TECH_PROCESS_CREATE", user=user, object_type="TechnologyProcess", object_id=p.process_code, detail=f"{style_cc}/{model_code or '-'}")
    return p


def get_process(db: Session, process_id: int) -> TechnologyProcess:
    p = db.get(TechnologyProcess, process_id)
    if p is None:
        raise HTTPException(404, "Không tìm thấy Technology Process")
    return p


def get_or_create_process(db: Session, user: User, style_cc: str, model_code: str, product_family: str | None = None) -> TechnologyProcess:
    style_cc, model_code = _canon_key(style_cc), _canon_key(model_code)
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


# Số lần thử lại khi 2 request đồng thời cùng tính ra một version_no (GPT review vòng 2 mục 2) — unique constraint
# uq_tpv_process_layer_version là lưới an toàn cuối, nhưng người dùng không được thấy 500 vì tranh chấp version_no.
_MAX_VERSION_NO_RETRIES = 5


def create_draft_version(db: Session, user: User, process_id: int, d: dict) -> TechnologyProcessVersion:
    p = get_process(db, process_id)
    d = {**d, "layer": d.get("layer")}
    _validate_version_fields(d)
    last_error: IntegrityError | None = None
    for _attempt in range(_MAX_VERSION_NO_RETRIES):
        v = TechnologyProcessVersion(
            technology_process_id=p.id, layer=d["layer"], version_no=_next_version_no(db, p.id, d["layer"]), status="DRAFT",
            source_type=d.get("source_type") or "MANUAL", source_ref=d.get("source_ref") or None, source_date=d.get("source_date"),
            derived_from_version_id=d.get("derived_from_version_id"), effective_from=d.get("effective_from"), effective_to=d.get("effective_to"),
            expected_output_per_day=d.get("expected_output_per_day"), required_labor=d.get("required_labor"), assumptions_json=d.get("assumptions_json") or {},
            note=d.get("note") or "", created_by=user.username,
        )
        db.add(v)
        try:
            db.commit()
        except IntegrityError as e:
            # va chạm version_no với request đồng thời khác (BR-005 unique) -> rollback, tính lại version_no, thử lại
            db.rollback()
            last_error = e
            continue
        write_audit("TECH_PROCESS_VERSION_CREATE", user=user, object_type="TechnologyProcessVersion", object_id=str(v.id), detail=f"{p.process_code} {v.layer} v{v.version_no}")
        return v
    raise HTTPException(409, f"Không thể tạo version mới cho layer {d['layer']} do tranh chấp số phiên bản, vui lòng thử lại") from last_error


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
    # note/assumptions_json là cột NOT NULL (default "" / {}) — null tường minh được hiểu là "xóa nội dung", không phải lỗi (GPT review #4 mục 5)
    if "note" in d and d["note"] is None:
        d = {**d, "note": ""}
    if "assumptions_json" in d and d["assumptions_json"] is None:
        d = {**d, "assumptions_json": {}}
    for k in ("source_ref", "source_date", "effective_from", "effective_to", "expected_output_per_day", "required_labor", "assumptions_json", "note"):
        if k in d:
            setattr(v, k, d[k])
    db.commit()
    write_audit("TECH_PROCESS_VERSION_UPDATE", user=user, object_type="TechnologyProcessVersion", object_id=str(v.id), detail="cập nhật thông tin version")
    return v


# ------------------------------------------------------------------ Total SAM (BR-016, BR-017)
def _sam_summary(operations) -> tuple[float | None, str]:
    """Hàm thuần (không đụng DB) — dùng chung cho recalc_total_sam và bootstrap atomic (GPT review #4 mục 1)."""
    active = [op for op in operations if op.is_active]
    if not active:
        return None, "EMPTY"
    if any(op.sam_minutes is None for op in active):
        return None, "INCOMPLETE"  # BR-017 — không lấy median/default Style khác lấp vào
    return round(sum(op.sam_minutes for op in active), 4), "COMPLETE"


def recalc_total_sam(db: Session, v: TechnologyProcessVersion) -> TechnologyProcessVersion:
    v.total_sam_minutes, v.sam_status = _sam_summary(v.operations)
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


# Cột NOT NULL trên TechnologyProcessOperation — null tường minh trên các trường này không có nghĩa nghiệp vụ hợp lệ
# (khác với các cột nullable như sam_minutes/machine_type_code, nơi null nghĩa là "chưa có/xóa giá trị" hợp lệ). GPT review #4 mục 5.
_OPERATION_NOT_NULLABLE = ("sequence_no", "operation_code", "operation_name", "operator_count", "automation_level", "source_type", "evidence_note")


def update_operation(db: Session, user: User, operation_id: int, d: dict) -> TechnologyProcessOperation:
    op = db.get(TechnologyProcessOperation, operation_id)
    if op is None:
        raise HTTPException(404, "Không tìm thấy công đoạn")
    v = get_version(db, op.process_version_id)
    _guard_editable(v)
    bad_null = [k for k in _OPERATION_NOT_NULLABLE if k in d and d[k] is None]
    if bad_null:
        raise _bad(f"Trường {', '.join(bad_null)} không được để trống (null)")
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
    """So sánh các version — CHỈ trong cùng một TechnologyProcess (GPT review #4 mục 4): so Style/Model khác nhau
    dễ gây hiểu nhầm là các phương án của cùng một mã hàng, nên bị từ chối tường minh thay vì âm thầm trả kết quả."""
    versions = [get_version(db, vid) for vid in version_ids]
    process_ids = {v.technology_process_id for v in versions}
    if len(process_ids) > 1:
        raise _bad("Chỉ so sánh được các version của cùng một Technology Process (cùng Style/Model)")
    out = []
    for v in versions:
        active = [op for op in v.operations if op.is_active]
        machines = sorted({(op.machine_type_code or "", op.machine_model_id) for op in active if op.machine_type_code or op.machine_model_id})
        out.append({**version_view(v), "process_code": v.technology_process.process_code, "style_cc": v.technology_process.style_cc, "model_code": v.technology_process.model_code,
                    "operation_count": len(active), "machine_summary": [{"machine_type_code": mt, "machine_model_id": mid} for mt, mid in machines]})
    return out


# ------------------------------------------------------------------ Bootstrap / import Current Process (§11)
# BR: KHÔNG tự query ERP trong Task 1 (Known Gap) — nhận input đã chuẩn hóa qua service/API (manual/controlled bootstrap).

# Toàn bộ trường nghiệp vụ của một operation trong payload bootstrap tham gia fingerprint (GPT review #4 mục 2) —
# đổi bất kỳ trường nào trong danh sách này phải ra fingerprint khác. `note` (ghi chú tự do cấp version) CHỦ Ý không tham gia vì
# là metadata mô tả, không ảnh hưởng nội dung kỹ thuật của Current Process.
_BOOTSTRAP_OP_FINGERPRINT_FIELDS = (
    "sequence_no", "operation_code", "operation_name", "machine_type_code", "machine_model_id", "operator_count", "helper_count", "sam_minutes",
    "cycle_time_seconds", "expected_output_per_day", "automation_level", "setup_changeover_minutes", "expected_defect_rate", "source_type", "evidence_note", "evidence_ref", "source_date",
)


def _canon(v):
    if isinstance(v, date):
        return v.isoformat()
    return v


def _fingerprint(style_cc: str, model_code: str, layer: str, source_ref: str, source_date_: date | None, operations: list[dict]) -> str:
    """Canonical JSON (sort_keys, thứ tự operation deterministic theo sequence_no rồi operation_name) -> SHA-256.
    GPT review #4 mục 2: hash phải đại diện đầy đủ business fields của payload, không chỉ 4 field như bản cũ."""
    ops_canon = [{k: _canon(o.get(k)) for k in _BOOTSTRAP_OP_FINGERPRINT_FIELDS} for o in sorted(operations, key=lambda o: (o.get("sequence_no") or 0, o.get("operation_name") or ""))]
    payload = {"style_cc": style_cc, "model_code": model_code, "layer": layer, "source_ref": source_ref, "source_date": _canon(source_date_), "operations": ops_canon}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def bootstrap_current_process(db: Session, user: User, d: dict) -> dict:
    """Bootstrap thủ công/normalized có kiểm soát cho Current Process (BR-011, BR-015). KHÔNG tự nối ERP sống trong Task 1.

    Atomic (GPT review #4 mục 1): validate TOÀN BỘ operation trước (đọc-only), kiểm tra idempotency trước khi ghi bất kỳ dòng nào,
    sau đó insert process/version/operation và chỉ COMMIT MỘT LẦN ở cuối. Bất kỳ lỗi nào trước commit -> rollback toàn bộ,
    không bao giờ để lại version có bootstrap_fingerprint nhưng operation dở dang."""
    style_cc, model_code = _canon_key(d.get("style_cc")), _canon_key(d.get("model_code"))
    if not style_cc:
        raise _bad("Cần Style/CC")
    operations = d.get("operations") or []
    if not operations:
        raise _bad("Cần ít nhất một operation để bootstrap")
    source_ref = (d.get("source_ref") or "").strip()
    if not source_ref:
        raise _bad("Cần source_ref (bằng chứng nguồn) cho bootstrap — không được để trống")
    source_date_ = d.get("source_date")

    # 1) Validate + chuẩn hóa TOÀN BỘ operation trước — chưa ghi gì vào DB (chỉ đọc MachineType/MachineModel để kiểm tra)
    seen_seq: set = set()
    norm_ops: list[dict] = []
    for i, raw_od in enumerate(operations, start=1):
        od = {**raw_od, "sequence_no": raw_od.get("sequence_no") or i, "source_type": raw_od.get("source_type") or "IMPORT"}
        if not (od.get("operation_name") or "").strip():
            raise _bad(f"Operation #{i}: cần operation_name")
        if od["sequence_no"] in seen_seq:
            raise _bad(f"Thứ tự công đoạn {od['sequence_no']} bị trùng trong payload bootstrap")
        seen_seq.add(od["sequence_no"])
        _validate_operation(db, od)
        norm_ops.append(od)

    fp = _fingerprint(style_cc, model_code, "CURRENT_PROCESS", source_ref, source_date_, norm_ops)

    # 2) Idempotency check TRƯỚC khi ghi (BR-015) — nếu đã có version cùng fingerprint, trả nguyên trạng, không đụng DB
    existing_process = db.query(TechnologyProcess).filter(TechnologyProcess.style_cc == style_cc, TechnologyProcess.model_code == model_code).first()
    if existing_process is not None:
        existing_version = db.query(TechnologyProcessVersion).filter(TechnologyProcessVersion.technology_process_id == existing_process.id,
                                                                       TechnologyProcessVersion.layer == "CURRENT_PROCESS", TechnologyProcessVersion.bootstrap_fingerprint == fp).first()
        if existing_version is not None:
            return {"created": False, "process": process_view(existing_process), "version": version_view(existing_version, True)}

    # 3) Ghi — không commit cho tới khi mọi thứ insert xong; lỗi bất kỳ đâu -> rollback toàn bộ, không tạo process/version dở dang
    try:
        p = existing_process
        if p is None:
            p = TechnologyProcess(process_code=_unique_process_code(db, style_cc, model_code), style_cc=style_cc, model_code=model_code,
                                  product_family=(d.get("product_family") or None), description="", created_by=user.username)
            db.add(p)
            db.flush()  # cần p.id cho version — chưa commit

        v = TechnologyProcessVersion(
            technology_process_id=p.id, layer="CURRENT_PROCESS", version_no=_next_version_no(db, p.id, "CURRENT_PROCESS"), status="DRAFT", source_type="IMPORT",
            source_ref=source_ref, source_date=source_date_, note=d.get("note") or "Bootstrap thủ công — chưa nối live ERP QTCN (Known Gap)",
            created_by=user.username, bootstrap_fingerprint=fp,
        )
        db.add(v)
        db.flush()  # cần v.id cho operation — chưa commit

        ops_added: list[TechnologyProcessOperation] = []
        for od in norm_ops:
            op = TechnologyProcessOperation(
                process_version_id=v.id, sequence_no=od["sequence_no"], operation_code=od.get("operation_code") or "", operation_name=od["operation_name"],
                machine_type_code=od.get("machine_type_code") or None, machine_model_id=od.get("machine_model_id") or None, operator_count=int(od.get("operator_count") or 0),
                helper_count=od.get("helper_count"), sam_minutes=od.get("sam_minutes"), cycle_time_seconds=od.get("cycle_time_seconds"), expected_output_per_day=od.get("expected_output_per_day"),
                automation_level=od.get("automation_level") or "", setup_changeover_minutes=od.get("setup_changeover_minutes"), expected_defect_rate=od.get("expected_defect_rate"),
                source_type=od.get("source_type") or "IMPORT", evidence_note=od.get("evidence_note") or "", evidence_ref=od.get("evidence_ref"), source_date=od.get("source_date"),
                is_active=True,  # đặt tường minh: cột có default ở DB nhưng CHƯA áp dụng cho object Python trước khi flush/commit — _sam_summary() đọc ngay object này
                created_by=user.username,
            )
            db.add(op)
            ops_added.append(op)

        v.total_sam_minutes, v.sam_status = _sam_summary(ops_added)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Đã có Technology Process cho Style {style_cc}" + (f" / Model {model_code}" if model_code else "")) from None
    except Exception:
        db.rollback()
        raise

    db.refresh(v)
    write_audit("TECH_PROCESS_BOOTSTRAP", user=user, object_type="TechnologyProcessVersion", object_id=str(v.id), detail=f"{p.process_code} CURRENT_PROCESS bootstrap ({len(norm_ops)} operation), source_ref={source_ref}")
    return {"created": True, "process": process_view(p), "version": version_view(v, True)}


# ------------------------------------------------------------------ Machine Model / Candidate (§10) — master độc lập, KHÔNG thuộc sở hữu một Process
# Cột NOT NULL trên MachineModel; brand/model/automation_level/source/note là text mô tả nên coi null tường minh = "" (xóa nội dung).
_MACHINE_MODEL_NOT_NULLABLE = ("machine_type_code", "status")


def save_machine_model(db: Session, user: User, d: dict, model_id: int | None = None) -> MachineModel:
    bad_null = [k for k in _MACHINE_MODEL_NOT_NULLABLE if k in d and d[k] is None]
    if bad_null:  # GPT review #4 mục 5 — machine_type_code/status là NOT NULL và có ý nghĩa cấu trúc, null tường minh là lỗi input
        raise _bad(f"Trường {', '.join(bad_null)} không được để trống (null)")
    if d.get("machine_type_code") is not None and not db.get(MachineType, d["machine_type_code"]):
        raise _bad(f"Loại máy '{d['machine_type_code']}' không tồn tại")
    if d.get("status") is not None and d["status"] not in MACHINE_MODEL_STATUSES:
        raise _bad(f"status phải là một trong {MACHINE_MODEL_STATUSES}")
    for k in ("brand", "model", "automation_level", "source", "note"):  # text field NOT NULL — null tường minh -> "" (xóa nội dung, không phải lỗi)
        if k in d and d[k] is None:
            d = {**d, k: ""}
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
