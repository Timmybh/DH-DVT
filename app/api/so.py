from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import User
from app.services import so_service as svc

router = APIRouter(prefix="/planning/so", tags=["so"])


@router.get("")
def list_sos(q: str = "", factory: str = "", status: str = "", limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db),
             _: User = Depends(require_perm("planning.view"))):
    return svc.list_sos(db, q, factory, status, limit, offset)


@router.get("/{so_id}")
def detail(so_id: int, db: Session = Depends(get_db), _: User = Depends(require_perm("planning.view"))):
    return svc.so_detail(db, so_id)


class DescriptionBody(BaseModel):
    description: str = Field(min_length=1, max_length=300)


@router.put("/{so_id}/description")
def update_description(so_id: int, body: DescriptionBody, db: Session = Depends(get_db), user: User = Depends(require_perm("planning.edit"))):
    """Chỉ SO Description được chỉnh; SO Number bất biến."""
    return svc.so_view(svc.update_description(db, so_id, body.description, user))


@router.post("/bulk-issue")
def bulk_issue(db: Session = Depends(get_db), user: User = Depends(require_perm("so.manage"))):
    """Cấp SO TẠM cho dữ liệu hiện có chưa có SO (UAT). Chạy lại an toàn — không cấp lại SO đã có."""
    return svc.bulk_issue_current(db, user.username)
