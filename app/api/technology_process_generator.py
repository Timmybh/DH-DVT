"""API Optimized Current Technology Proposal Generator (Task 3 — Issue #7). Permission theo đúng đề xuất đã duyệt
(mục 13 Issue): preview/compare/đọc = technology_process.view; generate + quản trị compatibility = technology_process.manage."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import User
from app.services import technology_process_generator as gen

router = APIRouter(prefix="/planning/technology-process", tags=["technology-process-generator"])
# LƯU Ý ROUTING (đã sửa 1 bug thật khi làm live smoke test): mọi route ở đây bắt đầu bằng `/versions/{version_id}/...`
# (nhiều segment) mới an toàn — router `technology_process.py` (đăng ký trước trong main.py) đã có
# `GET /versions/{version_id}` (1 segment). Một route CÙNG SỐ SEGMENT như `/versions/compare-current-optimized`
# (bare, không lồng dưới {version_id}) sẽ bị `/versions/{version_id}` của router kia bắt trước (FastAPI thử theo
# thứ tự đăng ký router), "compare-current-optimized" bị parse như version_id -> 422. Do đó compare ở đây thiết kế
# theo dạng `/versions/{id}/compare-with-source` thay vì endpoint bare `/versions/compare-...`.

View = Depends(require_perm("technology_process.view"))
Manage = Depends(require_perm("technology_process.manage"))


@router.get("/versions/{version_id}/optimized-preview")
def optimized_preview(version_id: int, db: Session = Depends(get_db), _: User = View):
    return gen.preview_optimized_proposal(db, version_id)


class GenerateBody(BaseModel):
    selections: dict[str, int] = Field(default_factory=dict, description="sequence_no (string) -> OperationMachineCompatibility id do người dùng chọn tường minh")


@router.post("/versions/{version_id}/generate-optimized")
def generate_optimized(version_id: int, body: GenerateBody, db: Session = Depends(get_db), user: User = Manage):
    result = gen.generate_optimized_proposal(db, user, version_id, body.selections)
    return {"created": result["created"], "version": result["version"]}


@router.get("/versions/{version_id}/compare-with-source")
def compare_with_source(version_id: int, db: Session = Depends(get_db), _: User = View):
    return gen.compare_with_source(db, version_id)


@router.get("/compatibility")
def list_compatibility(operation_code: str = "", db: Session = Depends(get_db), _: User = View):
    return [gen.compatibility_view(r) for r in gen.list_compatibility(db, operation_code)]


class CompatibilityBody(BaseModel):
    operation_code: str | None = Field(None, max_length=60)
    source_machine_type_code: str | None = Field(None, max_length=20)
    candidate_machine_type_code: str | None = Field(None, max_length=20)
    candidate_machine_model_id: int | None = None
    compatibility_status: str | None = None
    evidence_ref: str | None = Field(None, max_length=200)
    evidence_note: str | None = Field(None, max_length=300)


@router.post("/compatibility")
def create_compatibility(body: CompatibilityBody, db: Session = Depends(get_db), user: User = Manage):
    return gen.compatibility_view(gen.save_compatibility(db, user, body.model_dump(exclude_unset=True)))


@router.put("/compatibility/{compatibility_id}")
def update_compatibility(compatibility_id: int, body: CompatibilityBody, db: Session = Depends(get_db), user: User = Manage):
    return gen.compatibility_view(gen.save_compatibility(db, user, body.model_dump(exclude_unset=True), compatibility_id))
