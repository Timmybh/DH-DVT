"""Đăng nhập Google SSO (handoff §34A.1, §34A.4). Tách khỏi router để kiểm thử được (mock việc xác minh token)."""

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.core import SsoConfig, User
from app.services.audit import write_audit


def verify_google_credential(credential: str, client_id: str) -> dict:
    """Xác minh ID token của Google (chữ ký, audience = Client ID, hạn dùng). Tách riêng để test mock."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)


def authenticate_google(db: Session, credential: str) -> User:
    cfg = db.get(SsoConfig, 1)
    if cfg is None or not (cfg.google_enabled and cfg.google_client_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Google SSO chưa được bật")
    try:
        info = verify_google_credential(credential, cfg.google_client_id)
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
    return user
