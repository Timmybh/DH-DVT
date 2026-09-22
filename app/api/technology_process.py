"""API Quy trình công nghệ 3 tầng (Task 1 — Issue #3). Permission: technology_process.view/manage/review/approve — backend luôn tự enforce."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import User
from app.models.resources import MachineType
from app.models.technology_process import LAYERS
from app.services import technology_process_service as svc

router = APIRouter(prefix="/planning/technology-process", tags=["technology-process"])

View = Depends(require_perm("technology_process.view"))
Manage = Depends(require_perm("technology_process.manage"))
Review = Depends(require_perm("technology_process.review"))
Approve = Depends(require_perm("technology_process.approve"))


@router.get("/options")
def options(_: User = View):
    return {"layers": list(LAYERS), "layer_label": {"CURRENT_PROCESS": "Current Process", "OPTIMIZED_CURRENT_TECHNOLOGY": "Optimized Current Technology", "FUTURE_TECHNOLOGY": "Future Technology"},
            "statuses": list(svc.VERSION_STATUSES), "source_types": list(svc.SOURCE_TYPES), "machine_model_statuses": list(svc.MACHINE_MODEL_STATUSES)}


# ------------------------------------------------------------------ danh sách (màn hình list, §13)
@router.get("/versions")
def list_versions(style: str = "", model: str = "", layer: str = "", status: str = "", q: str = "", limit: int = Query(500, ge=1, le=2000), db: Session = Depends(get_db), _: User = View):
    return svc.list_versions(db, style, model, layer, status, q, limit)


@router.get("/versions/compare")
def compare(version_ids: str = Query(..., description="Danh sách id, cách nhau bằng dấu phẩy"), db: Session = Depends(get_db), _: User = View):
    try:
        ids = [int(x) for x in version_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(422, "version_ids không hợp lệ") from None
    if not ids:
        raise HTTPException(422, "Cần ít nhất một version_id")
    return svc.compare_versions(db, ids)


@router.get("/versions/{version_id}")
def get_version(version_id: int, db: Session = Depends(get_db), _: User = View):
    v = svc.get_version(db, version_id)
    out = svc.version_view(v, with_operations=True)
    out.update(process_code=v.technology_process.process_code, style_cc=v.technology_process.style_cc, model_code=v.technology_process.model_code)
    return out


class VersionBody(BaseModel):
    layer: str
    source_type: str | None = None
    source_ref: str | None = Field(None, max_length=200)
    source_date: date | None = None
    derived_from_version_id: int | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    expected_output_per_day: float | None = Field(None, ge=0)
    required_labor: int | None = Field(None, ge=0)
    assumptions_json: dict | None = None
    note: str | None = Field(None, max_length=500)


@router.post("/processes/{process_id}/versions")
def create_version(process_id: int, body: VersionBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.version_view(svc.create_draft_version(db, user, process_id, body.model_dump(exclude_unset=True)))


class VersionUpdateBody(BaseModel):
    source_ref: str | None = Field(None, max_length=200)
    source_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    expected_output_per_day: float | None = Field(None, ge=0)
    required_labor: int | None = Field(None, ge=0)
    assumptions_json: dict | None = None
    note: str | None = Field(None, max_length=500)


@router.put("/versions/{version_id}")
def update_version(version_id: int, body: VersionUpdateBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.version_view(svc.update_version(db, user, version_id, body.model_dump(exclude_unset=True)))


class DeriveBody(BaseModel):
    target_layer: str
    source_type: str | None = None
    source_ref: str | None = Field(None, max_length=200)
    note: str | None = Field(None, max_length=500)


@router.post("/versions/{version_id}/derive")
def derive(version_id: int, body: DeriveBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.version_view(svc.derive_version(db, user, version_id, body.target_layer, body.model_dump(exclude={"target_layer"}, exclude_unset=True)), with_operations=True)


@router.post("/versions/{version_id}/recalc-sam")
def recalc_sam(version_id: int, db: Session = Depends(get_db), user: User = Manage):
    v = svc.get_version(db, version_id)
    return svc.version_view(svc.recalc_total_sam(db, v), with_operations=True)


@router.post("/versions/{version_id}/simulate")
def simulate(version_id: int, db: Session = Depends(get_db), user: User = Manage):
    return svc.version_view(svc.simulate_version(db, user, version_id))


@router.post("/versions/{version_id}/review")
def review(version_id: int, db: Session = Depends(get_db), user: User = Review):
    return svc.version_view(svc.transition_version(db, user, version_id, "review"))


@router.post("/versions/{version_id}/approve")
def approve(version_id: int, db: Session = Depends(get_db), user: User = Approve):
    return svc.version_view(svc.transition_version(db, user, version_id, "approve"))


@router.post("/versions/{version_id}/retire")
def retire(version_id: int, db: Session = Depends(get_db), user: User = Approve):
    return svc.version_view(svc.transition_version(db, user, version_id, "retire"))


# ------------------------------------------------------------------ Operation
class OperationBody(BaseModel):
    sequence_no: int | None = Field(None, ge=1)
    operation_code: str | None = Field(None, max_length=60)
    operation_name: str = Field(..., max_length=200)
    machine_type_code: str | None = Field(None, max_length=20)
    machine_model_id: int | None = None
    operator_count: int = Field(0, ge=0)
    helper_count: int | None = Field(None, ge=0)
    sam_minutes: float | None = Field(None, gt=0)
    cycle_time_seconds: float | None = Field(None, ge=0)
    expected_output_per_day: float | None = Field(None, ge=0)
    automation_level: str | None = Field(None, max_length=60)
    setup_changeover_minutes: float | None = Field(None, ge=0)
    expected_defect_rate: float | None = Field(None, ge=0, le=1)
    source_type: str | None = None
    evidence_note: str | None = Field(None, max_length=300)
    evidence_ref: str | None = Field(None, max_length=200)
    source_date: date | None = None


@router.post("/versions/{version_id}/operations")
def add_operation(version_id: int, body: OperationBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.operation_view(svc.add_operation(db, user, version_id, body.model_dump(exclude_unset=True)))


class OperationUpdateBody(OperationBody):
    operation_name: str | None = Field(None, max_length=200)  # PUT: mọi field optional


@router.put("/operations/{operation_id}")
def update_operation(operation_id: int, body: OperationUpdateBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.operation_view(svc.update_operation(db, user, operation_id, body.model_dump(exclude_unset=True)))


class RemoveBody(BaseModel):
    reason: str = Field("", max_length=300)


@router.post("/operations/{operation_id}/remove")
def remove_operation(operation_id: int, body: RemoveBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.operation_view(svc.remove_operation(db, user, operation_id, body.reason))


# ------------------------------------------------------------------ Process
class ProcessBody(BaseModel):
    style_cc: str = Field(..., max_length=60)
    model_code: str | None = Field(None, max_length=60)
    product_family: str | None = Field(None, max_length=60)
    description: str | None = Field(None, max_length=300)


@router.post("/processes")
def create_process(body: ProcessBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.process_view(svc.create_process(db, user, body.model_dump(exclude_unset=True)))


@router.get("/processes/{process_id}")
def get_process(process_id: int, db: Session = Depends(get_db), _: User = View):
    return svc.process_view(svc.get_process(db, process_id), with_versions=True)


# ------------------------------------------------------------------ Bootstrap Current Process (§11) — service boundary, KHÔNG nối live ERP trong Task 1
class BootstrapOperation(BaseModel):
    sequence_no: int | None = Field(None, ge=1)
    operation_code: str | None = Field(None, max_length=60)
    operation_name: str = Field(..., max_length=200)
    machine_type_code: str | None = Field(None, max_length=20)
    operator_count: int = Field(0, ge=0)
    helper_count: int | None = Field(None, ge=0)
    sam_minutes: float | None = Field(None, gt=0)
    evidence_note: str | None = Field(None, max_length=300)


class BootstrapBody(BaseModel):
    style_cc: str = Field(..., max_length=60)
    model_code: str | None = Field(None, max_length=60)
    product_family: str | None = Field(None, max_length=60)
    source_ref: str = Field(..., min_length=1, max_length=200)
    source_date: date | None = None
    note: str | None = Field(None, max_length=500)
    operations: list[BootstrapOperation]


@router.post("/bootstrap")
def bootstrap(body: BootstrapBody, db: Session = Depends(get_db), user: User = Manage):
    d = body.model_dump(exclude_unset=True)
    d["operations"] = [o.model_dump(exclude_unset=True) for o in body.operations]
    return svc.bootstrap_current_process(db, user, d)


# ------------------------------------------------------------------ Machine Model / Candidate (§10)
@router.get("/machine-models")
def list_machine_models(machine_type: str = "", status: str = "", db: Session = Depends(get_db), _: User = View):
    return [svc.machine_model_view(m) for m in svc.list_machine_models(db, machine_type, status)]


@router.get("/machine-types")
def list_machine_types(db: Session = Depends(get_db), _: User = View):
    return [{"code": m.code, "name": m.name} for m in db.query(MachineType).filter(MachineType.status == "ACTIVE").order_by(MachineType.code)]


class MachineModelBody(BaseModel):
    machine_type_code: str | None = Field(None, max_length=20)
    brand: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=100)
    automation_level: str | None = Field(None, max_length=60)
    reference_output: float | None = Field(None, ge=0)
    reference_cycle_time: float | None = Field(None, ge=0)
    required_operator: int | None = Field(None, ge=0)
    source: str | None = Field(None, max_length=100)
    status: str | None = None
    note: str | None = Field(None, max_length=300)


@router.post("/machine-models")
def create_machine_model(body: MachineModelBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.machine_model_view(svc.save_machine_model(db, user, body.model_dump(exclude_unset=True)))


@router.put("/machine-models/{model_id}")
def update_machine_model(model_id: int, body: MachineModelBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.machine_model_view(svc.save_machine_model(db, user, body.model_dump(exclude_unset=True), model_id))
