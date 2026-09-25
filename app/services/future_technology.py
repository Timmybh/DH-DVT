"""Quản trị Future Technology candidate / evidence / compatibility / lifecycle (Task 4 — Issue #9).

- BR-401/403: mỗi candidate + evidence phải có source rõ; không suy đoán theo tên model.
- BR-402/404: lifecycle DISCOVERED..INACTIVE; discovered != approved.
- BR-405: compatibility explicit, validate trạng thái CUỐI của row (bài học Task 3 review).
- Evidence và status history append-only; status đổi + history ghi trong CÙNG một transaction.
- Permission (GPT chốt Issue #9 mục 9): đổi sang/khỏi APPROVED_FOR_FUTURE cần technology_process.approve — kiểm ở API.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import User
from app.models.future_technology import (
    EVIDENCE_BASES,
    EVIDENCE_METRIC_CODES,
    EVIDENCE_SOURCE_KINDS,
    FUTURE_CANDIDATE_STATUSES,
    FUTURE_CANDIDATE_TRANSITIONS,
    FUTURE_COMPATIBILITY_STATUSES,
    IDENTITY_EDITABLE_STATUSES,
    REASON_REQUIRED_TARGETS,
    FutureTechnologyCandidate,
    FutureTechnologyCompatibility,
    FutureTechnologyEvidence,
    FutureTechnologyStatusHistory,
)
from app.models.resources import MachineModel, MachineType
from app.services.audit import write_audit

# Rời DISCOVERED (vào UNDER_REVIEW, gồm reactivate từ INACTIVE) và APPROVED_FOR_FUTURE đều bắt buộc đã có evidence.
EVIDENCE_REQUIRED_TARGETS = ("UNDER_REVIEW", "APPROVED_FOR_FUTURE")


def _bad(msg: str, code: int = 422) -> HTTPException:
    return HTTPException(code, msg)


def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


# ------------------------------------------------------------------ views
def candidate_view(c: FutureTechnologyCandidate) -> dict:
    return {
        "id": c.id, "candidate_code": c.candidate_code, "machine_type_code": c.machine_type_code, "machine_model_id": c.machine_model_id,
        "brand": c.brand, "model_name": c.model_name, "technology_name": c.technology_name, "automation_level": c.automation_level,
        "status": c.status, "status_reason": c.status_reason, "identity_editable": c.status in IDENTITY_EDITABLE_STATUSES,
        "allowed_transitions": list(FUTURE_CANDIDATE_TRANSITIONS.get(c.status, ())),
        "reviewed_by": c.reviewed_by, "reviewed_at": _iso(c.reviewed_at), "approved_by": c.approved_by, "approved_at": _iso(c.approved_at),
        "created_by": c.created_by, "created_at": _iso(c.created_at), "updated_by": c.updated_by, "updated_at": _iso(c.updated_at),
    }


def evidence_view(e: FutureTechnologyEvidence) -> dict:
    return {
        "id": e.id, "candidate_id": e.candidate_id, "source_ref": e.source_ref, "source_kind": e.source_kind, "basis": e.basis, "metric_code": e.metric_code,
        "value": e.value, "unit": e.unit, "evidence_date": _iso(e.evidence_date), "note": e.note, "added_by": e.added_by, "added_at": _iso(e.added_at),
    }


def history_view(h: FutureTechnologyStatusHistory) -> dict:
    return {"id": h.id, "candidate_id": h.candidate_id, "from_status": h.from_status, "to_status": h.to_status, "reason": h.reason, "actor": h.actor, "at": _iso(h.at)}


def compatibility_view(r: FutureTechnologyCompatibility) -> dict:
    return {
        "id": r.id, "candidate_id": r.candidate_id, "operation_code": r.operation_code, "source_machine_type_code": r.source_machine_type_code,
        "compatibility_status": r.compatibility_status, "evidence_ref": r.evidence_ref, "evidence_note": r.evidence_note,
        "created_by": r.created_by, "updated_by": r.updated_by,
    }


# ------------------------------------------------------------------ candidate
def get_candidate(db: Session, candidate_id: int) -> FutureTechnologyCandidate:
    c = db.get(FutureTechnologyCandidate, candidate_id)
    if c is None:
        raise HTTPException(404, "Không tìm thấy Future Technology candidate")
    return c


def list_candidates(db: Session, status: str = "", machine_type: str = "") -> list[FutureTechnologyCandidate]:
    q = db.query(FutureTechnologyCandidate)
    if status:
        q = q.filter(FutureTechnologyCandidate.status == status)
    if machine_type:
        q = q.filter(FutureTechnologyCandidate.machine_type_code == machine_type)
    return q.order_by(FutureTechnologyCandidate.id.desc()).all()


def _validate_candidate_refs(db: Session, machine_type_code: str | None, machine_model_id: int | None) -> None:
    if not (machine_type_code or "").strip():
        raise _bad("Cần machine_type_code")  # GPT chốt: bắt buộc gắn MachineType đã tồn tại
    if not db.get(MachineType, machine_type_code):
        raise _bad(f"Loại máy '{machine_type_code}' không tồn tại — tạo MachineType trước theo danh mục hiện có")
    if machine_model_id is not None:
        mm = db.get(MachineModel, machine_model_id)
        if mm is None:
            raise _bad(f"MachineModel id {machine_model_id} không tồn tại")
        if mm.machine_type_code != machine_type_code:
            raise _bad(f"MachineModel #{machine_model_id} thuộc loại máy '{mm.machine_type_code}', không khớp machine_type_code '{machine_type_code}'")


_TEXT_FIELDS = ("brand", "model_name", "technology_name", "automation_level")


def create_candidate(db: Session, user: User, d: dict) -> FutureTechnologyCandidate:
    machine_type_code = (d.get("machine_type_code") or "").strip()
    machine_model_id = d.get("machine_model_id") or None
    _validate_candidate_refs(db, machine_type_code, machine_model_id)
    if not any((d.get(k) or "").strip() for k in ("brand", "model_name", "technology_name")):
        raise _bad("Cần ít nhất một trong brand / model_name / technology_name để nhận diện candidate")
    c = FutureTechnologyCandidate(
        candidate_code="PENDING", machine_type_code=machine_type_code, machine_model_id=machine_model_id,
        status="DISCOVERED", created_by=user.username, **{k: (d.get(k) or "").strip() for k in _TEXT_FIELDS},
    )
    db.add(c)
    db.flush()
    c.candidate_code = f"FTC-{c.id:06d}"  # bất biến sau khi tạo
    db.add(FutureTechnologyStatusHistory(candidate_id=c.id, from_status=None, to_status="DISCOVERED", reason="created", actor=user.username))
    db.commit()
    write_audit("FUTURE_CANDIDATE_CREATE", user=user, object_type="FutureTechnologyCandidate", object_id=c.candidate_code, detail=f"{c.machine_type_code} {c.brand} {c.model_name}".strip())
    return c


def update_candidate(db: Session, user: User, candidate_id: int, d: dict) -> FutureTechnologyCandidate:
    c = get_candidate(db, candidate_id)
    if c.status not in IDENTITY_EDITABLE_STATUSES:
        raise _bad(f"Chỉ sửa được định danh candidate khi status là {IDENTITY_EDITABLE_STATUSES} (hiện {c.status})", 409)
    if "candidate_code" in d or "status" in d:
        raise _bad("candidate_code bất biến và status chỉ đổi qua transition")
    final_type = d["machine_type_code"] if "machine_type_code" in d else c.machine_type_code
    final_model = d["machine_model_id"] if "machine_model_id" in d else c.machine_model_id
    if "machine_type_code" in d and not (d["machine_type_code"] or "").strip():
        raise _bad("machine_type_code không được để trống")
    _validate_candidate_refs(db, (final_type or "").strip(), final_model or None)
    c.machine_type_code, c.machine_model_id = (final_type or "").strip(), final_model or None
    for k in _TEXT_FIELDS:
        if k in d:
            setattr(c, k, (d[k] or "").strip())
    if not any((getattr(c, k) or "").strip() for k in ("brand", "model_name", "technology_name")):
        raise _bad("Cần ít nhất một trong brand / model_name / technology_name để nhận diện candidate")
    c.updated_by, c.updated_at = user.username, utcnow()
    db.commit()
    write_audit("FUTURE_CANDIDATE_UPDATE", user=user, object_type="FutureTechnologyCandidate", object_id=c.candidate_code, detail=f"{c.machine_type_code} {c.brand} {c.model_name}".strip())
    return c


def transition_candidate(db: Session, user: User, candidate_id: int, to_status: str, reason: str = "") -> FutureTechnologyCandidate:
    """Quyền theo trạng thái (approve khi đổi sang/khỏi APPROVED_FOR_FUTURE) do API kiểm tra — xem `requires_approve`."""
    c = get_candidate(db, candidate_id)
    if to_status not in FUTURE_CANDIDATE_STATUSES:
        raise _bad(f"status phải là một trong {FUTURE_CANDIDATE_STATUSES}")
    if to_status not in FUTURE_CANDIDATE_TRANSITIONS.get(c.status, ()):
        raise _bad(f"Không cho chuyển {c.status} -> {to_status} (cho phép: {list(FUTURE_CANDIDATE_TRANSITIONS.get(c.status, ())) or 'không có'})", 409)
    if to_status in EVIDENCE_REQUIRED_TARGETS and db.query(FutureTechnologyEvidence.id).filter_by(candidate_id=c.id).first() is None:
        # BR-401/403 (PR #10 review mục 1): candidate vào review/được duyệt phải truy được source/evidence — service enforce, không chỉ UI.
        raise _bad(f"Không thể chuyển sang {to_status}: candidate chưa có evidence nào (cần ít nhất 1 evidence có source_ref)", 422)
    reason = (reason or "").strip()
    if (to_status in REASON_REQUIRED_TARGETS or c.status == "INACTIVE") and not reason:
        raise _bad(f"Chuyển sang {to_status} (hoặc kích hoạt lại từ INACTIVE) bắt buộc có reason")
    now = utcnow()
    from_status = c.status
    c.status, c.status_reason = to_status, reason
    if to_status == "UNDER_REVIEW":
        c.reviewed_by, c.reviewed_at = user.username, now
    if to_status == "APPROVED_FOR_FUTURE":
        c.approved_by, c.approved_at = user.username, now
    c.updated_by, c.updated_at = user.username, now
    db.add(FutureTechnologyStatusHistory(candidate_id=c.id, from_status=from_status, to_status=to_status, reason=reason, actor=user.username, at=now))
    db.commit()  # đổi status + history trong CÙNG một transaction
    write_audit("FUTURE_CANDIDATE_TRANSITION", user=user, object_type="FutureTechnologyCandidate", object_id=c.candidate_code, detail=f"{from_status} -> {to_status}" + (f" ({reason})" if reason else ""))
    return c


def requires_approve(from_status: str, to_status: str) -> bool:
    return "APPROVED_FOR_FUTURE" in (from_status, to_status)


def list_history(db: Session, candidate_id: int) -> list[FutureTechnologyStatusHistory]:
    get_candidate(db, candidate_id)
    return db.query(FutureTechnologyStatusHistory).filter_by(candidate_id=candidate_id).order_by(FutureTechnologyStatusHistory.id).all()


# ------------------------------------------------------------------ evidence (append-only)
def add_evidence(db: Session, user: User, candidate_id: int, d: dict) -> FutureTechnologyEvidence:
    c = get_candidate(db, candidate_id)
    source_ref = (d.get("source_ref") or "").strip()
    if not source_ref:
        raise _bad("Evidence bắt buộc có source_ref")  # BR-401/403
    source_kind, basis, metric_code = d.get("source_kind") or "OTHER", d.get("basis") or "CLAIMED", d.get("metric_code") or "OTHER"
    if source_kind not in EVIDENCE_SOURCE_KINDS:
        raise _bad(f"source_kind phải là một trong {EVIDENCE_SOURCE_KINDS}")
    if basis not in EVIDENCE_BASES:
        raise _bad(f"basis phải là một trong {EVIDENCE_BASES}")
    if metric_code not in EVIDENCE_METRIC_CODES:
        raise _bad(f"metric_code phải là một trong {EVIDENCE_METRIC_CODES}")
    value = d.get("value")
    if value is not None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise _bad("value phải là số")
        if value < 0:
            raise _bad("value không được âm")
        if not (d.get("unit") or "").strip():
            raise _bad("Evidence có value thì bắt buộc có unit (BR-410)")
    evidence_date = d.get("evidence_date")
    if isinstance(evidence_date, str) and evidence_date:
        try:
            evidence_date = date.fromisoformat(evidence_date)
        except ValueError:
            raise _bad("evidence_date phải dạng YYYY-MM-DD")
    e = FutureTechnologyEvidence(
        candidate_id=c.id, source_ref=source_ref[:200], source_kind=source_kind, basis=basis, metric_code=metric_code, value=value,
        unit=(d.get("unit") or "").strip(), evidence_date=evidence_date or None, note=(d.get("note") or "")[:300], added_by=user.username,
    )
    db.add(e)
    db.commit()
    write_audit("FUTURE_EVIDENCE_ADD", user=user, object_type="FutureTechnologyCandidate", object_id=c.candidate_code, detail=f"{metric_code}/{basis} from {source_ref}"[:200])
    return e


def list_evidence(db: Session, candidate_id: int) -> list[FutureTechnologyEvidence]:
    get_candidate(db, candidate_id)
    return db.query(FutureTechnologyEvidence).filter_by(candidate_id=candidate_id).order_by(FutureTechnologyEvidence.id).all()


# ------------------------------------------------------------------ compatibility
def list_compatibility(db: Session, operation_code: str = "", candidate_id: int | None = None) -> list[FutureTechnologyCompatibility]:
    q = db.query(FutureTechnologyCompatibility)
    if operation_code:
        q = q.filter(FutureTechnologyCompatibility.operation_code == operation_code)
    if candidate_id:
        q = q.filter(FutureTechnologyCompatibility.candidate_id == candidate_id)
    return q.order_by(FutureTechnologyCompatibility.operation_code, FutureTechnologyCompatibility.id).all()


_COMPAT_REQUIRED = ("operation_code", "candidate_id", "compatibility_status")


def _validate_compat_final(db: Session, operation_code: str, candidate_id: int | None, source_mtc: str | None, status: str | None) -> None:
    if not (operation_code or "").strip():
        raise _bad("Cần operation_code")  # BR-405 — không match fuzzy theo tên
    if candidate_id is None or db.get(FutureTechnologyCandidate, candidate_id) is None:
        raise _bad(f"Future candidate id {candidate_id} không tồn tại")
    if source_mtc and not db.get(MachineType, source_mtc):
        raise _bad(f"Loại máy nguồn '{source_mtc}' không tồn tại")
    if status not in FUTURE_COMPATIBILITY_STATUSES:
        raise _bad(f"compatibility_status không hợp lệ: {status!r} (phải thuộc {FUTURE_COMPATIBILITY_STATUSES})")


def save_compatibility(db: Session, user: User, d: dict, row_id: int | None = None) -> FutureTechnologyCompatibility:
    if row_id is None:
        operation_code = (d.get("operation_code") or "").strip()
        source_mtc = d.get("source_machine_type_code") or None
        status = d.get("compatibility_status") or "PROPOSED"
        _validate_compat_final(db, operation_code, d.get("candidate_id"), source_mtc, status)
        row = FutureTechnologyCompatibility(
            candidate_id=d["candidate_id"], operation_code=operation_code, source_machine_type_code=source_mtc, compatibility_status=status,
            evidence_ref=d.get("evidence_ref"), evidence_note=d.get("evidence_note") or "", created_by=user.username,
        )
        db.add(row)
    else:
        row = db.get(FutureTechnologyCompatibility, row_id)
        if row is None:
            raise HTTPException(404, "Không tìm thấy future compatibility mapping")
        for k in _COMPAT_REQUIRED:
            if k in d and (d[k] is None or (isinstance(d[k], str) and not d[k].strip())):
                raise _bad(f"{k} không được để trống")
        f_op = d["operation_code"].strip() if "operation_code" in d else row.operation_code
        f_cand = d["candidate_id"] if "candidate_id" in d else row.candidate_id
        f_src = d["source_machine_type_code"] if "source_machine_type_code" in d else row.source_machine_type_code
        f_status = d["compatibility_status"] if "compatibility_status" in d else row.compatibility_status
        _validate_compat_final(db, f_op, f_cand, f_src or None, f_status)
        row.operation_code, row.candidate_id, row.source_machine_type_code, row.compatibility_status = f_op, f_cand, f_src or None, f_status
        if "evidence_ref" in d:
            row.evidence_ref = d["evidence_ref"]
        if "evidence_note" in d:
            row.evidence_note = d["evidence_note"] or ""
        row.updated_by, row.updated_at = user.username, utcnow()
    db.commit()
    write_audit("FUTURE_COMPAT_SAVE", user=user, object_type="FutureTechnologyCompatibility", object_id=str(row.id), detail=f"{row.operation_code} <-> candidate#{row.candidate_id} ({row.compatibility_status})")
    return row
