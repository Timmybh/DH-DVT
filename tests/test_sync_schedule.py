"""Bảng đăng ký tần suất đồng bộ theo nguồn (sync_schedules)."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.data import SyncSchedule
from app.services import sync_schedule as ss

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[SyncSchedule.__table__])
    s = sessionmaker(bind=engine)()
    ss.ensure_defaults(s)
    return s


def _now(h, m=0):
    return datetime(2026, 9, 26, h, m, tzinfo=TZ)


def test_defaults_seeded_once(db):
    ss.ensure_defaults(db)
    rows = db.query(SyncSchedule).all()
    assert [r.code for r in rows] == ["HIPRO_LINE_OUTPUT"] and rows[0].mode == "INTERVAL" and rows[0].interval_minutes == 30


def test_interval_due_rules(db):
    r = db.query(SyncSchedule).one()
    assert ss.is_due(r, _now(5, 59)) is False and ss.is_due(r, _now(20, 1)) is False        # ngoài khung giờ
    assert ss.is_due(r, _now(8)) is True                                                       # chưa từng chạy
    r.last_run_at = _now(8).astimezone(timezone.utc)
    assert ss.is_due(r, _now(8, 29)) is False and ss.is_due(r, _now(8, 30)) is True            # đủ chu kỳ mới chạy
    r.enabled = False
    assert ss.is_due(r, _now(12)) is False


def test_daily_due_once_per_day(db):
    r = db.query(SyncSchedule).one()
    r.mode, r.daily_time = "DAILY", "05:00"
    assert ss.is_due(r, _now(4, 59)) is False and ss.is_due(r, _now(5)) is True
    r.last_run_at = _now(5, 1).astimezone(timezone.utc)
    assert ss.is_due(r, _now(15)) is False
    r.last_run_at = (_now(5, 1) - timedelta(days=1)).astimezone(timezone.utc)
    assert ss.is_due(r, _now(6)) is True


def test_validation(db):
    r = db.query(SyncSchedule).one()
    for bad in ({"mode": "WEEKLY"}, {"interval_minutes": 1}, {"interval_minutes": 5000}, {"daily_time": "25:00"}, {"window_start": "21:00", "window_end": "08:00"}):
        with pytest.raises(HTTPException) as e:
            ss.validate_and_apply(r, bad, "admin")
        assert e.value.status_code == 422
    ss.validate_and_apply(r, {"interval_minutes": 15, "window_start": "07:00", "window_end": "18:30"}, "admin")
    assert (r.interval_minutes, r.window_start, r.window_end, r.updated_by) == (15, "07:00", "18:30", "admin")


def test_run_due_records_result_and_failure_is_isolated(db, monkeypatch):
    calls = []
    monkeypatch.setitem(ss.RUNNERS, "HIPRO_LINE_OUTPUT", lambda d: calls.append(1) or {"read": 42, "inserted": 3, "updated": 1, "deleted": 0, "unchanged": 38})
    assert ss.run_due(db, _now(9)) == ["HIPRO_LINE_OUTPUT"]
    r = db.query(SyncSchedule).one()
    assert (r.last_status, r.last_rows, r.last_changed) == ("SUCCEEDED", 42, 4) and r.last_run_at is not None
    assert ss.run_due(db, _now(9, 5)) == []                                                    # chưa đủ 30 phút
    monkeypatch.setitem(ss.RUNNERS, "HIPRO_LINE_OUTPUT", lambda d: (_ for _ in ()).throw(RuntimeError("HiPro mất kết nối")))
    ss.run_one(db, r)
    assert r.last_status == "FAILED" and "HiPro mất kết nối" in r.last_error and r.enabled is True


def test_http_schedules(db, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.db.session import get_db
    from app.main import app
    from app.models.core import SyncConfig
    from app.models.data import SyncRun

    Base.metadata.create_all(db.get_bind(), tables=[SyncConfig.__table__, SyncRun.__table__])
    admin = SimpleNamespace(username="admin", role="ADMIN", id=1, is_active=True, must_change_password=False)
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setitem(ss.RUNNERS, "HIPRO_LINE_OUTPUT", lambda d: {"read": 7, "inserted": 0, "updated": 0, "deleted": 0, "unchanged": 7})
    try:
        c = TestClient(app)
        lst = c.get("/api/sync/schedules").json()
        assert [x["code"] for x in lst] == ["EGMF_FULL", "HIPRO_LINE_OUTPUT"] and lst[0]["editable"] is False
        assert c.put("/api/sync/schedules/HIPRO_LINE_OUTPUT", json={"interval_minutes": 10}).json()["interval_minutes"] == 10
        assert c.put("/api/sync/schedules/HIPRO_LINE_OUTPUT", json={"interval_minutes": 1}).status_code == 422
        assert c.put("/api/sync/schedules/EGMF_FULL", json={"enabled": False}).status_code == 404       # lịch eGMF chỉnh ở /sync/config
        assert c.post("/api/sync/schedules/HIPRO_LINE_OUTPUT/run").json()["last_rows"] == 7
    finally:
        app.dependency_overrides.clear()
