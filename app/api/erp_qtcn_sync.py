"""API ERP QTCN sync (Task 2 — Issue #5). Permission theo đúng đề xuất đã GPT duyệt (mục 9):
preview/đọc = sync.view; apply = sync.run; resolve exception/quản trị crosswalk = technology_process.manage."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db, utcnow
from app.models.core import User
from app.models.erp_sync import EXCEPTION_CATEGORIES, RESOLUTION_STATUSES, MachineCrosswalk, TechProcessSyncException
from app.services import erp_qtcn_sync as svc
from app.services.audit import write_audit

router = APIRouter(prefix="/planning/technology-process/erp-sync", tags=["erp-qtcn-sync"])

View = Depends(require_perm("sync.view"))
Run = Depends(require_perm("sync.run"))
Manage = Depends(require_perm("technology_process.manage"))


@router.get("/preview")
def preview(db: Session = Depends(get_db), user: User = View):
    try:
        return svc.preview(db, user)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/apply")
def apply(db: Session = Depends(get_db), user: User = Run):
    try:
        result = svc.apply(db, user)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from None
    run = result["run"]
    return {
        "run_id": run.id, "run_code": run.run_code, "status": run.status,
        "created": result["created"], "no_change": result["no_change"], "failed": result["failed"], "exception_count": result["exception_count"],
        "summary": run.summary,
    }


def _exc_out(e: TechProcessSyncException) -> dict:
    return {
        "id": e.id, "sync_run_id": e.sync_run_id, "category": e.category, "source_key": e.source_key, "reason": e.reason,
        "detected_at": e.detected_at.isoformat() if e.detected_at else None, "resolution_status": e.resolution_status,
        "resolution_note": e.resolution_note, "resolved_by": e.resolved_by, "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
    }


@router.get("/exceptions")
def list_exceptions(
    run_id: int | None = None, category: str = "", status: str = "OPEN",
    limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db), _: User = View,
):
    q = db.query(TechProcessSyncException)
    if run_id:
        q = q.filter(TechProcessSyncException.sync_run_id == run_id)
    if category:
        q = q.filter(TechProcessSyncException.category == category)
    if status:
        q = q.filter(TechProcessSyncException.resolution_status == status)
    rows = q.order_by(TechProcessSyncException.detected_at.desc()).limit(limit).all()
    return {"categories": list(EXCEPTION_CATEGORIES), "statuses": list(RESOLUTION_STATUSES), "items": [_exc_out(e) for e in rows]}


class ResolveBody(BaseModel):
    resolution_status: str = Field(..., description="RESOLVED hoặc IGNORED")
    resolution_note: str = Field("", max_length=500)


@router.post("/exceptions/{exception_id}/resolve")
def resolve_exception(exception_id: int, body: ResolveBody, db: Session = Depends(get_db), user: User = Manage):
    e = db.get(TechProcessSyncException, exception_id)
    if e is None:
        raise HTTPException(404, "Không tìm thấy exception")
    if body.resolution_status not in ("RESOLVED", "IGNORED"):
        raise HTTPException(422, "resolution_status phải là RESOLVED hoặc IGNORED")
    e.resolution_status, e.resolution_note = body.resolution_status, body.resolution_note
    e.resolved_by, e.resolved_at = user.username, utcnow()
    db.commit()
    write_audit("TECH_PROCESS_SYNC_EXCEPTION_RESOLVE", user=user, object_type="TechProcessSyncException", object_id=str(e.id), detail=f"{e.category} -> {e.resolution_status}: {e.resolution_note}"[:500])
    return _exc_out(e)


def _cw_out(c: MachineCrosswalk) -> dict:
    return {
        "id": c.id, "source_equipment_code": c.source_equipment_code, "source_equipment_name": c.source_equipment_name,
        "machine_type_code": c.machine_type_code, "match_type": c.match_type, "note": c.note, "created_by": c.created_by,
    }


@router.get("/machine-crosswalk")
def list_crosswalk(db: Session = Depends(get_db), _: User = View):
    return [_cw_out(c) for c in db.query(MachineCrosswalk).order_by(MachineCrosswalk.source_equipment_code).all()]


class CrosswalkBody(BaseModel):
    source_equipment_code: str = Field(..., max_length=50)
    source_equipment_name: str = Field("", max_length=500)
    machine_type_code: str = Field(..., max_length=20)
    note: str = Field("", max_length=300)


@router.post("/machine-crosswalk")
def confirm_crosswalk(body: CrosswalkBody, db: Session = Depends(get_db), user: User = Manage):
    """Người dùng xác nhận thủ công 1 mapping POSSIBLE/UNMAPPED -> match_type=MANUAL_CONFIRMED (BR-212/213 — không tự suy đoán)."""
    from app.models.resources import MachineType

    if not db.get(MachineType, body.machine_type_code):
        raise HTTPException(422, f"Loại máy '{body.machine_type_code}' không tồn tại")
    c = db.query(MachineCrosswalk).filter(MachineCrosswalk.source_system == svc.SOURCE, MachineCrosswalk.source_equipment_code == body.source_equipment_code).first()
    if c is None:
        c = MachineCrosswalk(source_system=svc.SOURCE, source_equipment_code=body.source_equipment_code, created_by=user.username)
        db.add(c)
    c.source_equipment_name, c.machine_type_code, c.match_type, c.note = body.source_equipment_name, body.machine_type_code, "MANUAL_CONFIRMED", body.note
    db.commit()
    write_audit("TECH_PROCESS_MACHINE_CROSSWALK_CONFIRM", user=user, object_type="MachineCrosswalk", object_id=str(c.id), detail=f"{c.source_equipment_code} -> {c.machine_type_code}")
    return _cw_out(c)
