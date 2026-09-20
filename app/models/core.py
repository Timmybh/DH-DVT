from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="VIEWER")  # ADMIN | PLANNER | VIEWER
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_local_login: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # tăng khi đăng xuất / khóa / đặt lại mật khẩu -> mọi token cũ mất hiệu lực
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Factory(Base):
    __tablename__ = "factories"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # XN1, XN2, XN3
    name: Mapped[str] = mapped_column(String(200))
    sql_xn_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    display_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SsoConfig(Base):
    """Cấu hình đăng nhập (singleton, id=1)."""

    __tablename__ = "sso_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    google_client_id: Mapped[str] = mapped_column(String(300), default="")
    allowed_domains: Mapped[str] = mapped_column(String(500), default="")
    redirect_uri: Mapped[str] = mapped_column(String(500), default="")
    local_fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SyncConfig(Base):
    """Lịch đồng bộ eGMF hằng ngày (singleton, id=1)."""

    __tablename__ = "sync_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    scheduled_time: Mapped[str] = mapped_column(String(5), default="05:00")
    last_scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(100), default="")
    action: Mapped[str] = mapped_column(String(60), index=True)
    object_type: Mapped[str] = mapped_column(String(60), default="")
    object_id: Mapped[str] = mapped_column(String(100), default="")
    result: Mapped[str] = mapped_column(String(20), default="OK")
    trace_id: Mapped[str] = mapped_column(String(40), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
