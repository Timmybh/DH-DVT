from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import User
from app.services import monitoring

router = APIRouter(prefix="/admin/monitoring", tags=["monitoring"])


@router.get("")
def overview(db: Session = Depends(get_db), _: User = Depends(require_perm("monitoring.view"))):
    return monitoring.snapshot(db)
