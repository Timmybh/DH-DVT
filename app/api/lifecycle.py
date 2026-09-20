from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import User
from app.models.lifecycle import CarryForwardItem, YearCarryForward
from app.services import lifecycle as svc

router = APIRouter(prefix="/admin/lifecycle", tags=["lifecycle"])
Manage = Depends(require_perm("lifecycle.manage"))


@router.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Manage):
    return svc.year_overview(db)


class CarryBody(BaseModel):
    year: int = Field(ge=2000, le=2100)
    version_id: int | None = None
    include_no_actual: bool = True


@router.post("/carry-forward")
def build(body: CarryBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.carry_forward_view(svc.build_carry_forward(db, body.year, user, body.version_id, body.include_no_actual))


@router.get("/carry-forward/{cf_id}")
def detail(cf_id: int, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0), db: Session = Depends(get_db), _: User = Manage):
    cf = db.get(YearCarryForward, cf_id)
    if cf is None:
        raise HTTPException(404, "Không tìm thấy bản kết chuyển")
    q = db.query(CarryForwardItem).filter(CarryForwardItem.cf_id == cf_id)
    items = q.order_by(CarryForwardItem.factory_code, CarryForwardItem.line_raw, CarryForwardItem.id).offset(offset).limit(limit).all()
    return {**svc.carry_forward_view(cf), "total_items": q.count(), "items": [
        {"row_uid": i.row_uid, "factory_code": i.factory_code, "line": i.line_raw, "po": i.po_number, "style": i.style_cc, "customer": i.customer, "planned_qty": i.planned_qty, "sewn_qty": i.sewn_qty,
         "fg_qty": i.fg_qty, "remaining_qty": i.remaining_qty, "planned_end": i.planned_end.isoformat() if i.planned_end else None, "has_transfer": i.has_transfer, "reason": i.reason} for i in items]}


@router.post("/carry-forward/{cf_id}/apply")
def apply(cf_id: int, db: Session = Depends(get_db), user: User = Manage):
    v = svc.apply_carry_forward(db, cf_id, user)
    return {"version_id": v.id, "code": v.code, "rows": v.row_count, "recheck": v.recheck_result}


@router.get("/archive/{year}/dry-run")
def dry_run(year: int, db: Session = Depends(get_db), _: User = Manage):
    return svc.archive_dry_run(db, year)


class ArchiveBody(BaseModel):
    confirm: str


@router.post("/archive/{year}")
def archive(year: int, body: ArchiveBody, db: Session = Depends(get_db), user: User = Manage):
    if body.confirm != f"ARCHIVE {year}":
        raise HTTPException(422, f'Cần xác nhận bằng cách gõ đúng "ARCHIVE {year}"')
    a = svc.archive_year(db, year, user)
    return {"year": a.year, "status": a.status, "path": a.path, "manifest": a.manifest}


@router.post("/archive/{year}/restore")
def restore(year: int, db: Session = Depends(get_db), user: User = Manage):
    return {"year": year, "restored": svc.restore_year(db, year, user)}
