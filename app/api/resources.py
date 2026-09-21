from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import User
from app.models.resources import LaborStandard, ProductivityGrade, CapacityDefinition, MachineCapacity, MachineMaintenance, MachineRequirement, MachineSharedPool, MachineSharing, MachineStyleOutput, MachineType
from app.services import labor_grade_service as lg
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
def machine_types(all: bool = False, db: Session = Depends(get_db), _: User = View):
    q = db.query(MachineType)
    if not all:
        q = q.filter(MachineType.status == "ACTIVE")
    return [svc.type_view(m) for m in q.order_by(MachineType.code)]


class TypeBody(BaseModel):
    code: str | None = Field(None, max_length=20)
    name: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=60)
    machine_group: str | None = Field(None, max_length=60)
    process: str | None = Field(None, max_length=60)
    nominal_output_per_day: float | None = Field(None, ge=0)
    default_efficiency: float | None = None
    changeover_minutes: float | None = Field(None, ge=0)
    is_bottleneck_capable: bool | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    note: str | None = Field(None, max_length=300)


@router.post("/machine-types")
def create_machine_type(body: TypeBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.type_view(svc.save_machine_type(db, user, body.model_dump(exclude_unset=True)))


@router.put("/machine-types/{code}")
def update_machine_type(code: str, body: TypeBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.type_view(svc.save_machine_type(db, user, body.model_dump(exclude_unset=True), code))


@router.post("/machine-types/{code}/deactivate")
def deactivate_machine_type(code: str, db: Session = Depends(get_db), user: User = Manage):
    return svc.type_view(svc.set_type_status(db, user, code, False))


@router.post("/machine-types/{code}/activate")
def activate_machine_type(code: str, db: Session = Depends(get_db), user: User = Manage):
    return svc.type_view(svc.set_type_status(db, user, code, True))


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
    maintenance_quantity: int | None = Field(None, ge=0)
    down_quantity: int | None = Field(None, ge=0)


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


# ------------------------------------------------------------------ lao động khả dụng + lịch nguồn lực rảnh
@router.get("/labor")
def labor(db: Session = Depends(get_db), _: User = View):
    data = svc.latest_labor(db)
    return [{"factory_code": k[0], "line": k[1], "day": v["day"].isoformat(), "present": v["present"], "total": v["total"]} for k, v in sorted(data.items())]


@router.get("/release")
def release(version_id: int, week_start: date | None = None, db: Session = Depends(get_db), _: User = View):
    ws = svc.week_start_of(week_start or today_local())
    return svc.release_for_version(db, version_id, ws)


# ------------------------------------------------------------------ Cấp 3: mượn máy + lịch bảo trì (không xóa, chỉ Ngưng áp dụng)
class SharingBody(BaseModel):
    machine_type: str | None = Field(None, max_length=20)
    from_factory: str | None = Field(None, max_length=20)
    from_line: str | None = Field(None, max_length=20)
    to_factory: str | None = Field(None, max_length=20)
    to_line: str | None = Field(None, max_length=20)
    quantity: int | None = Field(None, ge=1)
    date_from: date | None = None
    date_to: date | None = None
    reason: str | None = Field(None, max_length=300)


class MaintBody(BaseModel):
    factory_code: str | None = Field(None, max_length=20)
    line: str | None = Field(None, max_length=20)
    machine_type: str | None = Field(None, max_length=20)
    quantity: int | None = Field(None, ge=1)
    date_from: date | None = None
    date_to: date | None = None
    kind: str | None = None
    reason: str | None = Field(None, max_length=300)


class StatusBody(BaseModel):
    reason: str = Field("", max_length=200)


@router.get("/machine-sharing")
def list_sharing(factory: str | None = None, include_inactive: bool = False, db: Session = Depends(get_db), _: User = View):
    q = db.query(MachineSharing)
    if not include_inactive:
        q = q.filter(MachineSharing.status == "ACTIVE")
    if factory:
        q = q.filter((MachineSharing.from_factory == factory) | (MachineSharing.to_factory == factory))
    return [svc.sharing_view(r) for r in q.order_by(MachineSharing.date_from.desc(), MachineSharing.id.desc()).limit(1000)]


@router.post("/machine-sharing")
def create_sharing(body: SharingBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.sharing_view(svc.save_sharing(db, user, body.model_dump(exclude_unset=True)))


@router.post("/machine-sharing/{sid}/deactivate")
def deactivate_sharing(sid: int, body: StatusBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.sharing_view(svc.set_row_status(db, user, MachineSharing, sid, False, body.reason))


@router.post("/machine-sharing/{sid}/activate")
def activate_sharing(sid: int, body: StatusBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.sharing_view(svc.set_row_status(db, user, MachineSharing, sid, True, body.reason))


@router.get("/machine-maintenance")
def list_maintenance(factory: str | None = None, include_inactive: bool = False, db: Session = Depends(get_db), _: User = View):
    q = db.query(MachineMaintenance)
    if not include_inactive:
        q = q.filter(MachineMaintenance.status == "ACTIVE")
    if factory:
        q = q.filter(MachineMaintenance.factory_code == factory)
    return [svc.maint_view(r) for r in q.order_by(MachineMaintenance.date_from.desc(), MachineMaintenance.id.desc()).limit(1000)]


@router.post("/machine-maintenance")
def create_maintenance(body: MaintBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.maint_view(svc.save_maintenance(db, user, body.model_dump(exclude_unset=True)))


@router.post("/machine-maintenance/{mid}/deactivate")
def deactivate_maintenance(mid: int, body: StatusBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.maint_view(svc.set_row_status(db, user, MachineMaintenance, mid, False, body.reason))


@router.post("/machine-maintenance/{mid}/activate")
def activate_maintenance(mid: int, body: StatusBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.maint_view(svc.set_row_status(db, user, MachineMaintenance, mid, True, body.reason))


# ------------------------------------------------------------------ Lao động: cấp 1 danh mục bậc, cấp 2 cơ cấu theo XN/chuyền
@router.get("/productivity-grades")
def list_grades(all: bool = False, db: Session = Depends(get_db), _: User = View):
    q = db.query(ProductivityGrade)
    if not all:
        q = q.filter(ProductivityGrade.status == "ACTIVE")
    return [lg.grade_view(g) for g in q.order_by(ProductivityGrade.grade, ProductivityGrade.effective_from.desc().nullslast(), ProductivityGrade.id.desc())]


class GradeReviseBody(BaseModel):
    productivity_factor: float = Field(..., gt=0, le=1.5)
    effective_from: date
    name: str | None = Field(None, max_length=60)
    note: str | None = Field(None, max_length=300)


@router.post("/productivity-grades/{grade}/revise")
def revise_grade(grade: int, body: GradeReviseBody, db: Session = Depends(get_db), user: User = Manage):
    return lg.grade_view(lg.revise_grade(db, user, grade, body.productivity_factor, body.effective_from, body.name, body.note))


@router.post("/productivity-grades/id/{gid}/deactivate")
def deactivate_grade(gid: int, db: Session = Depends(get_db), user: User = Manage):
    return lg.grade_view(lg.set_grade_status(db, user, gid, False))


@router.post("/productivity-grades/id/{gid}/activate")
def activate_grade(gid: int, db: Session = Depends(get_db), user: User = Manage):
    return lg.grade_view(lg.set_grade_status(db, user, gid, True))


class GradeLine(BaseModel):
    grade: int = Field(..., ge=1, le=10)
    headcount: int = Field(..., ge=0)


class StandardBody(BaseModel):
    factory_code: str | None = Field(None, max_length=20)
    line: str | None = Field(None, max_length=20)
    total_labor: int = Field(..., ge=0)
    effective_from: date
    effective_to: date | None = None
    note: str | None = Field(None, max_length=300)
    details: list[GradeLine]


@router.get("/labor-standards")
def list_standards(factory: str | None = None, on: date | None = None, include_history: bool = False, db: Session = Depends(get_db), _: User = View):
    q = db.query(LaborStandard)
    if not include_history:
        q = q.filter(LaborStandard.status == "ACTIVE")
    if factory:
        q = q.filter(LaborStandard.factory_code == factory)
    rows = q.order_by(LaborStandard.factory_code, LaborStandard.line, LaborStandard.effective_from.desc()).limit(1000).all()
    return [lg.standard_view(db, s, on) for s in rows]


@router.post("/labor-standards")
def create_standard(body: StandardBody, db: Session = Depends(get_db), user: User = Manage):
    d = body.model_dump()
    return lg.standard_view(db, lg.create_standard(db, user, d))


@router.post("/labor-standards/{sid}/revise")
def revise_standard(sid: int, body: StandardBody, db: Session = Depends(get_db), user: User = Manage):
    return lg.standard_view(db, lg.revise_standard(db, user, sid, body.model_dump(exclude_none=True)))


@router.post("/labor-standards/{sid}/deactivate")
def deactivate_standard(sid: int, db: Session = Depends(get_db), user: User = Manage):
    return lg.standard_view(db, lg.set_standard_status(db, user, sid, False))


@router.post("/labor-standards/{sid}/activate")
def activate_standard(sid: int, db: Session = Depends(get_db), user: User = Manage):
    return lg.standard_view(db, lg.set_standard_status(db, user, sid, True))


# ------------------------------------------------------------------ Năng suất loại máy theo mã hàng (chỉ khai báo)
class StyleOutputBody(BaseModel):
    machine_type: str | None = Field(None, max_length=20)
    style_cc: str | None = Field(None, max_length=60)
    output_per_day: float | None = Field(None, gt=0)
    required_quantity: int | None = Field(None, ge=1)
    effective_from: date | None = None
    effective_to: date | None = None
    note: str | None = Field(None, max_length=300)


@router.get("/machine-style-outputs")
def list_style_outputs(machine_type: str | None = None, q: str | None = None, include_inactive: bool = False, db: Session = Depends(get_db), _: User = View):
    query = db.query(MachineStyleOutput)
    if machine_type:
        query = query.filter(MachineStyleOutput.machine_type == machine_type)
    if q:
        query = query.filter(MachineStyleOutput.style_cc.ilike(f"%{q.strip()}%"))
    if not include_inactive:
        query = query.filter(MachineStyleOutput.status == "ACTIVE")
    return [svc.style_output_view(r) for r in query.order_by(MachineStyleOutput.machine_type, MachineStyleOutput.style_cc).limit(2000)]


@router.post("/machine-style-outputs")
def create_style_output(body: StyleOutputBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.style_output_view(svc.save_style_output(db, user, body.model_dump(exclude_unset=True)))


@router.put("/machine-style-outputs/{rid}")
def update_style_output(rid: int, body: StyleOutputBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.style_output_view(svc.save_style_output(db, user, body.model_dump(exclude_unset=True), rid))


@router.post("/machine-style-outputs/{rid}/deactivate")
def deactivate_style_output(rid: int, body: StatusBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.style_output_view(svc.set_row_status(db, user, MachineStyleOutput, rid, False, body.reason))


@router.post("/machine-style-outputs/{rid}/activate")
def activate_style_output(rid: int, body: StatusBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.style_output_view(svc.set_row_status(db, user, MachineStyleOutput, rid, True, body.reason))


# ------------------------------------------------------------------ Đăng ký dùng chung nhiều chuyền
class PoolBody(BaseModel):
    factory_code: str = Field(..., max_length=20)
    machine_type: str = Field(..., max_length=20)
    quantity: int = Field(..., ge=1)
    lines: list[str]
    effective_from: date | None = None
    effective_to: date | None = None
    note: str | None = Field(None, max_length=300)


@router.get("/machine-shared")
def list_shared(factory: str | None = None, include_inactive: bool = False, db: Session = Depends(get_db), _: User = View):
    q = db.query(MachineSharedPool)
    if factory:
        q = q.filter(MachineSharedPool.factory_code == factory)
    if not include_inactive:
        q = q.filter(MachineSharedPool.status == "ACTIVE")
    return [svc.pool_view(r) for r in q.order_by(MachineSharedPool.machine_type, MachineSharedPool.id.desc()).limit(1000)]


@router.post("/machine-shared")
def create_shared(body: PoolBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.pool_view(svc.save_pool(db, user, body.model_dump()))


@router.post("/machine-shared/{pid}/deactivate")
def deactivate_shared(pid: int, body: StatusBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.pool_view(svc.set_row_status(db, user, MachineSharedPool, pid, False, body.reason))


@router.post("/machine-shared/{pid}/activate")
def activate_shared(pid: int, body: StatusBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.pool_view(svc.set_row_status(db, user, MachineSharedPool, pid, True, body.reason))
