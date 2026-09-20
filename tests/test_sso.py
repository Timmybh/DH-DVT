"""Luồng Google SSO (mock xác minh token — không gọi mạng)."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.core import SsoConfig, User
from app.services import sso


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[User.__table__, SsoConfig.__table__])
    session = sessionmaker(bind=engine)()
    session.add(SsoConfig(id=1, google_enabled=True, google_client_id="cid.apps.googleusercontent.com", allowed_domains="dongtien.vn"))
    session.add(User(full_name="An", username="an", email="an@dongtien.vn", password_hash="x", role="PLANNER"))
    session.add(User(full_name="Locked", username="lk", email="lk@dongtien.vn", password_hash="x", role="VIEWER", is_active=False))
    session.commit()
    monkeypatch.setattr(sso, "write_audit", lambda *a, **k: None)
    yield session
    session.close()


def fake_token(monkeypatch, info=None, error=None):
    def _verify(credential, client_id):
        if error:
            raise ValueError(error)
        assert client_id == "cid.apps.googleusercontent.com"  # audience phải là Client ID đã cấu hình
        return info

    monkeypatch.setattr(sso, "verify_google_credential", _verify)


def test_success_returns_pre_provisioned_user(db, monkeypatch):
    fake_token(monkeypatch, {"email": "An@DongTien.vn", "email_verified": True})
    assert sso.authenticate_google(db, "tok").username == "an"


@pytest.mark.parametrize(
    "info,code",
    [
        ({"email": "an@evil.com", "email_verified": True}, 403),  # sai domain
        ({"email": "an@dongtien.vn", "email_verified": False}, 401),  # email chưa xác minh
        ({"email": "new@dongtien.vn", "email_verified": True}, 403),  # chưa có tài khoản — không tự tạo
        ({"email": "lk@dongtien.vn", "email_verified": True}, 403),  # tài khoản bị khóa
    ],
)
def test_rejections(db, monkeypatch, info, code):
    fake_token(monkeypatch, info)
    with pytest.raises(HTTPException) as exc:
        sso.authenticate_google(db, "tok")
    assert exc.value.status_code == code


def test_invalid_token_is_401(db, monkeypatch):
    fake_token(monkeypatch, error="Token expired")
    with pytest.raises(HTTPException) as exc:
        sso.authenticate_google(db, "tok")
    assert exc.value.status_code == 401


def test_disabled_sso_is_403(db, monkeypatch):
    cfg = db.get(SsoConfig, 1)
    cfg.google_enabled = False
    db.commit()
    fake_token(monkeypatch, {"email": "an@dongtien.vn", "email_verified": True})
    with pytest.raises(HTTPException) as exc:
        sso.authenticate_google(db, "tok")
    assert exc.value.status_code == 403


def test_empty_domain_list_allows_any_domain(db, monkeypatch):
    db.get(SsoConfig, 1).allowed_domains = ""
    db.add(User(full_name="Ext", username="ext", email="ext@other.com", password_hash="x", role="VIEWER"))
    db.commit()
    fake_token(monkeypatch, {"email": "ext@other.com", "email_verified": True})
    assert sso.authenticate_google(db, "tok").username == "ext"
