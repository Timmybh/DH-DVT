"""Chống dò mật khẩu: khóa tạm tài khoản sau nhiều lần đăng nhập nội bộ sai liên tiếp."""

from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import utcnow
from app.models.core import User
from app.services.audit import write_audit


def check_not_locked(user: User | None) -> None:
    if user is None or not user.locked_until:
        return
    until = user.locked_until
    if until.tzinfo is None:
        from datetime import timezone

        until = until.replace(tzinfo=timezone.utc)
    if until > utcnow():
        minutes = max(1, int((until - utcnow()).total_seconds() // 60) + 1)
        write_audit("LOGIN_LOCAL", user=user, result="DENIED", detail="Tài khoản đang bị khóa tạm do đăng nhập sai nhiều lần")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Tài khoản tạm khóa do đăng nhập sai nhiều lần. Thử lại sau khoảng {minutes} phút.")


def register_failure(db: Session, user: User | None) -> None:
    if user is None:
        return
    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= settings.login_max_failures:
        user.locked_until = utcnow() + timedelta(minutes=settings.login_lockout_minutes)
        user.failed_login_count = 0
        write_audit("ACCOUNT_LOCKED", user=user, object_type="User", object_id=user.username, detail=f"Khóa {settings.login_lockout_minutes} phút sau {settings.login_max_failures} lần sai")
    db.commit()


def register_success(db: Session, user: User) -> None:
    if user.failed_login_count or user.locked_until:
        user.failed_login_count, user.locked_until = 0, None
        db.commit()
