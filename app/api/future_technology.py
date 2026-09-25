"""API Future Technology & Technology Scouting (Task 4 — Issue #9). Permission tái dùng technology_process.* (không tạo mới):
view/preview/compare/đọc = view; tạo/sửa candidate, evidence, compatibility, generate = manage;
chuyển sang/khỏi APPROVED_FOR_FUTURE cần thêm technology_process.approve (GPT chốt Issue #9 mục 9).

LƯU Ý ROUTING (bài học Task 3): route theo version phải dạng `/versions/{version_id}/...` (nhiều segment) để không bị
`GET /versions/{version_id}` của router technology_process (đăng ký trước) bắt nhầm. Route candidate/compat nằm dưới `/future/...`."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.core.permissions import ROLE_PERMISSIONS
from app.db.session import get_db
from app.models.core import User
from app.models.future_technology import (
    EVIDENCE_BASES,
    EVIDENCE_METRIC_CODES,
    EVIDENCE_SOURCE_KINDS,
    FUTURE_CANDIDATE_STATUSES,
    FUTURE_COMPATIBILITY_STATUSES,
)
from app.services import future_technology as ft
from app.services import future_technology_generator as gen

router = APIRouter(prefix="/planning/technology-process", tags=["future-technology"])

View = Depends(require_perm("technology_process.view"))
Manage = Depends(require_perm("technology_process.manage"))


@router.get("/future/options")
def future_options(_: User = View):
    return {"statuses": list(FUTURE_CANDIDATE_STATUSES), "evidence_source_kinds": list(EVIDENCE_SOURCE_KINDS), "evidence_bases": list(EVIDENCE_BASES),
            "evidence_metric_codes": list(EVIDENCE_METRIC_CODES), "compatibility_statuses": list(FUTURE_COMPATIBILITY_STATUSES)}


# ------------------------------------------------------------------ candidate
class CandidateBody(BaseModel):
    machine_type_code: str | None = Field(None, max_length=20)
    machine_model_id: int | None = None
    brand: str | None = Field(None, max_length=100)
    model_name: str | None = Field(None, max_length=100)
    technology_name: str | None = Field(None, max_length=150)
    automation_level: str | None = Field(None, max_length=60)


@router.get("/future/candidates")
def list_candidates(status: str = "", machine_type: str = "", db: Session = Depends(get_db), _: User = View):
    return [ft.candidate_view(c) for c in ft.list_candidates(db, status, machine_type)]


@router.post("/future/candidates")
def create_candidate(body: CandidateBody, db: Session = Depends(get_db), user: User = Manage):
    return ft.candidate_view(ft.create_candidate(db, user, body.model_dump(exclude_unset=True)))


@router.get("/future/candidates/{candidate_id}")
def get_candidate(candidate_id: int, db: Session = Depends(get_db), _: User = View):
    c = ft.get_candidate(db, candidate_id)
    return {**ft.candidate_view(c), "evidence": [ft.evidence_view(e) for e in ft.list_evidence(db, candidate_id)],
            "history": [ft.history_view(h) for h in ft.list_history(db, candidate_id)]}


@router.put("/future/candidates/{candidate_id}")
def update_candidate(candidate_id: int, body: CandidateBody, db: Session = Depends(get_db), user: User = Manage):
    return ft.candidate_view(ft.update_candidate(db, user, candidate_id, body.model_dump(exclude_unset=True)))


class TransitionBody(BaseModel):
    to_status: str
    reason: str = Field("", max_length=300)


@router.post("/future/candidates/{candidate_id}/transition")
def transition_candidate(candidate_id: int, body: TransitionBody, db: Session = Depends(get_db), user: User = Manage):
    current = ft.get_candidate(db, candidate_id)
    if ft.requires_approve(current.status, body.to_status) and "technology_process.approve" not in ROLE_PERMISSIONS.get(user.role, set()):
        raise HTTPException(403, "Thiếu quyền: technology_process.approve (đổi sang/khỏi APPROVED_FOR_FUTURE)")
    return ft.candidate_view(ft.transition_candidate(db, user, candidate_id, body.to_status, body.reason))


class EvidenceBody(BaseModel):
    source_ref: str | None = Field(None, max_length=200)
    source_kind: str | None = None
    basis: str | None = None
    metric_code: str | None = None
    value: float | None = None
    unit: str | None = Field(None, max_length=30)
    evidence_date: str | None = None
    note: str | None = Field(None, max_length=300)


@router.post("/future/candidates/{candidate_id}/evidence")
def add_evidence(candidate_id: int, body: EvidenceBody, db: Session = Depends(get_db), user: User = Manage):
    return ft.evidence_view(ft.add_evidence(db, user, candidate_id, body.model_dump(exclude_unset=True)))


@router.get("/future/candidates/{candidate_id}/history")
def candidate_history(candidate_id: int, db: Session = Depends(get_db), _: User = View):
    return [ft.history_view(h) for h in ft.list_history(db, candidate_id)]


# ------------------------------------------------------------------ compatibility
class CompatBody(BaseModel):
    candidate_id: int | None = None
    operation_code: str | None = Field(None, max_length=60)
    source_machine_type_code: str | None = Field(None, max_length=20)
    compatibility_status: str | None = None
    evidence_ref: str | None = Field(None, max_length=200)
    evidence_note: str | None = Field(None, max_length=300)


@router.get("/future/compatibility")
def list_compat(operation_code: str = "", candidate_id: int | None = None, db: Session = Depends(get_db), _: User = View):
    return [ft.compatibility_view(r) for r in ft.list_compatibility(db, operation_code, candidate_id)]


@router.post("/future/compatibility")
def create_compat(body: CompatBody, db: Session = Depends(get_db), user: User = Manage):
    return ft.compatibility_view(ft.save_compatibility(db, user, body.model_dump(exclude_unset=True)))


@router.put("/future/compatibility/{compat_id}")
def update_compat(compat_id: int, body: CompatBody, db: Session = Depends(get_db), user: User = Manage):
    return ft.compatibility_view(ft.save_compatibility(db, user, body.model_dump(exclude_unset=True), compat_id))


# ------------------------------------------------------------------ proposal (nested dưới /versions/{version_id}/...)
@router.get("/versions/{version_id}/future-preview")
def future_preview(version_id: int, db: Session = Depends(get_db), _: User = View):
    return gen.preview_future_proposal(db, version_id)


class GenerateFutureBody(BaseModel):
    selections: dict[str, int] = Field(default_factory=dict, description="sequence_no (string) -> FutureTechnologyCompatibility id chọn tường minh")


@router.post("/versions/{version_id}/generate-future")
def generate_future(version_id: int, body: GenerateFutureBody, db: Session = Depends(get_db), user: User = Manage):
    r = gen.generate_future_proposal(db, user, version_id, body.selections)
    return {"created": r["created"], "version": r["version"]}


@router.get("/versions/{version_id}/compare-with-baseline")
def compare_with_baseline(version_id: int, db: Session = Depends(get_db), _: User = View):
    return gen.compare_with_baseline(db, version_id)
