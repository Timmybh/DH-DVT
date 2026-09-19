from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.permissions import permissions_for
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.core import SsoConfig, User
from app.services.audit import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class GoogleLoginRequest(BaseModel):
    credential: str


def _user_payload(user: User) -> dict:
    return {
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
        "permissions": permissions_for(user.role),
    }


def _token_response(user: User, db: Session) -> dict:
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return {"access_token": create_access_token(user.username, user.role), "token_type": "bearer", "user": _user_payload(user)}


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
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        write_audit("LOGIN_LOCAL", user=user, username=ident, result="FAILED", detail="Sai tài khoản hoặc mật khẩu")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sai tài khoản hoặc mật khẩu")
    if not user.allow_local_login:
        write_audit("LOGIN_LOCAL", user=user, result="DENIED", detail="Tài khoản không được phép đăng nhập nội bộ")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tài khoản này chỉ được đăng nhập bằng Google SSO")

    write_audit("LOGIN_LOCAL", user=user, object_type="User", object_id=user.username)
    return _token_response(user, db)


@router.post("/google")
def login_google(payload: GoogleLoginRequest, db: Session = Depends(get_db)) -> dict:
    cfg = _sso(db)
    if not (cfg.google_enabled and cfg.google_client_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Google SSO chưa được bật")
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        info = id_token.verify_oauth2_token(payload.credential, google_requests.Request(), cfg.google_client_id)
    except Exception as exc:  # noqa: BLE001
        write_audit("LOGIN_SSO", result="FAILED", detail=f"Token Google không hợp lệ: {exc}"[:300])
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Không xác thực được tài khoản Google")

    email = (info.get("email") or "").lower()
    if not info.get("email_verified") or "@" not in email:
        write_audit("LOGIN_SSO", username=email, result="FAILED", detail="Email chưa xác minh")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email Google chưa được xác minh")

    domains = [d.strip().lower() for d in cfg.allowed_domains.split(",") if d.strip()]
    if domains and email.split("@", 1)[1] not in domains:
        write_audit("LOGIN_SSO", username=email, result="DENIED", detail="Domain không được phép")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Domain email không được phép truy cập")

    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is None or not user.is_active:
        write_audit("LOGIN_SSO", username=email, result="DENIED", detail="Email chưa được cấp tài khoản")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tài khoản chưa được cấp quyền. Liên hệ quản trị viên.")

    write_audit("LOGIN_SSO", user=user, object_type="User", object_id=user.username)
    return _token_response(user, db)


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return _user_payload(user)


@router.post("/logout")
def logout(user: User = Depends(get_current_user)) -> dict:
    write_audit("LOGOUT", user=user, object_type="User", object_id=user.username)
    return {"ok": True}
