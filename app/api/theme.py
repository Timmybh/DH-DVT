from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import User
from app.services import theme as svc
from app.services.audit import write_audit

router = APIRouter(prefix="/theme", tags=["theme"])


@router.get("")
def read_theme(db: Session = Depends(get_db)):
    """Công khai (cần cho màn hình đăng nhập): chỉ chứa mã màu, không có dữ liệu nghiệp vụ."""
    return svc.get_theme(db)


@router.put("")
def update_theme(body: dict, db: Session = Depends(get_db), user: User = Depends(require_perm("theme.manage"))):
    out = svc.save_theme(db, body.get("tokens", body), user.username)
    write_audit("THEME_UPDATE", user=user, object_type="Theme", object_id=str(out["version"]), detail=str(out["tokens"])[:500])
    return out


@router.post("/reset")
def reset(db: Session = Depends(get_db), user: User = Depends(require_perm("theme.manage"))):
    out = svc.reset_theme(db, user.username)
    write_audit("THEME_RESET", user=user, object_type="Theme", object_id=str(out["version"]))
    return out
