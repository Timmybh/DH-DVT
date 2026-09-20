from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_any
from app.core.config import settings
from app.core.permissions import permissions_for, validate_password
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.core import SsoConfig, User
from app.services.audit import write_audit
from app.services.auth_guard import check_not_locked, register_failure, register_success
from app.services.sso import authenticate_google

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class GoogleLoginRequest(BaseModel):
    credential: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def security_warnings(user: User, db: Session) -> list[str]:
    """Cảnh báo cấu hình an toàn — chỉ hiển thị cho quản trị."""
    if user.role != "ADMIN":
        return []
    out = []
    if settings.jwt_secret in ("", "change-me-in-env") or len(settings.jwt_secret) < 32:
        out.append("JWT_SECRET đang là giá trị mặc định/quá ngắn. Đặt chuỗi ngẫu nhiên ≥ 32 ký tự trong .env (python -c \"import secrets;print(secrets.token_urlsafe(48))\").")
    cfg = db.get(SsoConfig, 1)
    if cfg and not cfg.google_enabled and cfg.local_fallback_enabled:
        out.append("Google SSO chưa bật — đang chỉ dùng đăng nhập nội bộ (phương án dự phòng). Cấu hình ở mục Đăng nhập / SSO.")
    return out


def _user_payload(user: User, db: Session | None = None) -> dict:
    return {
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
        "permissions": permissions_for(user.role),
        "must_change_password": user.must_change_password,
        "security_warnings": security_warnings(user, db) if db is not None else [],
    }


def _token_response(user: User, db: Session) -> dict:
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return {"access_token": create_access_token(user.username, user.role, user.token_version or 0), "token_type": "bearer", "user": _user_payload(user, db)}


def _sso(db: Session) -> SsoConfig:
    cfg = db.get(SsoConfig, 1)
    if cfg is None:
        cfg = SsoConfig(id=1)
        db.add(cfg)
        db.commit()
    return cfg


@router.get("/config")
def public_config(db: Session = Depends(get_db)) -> dict:
    """Cấu hình công khai cho màn hình đăng nhập."""
    cfg = _sso(db)
    return {
        "google_enabled": bool(cfg.google_enabled and cfg.google_client_id),
        "google_client_id": cfg.google_client_id if cfg.google_enabled else "",
        "local_enabled": cfg.local_fallback_enabled,
    }


@router.post("/login")
def login_local(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    """Đăng nhập tài khoản nội bộ — chỉ là phương án dự phòng tạm thời/khẩn cấp; mọi lượt đều được audit."""
    cfg = _sso(db)
    ident = payload.username.strip()
    user = db.query(User).filter((func.lower(User.username) == ident.lower()) | (func.lower(User.email) == ident.lower())).first()

    if not cfg.local_fallback_enabled:
        write_audit("LOGIN_LOCAL", username=ident, result="DENIED", detail="Đăng nhập nội bộ đang tắt")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Đăng nhập tài khoản nội bộ đang tắt. Vui lòng dùng Google SSO.")
    check_not_locked(user)
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        write_audit("LOGIN_LOCAL", user=user, username=ident, result="FAILED", detail="Sai tài khoản hoặc mật khẩu")
        register_failure(db, user)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sai tài khoản hoặc mật khẩu")
    if not user.allow_local_login:
        write_audit("LOGIN_LOCAL", user=user, result="DENIED", detail="Tài khoản không được phép đăng nhập nội bộ")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tài khoản này chỉ được đăng nhập bằng Google SSO")

    register_success(db, user)
    write_audit("LOGIN_LOCAL", user=user, object_type="User", object_id=user.username)
    return _token_response(user, db)


@router.post("/google")
def login_google(payload: GoogleLoginRequest, db: Session = Depends(get_db)) -> dict:
    return _token_response(authenticate_google(db, payload.credential), db)


@router.get("/me")
def me(user: User = Depends(get_current_user_any), db: Session = Depends(get_db)) -> dict:
    return _user_payload(user, db)


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, user: User = Depends(get_current_user_any), db: Session = Depends(get_db)) -> dict:
    if not verify_password(payload.current_password, user.password_hash):
        write_audit("PASSWORD_CHANGE", user=user, result="FAILED", detail="Sai mật khẩu hiện tại")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mật khẩu hiện tại không đúng")
    if err := validate_password(payload.new_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, err)
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mật khẩu mới phải khác mật khẩu hiện tại")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.commit()
    write_audit("PASSWORD_CHANGE", user=user, object_type="User", object_id=user.username)
    return _user_payload(user, db)


@router.post("/logout")
def logout(user: User = Depends(get_current_user_any), db: Session = Depends(get_db)) -> dict:
    user.token_version = (user.token_version or 0) + 1  # thu hồi token hiện hành (đăng xuất thật sự, không chỉ xóa phía trình duyệt)
    db.commit()
    write_audit("LOGOUT", user=user, object_type="User", object_id=user.username)
    return {"ok": True}
