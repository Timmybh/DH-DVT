"""Chống dò mật khẩu (khóa tạm) và thu hồi token."""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token
from app.db.session import Base, utcnow
from app.models.core import User
from app.services import auth_guard


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[User.__table__])
    session = sessionmaker(bind=engine)()
    session.add(User(full_name="An", username="an", email="an@x.vn", password_hash="x", role="PLANNER"))
    session.commit()
    monkeypatch.setattr(auth_guard, "write_audit", lambda *a, **k: None)
    yield session
    session.close()


def test_account_locks_after_repeated_failures_and_unlocks_on_success_or_expiry(db):
    u = db.query(User).one()
    for _ in range(settings.login_max_failures - 1):
        auth_guard.register_failure(db, u)
        auth_guard.check_not_locked(u)                         # chưa khóa
    auth_guard.register_failure(db, u)                          # lần thứ N
    assert u.locked_until is not None and u.failed_login_count == 0
    with pytest.raises(HTTPException) as e:
        auth_guard.check_not_locked(u)
    assert e.value.status_code == 429
    u.locked_until = utcnow() - timedelta(seconds=1)            # hết hạn khóa
    auth_guard.check_not_locked(u)
    auth_guard.register_success(db, u)
    assert u.locked_until is None and u.failed_login_count == 0
    auth_guard.check_not_locked(None)                            # tài khoản không tồn tại: không lộ thông tin qua lỗi khóa
    auth_guard.register_failure(db, None)


def test_token_carries_version_for_revocation():
    tok = create_access_token("an", "PLANNER", 3)
    assert decode_access_token(tok)["tv"] == 3
    assert decode_access_token(create_access_token("an", "PLANNER"))["tv"] == 0
