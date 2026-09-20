from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import User
from app.services import snapshots as svc

router = APIRouter(prefix="/admin/snapshots", tags=["snapshots"])
View = Depends(require_perm("snapshot.view"))


@router.get("")
def catalog(db: Session = Depends(get_db), _: User = View):
    """Danh mục MỌI bảng snapshot / ảnh chụp theo lần đồng bộ (chỉ đọc)."""
    return svc.catalog(db)


@router.get("/{key}")
def dataset_rows(key: str, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), q: str = "", factory: str = "", date_from: date | None = None,
                 date_to: date | None = None, parent_id: int | None = None, db: Session = Depends(get_db), _: User = View):
    return svc.rows(db, key, limit, offset, q, factory, date_from, date_to, parent_id)
