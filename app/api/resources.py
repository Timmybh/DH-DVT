from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import User
from app.models.resources import CapacityDefinition, MachineCapacity, MachineRequirement, MachineType
from app.services import resource_service as svc
from app.services.audit import write_audit
from app.services.dashboard import today_local

router = APIRouter(prefix="/planning/resources", tags=["resources"])

View = Depends(require_perm("planning.view"))
Manage = Depends(require_perm("resource.manage"))


# ------------------------------------------------------------------ Capacity Definition
class CapacityBody(BaseModel):
    factory_code: str | None = Field(None, max_length=20)
    line: str | None = Field(None, max_length=20)
    style_cc: str | None = Field(None, max_length=60)
    model_code: str | None = Field(None, max_length=60)
    process: str | None = Field(None, max_length=60)
    worker_count: float | None = None
    working_minutes: float | None = None
    capacity_per_day: float | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    source: str | None = None
    owner: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=300)


@router.get("/capacity")
def list_capacity(status: str = "ACTIVE", factory: str | None = None, q: str | None = None, limit: int = Query(300, ge=1, le=2000), db: Session = Depends(get_db), _: User = View):
    query = db.query(CapacityDefinition)
    if status != "ALL":
        query = query.filter(CapacityDefinition.status == status)
    if factory:
        query = query.filter(CapacityDefinition.factory_code == factory)
    if q:
        like = f"%{q}%"
        query = query.filter(CapacityDefinition.style_cc.ilike(like) | CapacityDefinition.model_code.ilike(like) | CapacityDefinition.line.ilike(like))
    total = query.count()
    rows = query.order_by(CapacityDefinition.factory_code, CapacityDefinition.line, CapacityDefinition.style_cc, CapacityDefinition.version.desc()).limit(limit).all()
    return {"total": total, "rows": [svc.cap_view(c) for c in rows]}


@router.post("/capacity")
def create_capacity(body: CapacityBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.cap_view(svc.create_capacity(db, user, body.model_dump(exclude_unset=True)))


@router.put("/capacity/{cap_id}")
def revise_capacity(cap_id: int, body: CapacityBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.cap_view(svc.revise_capacity(db, user, cap_id, body.model_dump(exclude_unset=True)))


@router.post("/capacity/{cap_id}/retire")
def retire_capacity(cap_id: int, db: Session = Depends(get_db), user: User = Manage):
    return svc.cap_view(svc.retire_capacity(db, user, cap_id))


@router.post("/capacity/import-plan")
def import_capacity(db: Session = Depends(get_db), user: User = Manage):
    return svc.import_capacity_from_plan(db, user)


class ResolveBody(BaseModel):
    factory_code: str = ""
    line: str = ""
    style_cc: str = ""
    model_code: str = ""
    on: date | None = None


@router.post("/capacity/resolve")
def resolve(body: ResolveBody, db: Session = Depends(get_db), _: User = View):
    d = svc.resolve_capacity(svc.load_capacity_defs(db), body.factory_code, body.line, body.style_cc, body.model_code, body.on or today_local())
    return {"found": d is not None, "definition": ({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()} if d else None)}


# ------------------------------------------------------------------ Machine
@router.get("/machine-types")
def machine_types(db: Session = Depends(get_db), _: User = View):
    return [{"code": m.code, "name": m.name, "source": m.source} for m in db.query(MachineType).order_by(MachineType.code)]


class MachineBody(BaseModel):
    factory_code: str | None = None
    line: str | None = None
    machine_type: str | None = None
    quantity: int | None = None
    nominal_output_per_day: float | None = None
    efficiency: float | None = None
    changeover_minutes: float | None = None
    planned_downtime_pct: float | None = None
    maintenance_status: str | None = None
    is_bottleneck: bool | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    notes: str | None = Field(None, max_length=300)
    status: str | None = None


@router.get("/machine-capacity")
def list_machine_capacity(factory: str | None = None, line: str | None = None, db: Session = Depends(get_db), _: User = View):
    q = db.query(MachineCapacity).filter(MachineCapacity.status == "ACTIVE")
    if factory:
        q = q.filter(MachineCapacity.factory_code == factory)
    if line:
        q = q.filter(MachineCapacity.line == line)
    return [svc.machine_cap_view(m) for m in q.order_by(MachineCapacity.factory_code, MachineCapacity.line, MachineCapacity.machine_type).limit(2000)]


@router.post("/machine-capacity")
def create_machine_capacity(body: MachineBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.machine_cap_view(svc.save_machine_capacity(db, user, body.model_dump(exclude_unset=True)))


@router.put("/machine-capacity/{mid}")
def update_machine_capacity(mid: int, body: MachineBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.machine_cap_view(svc.save_machine_capacity(db, user, body.model_dump(exclude_unset=True), mid))


class RequirementBody(BaseModel):
    style_cc: str = Field(..., min_length=1, max_length=60)
    machine_type: str = Field(..., min_length=1, max_length=20)
    quantity: int = Field(..., ge=1)


@router.get("/machine-requirements")
def list_requirements(q: str | None = None, db: Session = Depends(get_db), _: User = View):
    query = db.query(MachineRequirement)
    if q:
        query = query.filter(MachineRequirement.style_cc.ilike(f"%{q}%"))
    return [{"id": r.id, "style_cc": r.style_cc, "machine_type": r.machine_type, "machine_name": r.machine_name, "quantity": r.quantity, "source": r.source}
            for r in query.order_by(MachineRequirement.style_cc, MachineRequirement.machine_type).limit(2000)]


@router.post("/machine-requirements")
def upsert_requirement(body: RequirementBody, db: Session = Depends(get_db), user: User = Manage):
    r = db.query(MachineRequirement).filter_by(style_cc=body.style_cc, machine_type=body.machine_type).first()
    if r is None:
        mt = db.get(MachineType, body.machine_type)
        r = MachineRequirement(style_cc=body.style_cc, machine_type=body.machine_type, machine_name=mt.name if mt else "", quantity=body.quantity, source="MANUAL")
        db.add(r)
    else:
        r.quantity, r.source = body.quantity, "MANUAL"
    db.commit()
    write_audit("MACHINE_REQUIREMENT_SAVE", user=user, object_type="MachineRequirement", object_id=f"{body.style_cc}/{body.machine_type}", detail=f"x{body.quantity}")
    return {"id": r.id}


@router.delete("/machine-requirements/{rid}")
def delete_requirement(rid: int, db: Session = Depends(get_db), user: User = Manage):
    r = db.get(MachineRequirement, rid)
    if r is None:
        raise HTTPException(404, "Không tìm thấy yêu cầu máy")
    write_audit("MACHINE_REQUIREMENT_DELETE", user=user, object_type="MachineRequirement", object_id=f"{r.style_cc}/{r.machine_type}")
    db.delete(r)
    db.commit()
    return {"deleted": True}


# ------------------------------------------------------------------ lao động khả dụng + lịch giải phóng
@router.get("/labor")
def labor(db: Session = Depends(get_db), _: User = View):
    data = svc.latest_labor(db)
    return [{"factory_code": k[0], "line": k[1], "day": v["day"].isoformat(), "present": v["present"], "total": v["total"]} for k, v in sorted(data.items())]


@router.get("/release")
def release(version_id: int, week_start: date | None = None, db: Session = Depends(get_db), _: User = View):
    ws = svc.week_start_of(week_start or today_local())
    return svc.release_for_version(db, version_id, ws)
