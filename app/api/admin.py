from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.core.permissions import ROLES, validate_password
from app.core.security import hash_password
from app.db.session import get_db, utcnow
from app.models.core import AuditLog, SsoConfig, User
from app.services.audit import write_audit

router = APIRouter(prefix="/admin", tags=["admin"])


# ------------------------------------------------------------------ Users
class UserOut(BaseModel):
    id: int
    full_name: str
    username: str
    email: str
    role: str
    is_active: bool
    allow_local_login: bool
    last_login_at: str | None = None


class UserCreate(BaseModel):
    full_name: str
    username: str
    email: str
    password: str
    role: str = "VIEWER"
    allow_local_login: bool = True


class UserUpdate(BaseModel):
    full_name: str
    email: str
    role: str
    is_active: bool
    allow_local_login: bool


class PasswordReset(BaseModel):
    new_password: str


def _out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        full_name=u.full_name,
        username=u.username,
        email=u.email,
        role=u.role,
        is_active=u.is_active,
        allow_local_login=u.allow_local_login,
        last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
    )


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise HTTPException(400, f"Vai trò không hợp lệ. Cho phép: {', '.join(ROLES)}")


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_perm("admin.user_manage"))):
    return [_out(u) for u in db.query(User).order_by(User.id).all()]


@router.post("/users", response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db), actor: User = Depends(require_perm("admin.user_manage"))):
    _check_role(payload.role)
    if err := validate_password(payload.password):
        raise HTTPException(400, err)
    if db.query(User).filter((func.lower(User.username) == payload.username.lower()) | (func.lower(User.email) == payload.email.lower())).first():
        raise HTTPException(400, "Tài khoản hoặc email đã tồn tại")
    user = User(
        full_name=payload.full_name.strip(),
        username=payload.username.strip(),
        email=payload.email.strip().lower(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        allow_local_login=payload.allow_local_login,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    write_audit("USER_CREATE", user=actor, object_type="User", object_id=user.username, detail=f"role={user.role}")
    return _out(user)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), actor: User = Depends(require_perm("admin.user_manage"))):
    _check_role(payload.role)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Không tìm thấy người dùng")
    if user.id == actor.id and (payload.role != "ADMIN" or not payload.is_active):
        raise HTTPException(400, "Không thể tự hạ quyền hoặc khóa chính mình")
    changes = []
    if user.role != payload.role:
        changes.append(f"role {user.role}->{payload.role}")
    if user.is_active != payload.is_active:
        changes.append("kích hoạt" if payload.is_active else "vô hiệu hóa")
    user.full_name, user.email = payload.full_name.strip(), payload.email.strip().lower()
    user.role, user.is_active, user.allow_local_login = payload.role, payload.is_active, payload.allow_local_login
    db.commit()
    db.refresh(user)
    action = "ROLE_CHANGE" if any(c.startswith("role") for c in changes) else "USER_UPDATE"
    write_audit(action, user=actor, object_type="User", object_id=user.username, detail="; ".join(changes))
    return _out(user)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, payload: PasswordReset, db: Session = Depends(get_db), actor: User = Depends(require_perm("admin.user_manage"))):
    if err := validate_password(payload.new_password):
        raise HTTPException(400, err)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Không tìm thấy người dùng")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    write_audit("PASSWORD_RESET", user=actor, object_type="User", object_id=user.username)
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), actor: User = Depends(require_perm("admin.user_manage"))):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Không tìm thấy người dùng")
    if user.id == actor.id:
        raise HTTPException(400, "Không thể xóa chính mình")
    name = user.username
    db.delete(user)
    db.commit()
    write_audit("USER_DELETE", user=actor, object_type="User", object_id=name)
    return {"deleted": True}


# ------------------------------------------------------------------ SSO config
class SsoConfigIO(BaseModel):
    google_enabled: bool
    google_client_id: str = ""
    allowed_domains: str = ""
    redirect_uri: str = ""
    local_fallback_enabled: bool = True


@router.get("/sso", response_model=SsoConfigIO)
def get_sso(db: Session = Depends(get_db), _: User = Depends(require_perm("admin.sso_manage"))):
    cfg = db.get(SsoConfig, 1) or SsoConfig(id=1)
    return SsoConfigIO(
        google_enabled=cfg.google_enabled,
        google_client_id=cfg.google_client_id,
        allowed_domains=cfg.allowed_domains,
        redirect_uri=cfg.redirect_uri,
        local_fallback_enabled=cfg.local_fallback_enabled,
    )


@router.put("/sso", response_model=SsoConfigIO)
def put_sso(payload: SsoConfigIO, db: Session = Depends(get_db), actor: User = Depends(require_perm("admin.sso_manage"))):
    if payload.google_enabled and not payload.google_client_id.strip():
        raise HTTPException(400, "Cần nhập Google Client ID để bật SSO")
    if not payload.google_enabled and not payload.local_fallback_enabled:
        raise HTTPException(400, "Không thể tắt cả Google SSO và đăng nhập nội bộ — sẽ không ai đăng nhập được")
    cfg = db.get(SsoConfig, 1)
    if cfg is None:
        cfg = SsoConfig(id=1)
        db.add(cfg)
    cfg.google_enabled = payload.google_enabled
    cfg.google_client_id = payload.google_client_id.strip()
    cfg.allowed_domains = ",".join(d.strip().lower() for d in payload.allowed_domains.split(",") if d.strip())
    cfg.redirect_uri = payload.redirect_uri.strip()
    cfg.local_fallback_enabled = payload.local_fallback_enabled
    cfg.updated_by, cfg.updated_at = actor.username, utcnow()
    db.commit()
    write_audit("SSO_CONFIG_CHANGE", user=actor, object_type="SsoConfig", object_id="1", detail=f"google={cfg.google_enabled} local={cfg.local_fallback_enabled}")
    return payload


# ------------------------------------------------------------------ Audit log
@router.get("/audit")
def list_audit(
    action: str | None = None,
    username: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_perm("audit.view")),
):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if username:
        q = q.filter(AuditLog.username.ilike(f"%{username}%"))
    total = q.count()
    rows = q.order_by(AuditLog.at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "rows": [
            {
                "id": r.id,
                "at": r.at.isoformat(),
                "username": r.username,
                "action": r.action,
                "object_type": r.object_type,
                "object_id": r.object_id,
                "result": r.result,
                "trace_id": r.trace_id,
                "detail": r.detail,
            }
            for r in rows
        ],
    }


@router.get("/audit/actions")
def audit_actions(db: Session = Depends(get_db), _: User = Depends(require_perm("audit.view"))):
    return [a for (a,) in db.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]
