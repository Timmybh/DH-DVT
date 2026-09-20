from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base, utcnow
from app.models.core import User
from app.models.data import SyncRun
from app.services import monitoring
from app.services import theme as th


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_theme_validates_and_versions_tokens(db):
    assert th.get_theme(db)["is_default"] and th.get_theme(db)["tokens"]["brand"] == "#4f46e5"
    out = th.save_theme(db, {"brand": "#112233", "status": {"ok": "#00aa00"}, "series": ["#111111", "#222222", "#333333"]}, "admin")
    assert out["version"] == 1 and out["tokens"]["brand"] == "#112233" and out["tokens"]["status"]["ok"] == "#00aa00" and out["tokens"]["status"]["bad"] == th.DEFAULT_TOKENS["status"]["bad"]
    assert th.save_theme(db, {"brand": "#445566"}, "admin")["version"] == 2
    for bad in ({"brand": "red"}, {"brand": "#12345"}, {"brand": "#112233; background:url(x)"}, {"status": {"unknown": "#111111"}}, {"series": ["#111111"]}, {"series": ["#111111", "#222222", "zzz"]}):
        with pytest.raises(HTTPException):
            th.validate_tokens(bad)
    assert th.reset_theme(db, "admin")["tokens"] == th.DEFAULT_TOKENS


def test_monitoring_snapshot_flags_stale_sync_and_locked_accounts(db, monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    db.add(SyncRun(run_code="S1", source="EGMF_REVENUE", status="SUCCEEDED", started_at=utcnow() - timedelta(hours=settings.sync_stale_hours + 10)))
    db.add(User(full_name="A", username="a", email="a@x.vn", password_hash="x", role="VIEWER", locked_until=utcnow() + timedelta(minutes=5)))
    db.commit()
    snap = monitoring.snapshot(db)
    codes = {a["code"] for a in snap["alerts"]}
    assert {"SYNC_STALE", "ACCOUNTS_LOCKED"} <= codes and snap["status"] == "ERROR"
    assert snap["security"]["locked_accounts"] == 1 and snap["database"]["ping_ms"] >= 0 and snap["tables"]["Người dùng"] == 1
    db.add(SyncRun(run_code="S2", source="EGMF_REVENUE", status="SUCCEEDED", started_at=utcnow()))
    db.commit()
    assert "SYNC_STALE" not in {a["code"] for a in monitoring.snapshot(db)["alerts"]}
