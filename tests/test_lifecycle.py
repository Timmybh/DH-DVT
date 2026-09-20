from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.session import Base
from app.models.actual import ActualMapping, ActualObservation
from app.models.core import Factory
from app.models.data import QaDefectDaily, SyncRun
from app.models.lifecycle import CarryForwardItem, YearArchive, YearCarryForward
from app.models.planning import PlanningVersion, PlanningVersionRow
from app.models.resources import LaborDaily
from app.services import actual_service as asvc
from app.services import lifecycle as lc

ADMIN = SimpleNamespace(username="admin", role="ADMIN")


@pytest.fixture()
def db(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    monkeypatch.setattr(lc, "write_audit", lambda *a, **k: None)
    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    yield session
    session.close()


def version(db, year, status="ISSUED", code=None):
    v = PlanningVersion(code=code or f"{year}.W38.Master.v01", year=year, week=38, major=1, status=status)
    db.add(v)
    db.flush()
    return v


def vrow(db, v, uid, qty=1000, po="PO1", style="S1", xn="XN1", line="4", end=date(2026, 12, 20), transfer=None):
    db.add(PlanningVersionRow(version_id=v.id, row_uid=uid, sequence=1, source_key=f"{po}|{style}", factory_code=xn, primary_line=line, line_raw=line, line_assignments=[line],
                              transfer=transfer, po_number=po, style_cc=style, customer="C", quantity=qty, capacity=500, begin_prod_date=date(2026, 12, 1), end_prod_date=end,
                              warehouse_date=date(2026, 12, 22), extra={"ref": {"worker": 30}}))


def obs(db, run, po="PO1", line="4", sewn=0, fg=0, style="S1", when=datetime(2026, 12, 10, tzinfo=timezone.utc)):
    db.add(ActualObservation(actual_key=f"{po}|XN1|{line}", fingerprint=f"{po}|{style}|C", sync_run_id=run, observed_at=when, po=po, style=style, customer="C", factory_code="XN1",
                             line=line, qty=1000, sewn_qty=sewn, fg_qty=fg, last_seen=date(2026, 12, 10)))


def seed_year(db):
    v = version(db, 2026)
    vrow(db, v, "done", qty=1000, po="PO1")                                           # nhập kho đủ -> đóng
    vrow(db, v, "part", qty=1000, po="PO2", transfer={"from": "4", "to": "5", "effective_date": "2026-12-15", "planned_remaining_qty": 300, "status": "PLANNED"})
    vrow(db, v, "none", qty=500, po="PO3")                                            # chưa có thực tế
    obs(db, 1, po="PO1", sewn=1000, fg=1000)
    obs(db, 2, po="PO2", sewn=700, fg=400)
    obs(db, 1, po="PO2", sewn=100, fg=0, when=datetime(2026, 11, 1, tzinfo=timezone.utc))   # lịch sử cũ của PO2
    db.commit()
    asvc.reconcile(db, "t")
    db.commit()
    return v


def test_carry_forward_carries_only_open_items_with_remaining_quantity_and_validates(db):
    v = seed_year(db)
    cf = lc.build_carry_forward(db, 2026, ADMIN, today=date(2026, 12, 31))
    assert cf.status == "VALIDATED", [c for c in cf.report if not c["ok"]]
    s = cf.summary
    assert s["carried"] == 2 and s["closed"] == 1 and s["source_rows"] == 3
    items = {i.row_uid: i for i in db.query(CarryForwardItem).filter(CarryForwardItem.cf_id == cf.id)}
    assert set(items) == {"part", "none"} and items["part"].remaining_qty == 600 and items["part"].has_transfer and items["none"].reason == "NO_ACTUAL" and items["none"].remaining_qty == 500
    assert s["remaining_qty"] == 1100
    # kiểm tra không chặn nhưng có cảnh báo về mục chưa có thực tế
    assert any(c["code"] == "NO_ACTUAL_ITEMS" and not c["ok"] and not c["blocking"] for c in cf.report)
    # có thể loại các mục chưa có thực tế
    cf2 = lc.build_carry_forward(db, 2026, ADMIN, version_id=v.id, include_no_actual=False, today=date(2026, 12, 31))
    assert cf2.summary["carried"] == 1 and cf2.status == "VALIDATED"


def test_apply_carry_forward_creates_next_year_version_keeping_state(db):
    seed_year(db)
    cf = lc.build_carry_forward(db, 2026, ADMIN, today=date(2026, 12, 31))
    new = lc.apply_carry_forward(db, cf.id, ADMIN)
    assert new.year == 2027 and new.code.startswith("2027.W01.Master") and new.row_count == 2
    rows = {r.row_uid: r for r in db.query(PlanningVersionRow).filter(PlanningVersionRow.version_id == new.id)}
    assert rows["part"].quantity == 600 and rows["part"].transfer["to"] == "5" and rows["part"].extra["carry_forward"]["fg_qty"] == 400
    assert db.get(YearCarryForward, cf.id).status == "APPLIED"
    with pytest.raises(HTTPException):
        lc.apply_carry_forward(db, cf.id, ADMIN)                                       # không áp dụng hai lần


def test_failed_validation_blocks_apply(db):
    seed_year(db)
    cf = lc.build_carry_forward(db, 2026, ADMIN, today=date(2026, 12, 31))
    it = db.query(CarryForwardItem).filter(CarryForwardItem.cf_id == cf.id).first()
    it.remaining_qty = it.planned_qty + 50                                             # dữ liệu hỏng
    lc.validate_carry_forward(db, cf)
    assert cf.status == "FAILED" and any(c["code"] == "REMAINING_RANGE" and not c["ok"] for c in cf.report)
    with pytest.raises(HTTPException):
        lc.apply_carry_forward(db, cf.id, ADMIN)


def test_archive_requires_validated_carry_forward_past_year_and_keeps_current_state(db, monkeypatch):
    monkeypatch.setattr(lc, "_today", lambda: date(2027, 3, 1))
    v = seed_year(db)
    db.add(SyncRun(run_code="SYNC-2026-1", source="EGMF_REVENUE", started_at=datetime(2026, 12, 5, tzinfo=timezone.utc)))
    db.add(QaDefectDaily(factory_id=1, category="INLINE", day=date(2026, 12, 3), defect_count=4))
    db.add(LaborDaily(factory_code="XN1", line="4", day=date(2026, 12, 3), total=30, present=29))
    db.add(Factory(id=1, code="XN1", name="XN1"))
    old = version(db, 2026, status="COMMITTED", code="2026.W20.Master.v01")
    vrow(db, old, "o1")
    db.commit()
    old_id, v_id = old.id, v.id
    with pytest.raises(HTTPException) as e:
        lc.archive_dry_run(db, 2026)
    assert "kết chuyển" in e.value.detail
    lc.build_carry_forward(db, 2026, ADMIN, today=date(2026, 12, 31))
    plan = lc.archive_dry_run(db, 2026)["tables"]
    assert plan["planning_versions"] == 1 and plan["planning_version_rows"] == 1          # phiên bản ISSUED tham chiếu được giữ
    assert plan["actual_observations"] == 1 and plan["qa_defect_daily"] == 1 and plan["labor_daily"] == 1 and plan["sync_runs"] == 1  # chỉ quan sát cũ, không phải trạng thái hiện tại
    arch = lc.archive_year(db, 2026, ADMIN)
    assert arch.status == "ARCHIVED" and sum(m["rows"] for m in arch.manifest.values()) == 6
    assert db.get(PlanningVersion, old_id) is None and db.get(PlanningVersion, v_id) is not None
    assert db.query(ActualObservation).count() == 2 and db.query(QaDefectDaily).count() == 0
    with pytest.raises(HTTPException):
        lc.archive_year(db, 2026, ADMIN)                                                 # đã lưu trữ
    counts = lc.restore_year(db, 2026, ADMIN)
    assert counts["planning_versions"] == 1 and counts["planning_version_rows"] == 1 and counts["actual_observations"] == 1
    assert db.get(PlanningVersion, old_id) is not None and db.query(QaDefectDaily).count() == 1 and db.query(ActualObservation).count() == 3
    assert db.query(YearArchive).one().status == "RESTORED"


def test_archive_rejects_current_year_and_tampered_files(db, monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "_today", lambda: date(2027, 3, 1))
    seed_year(db)
    with pytest.raises(HTTPException):
        lc.archive_dry_run(db, 2027)                                                     # năm hiện hành không được lưu trữ
    lc.build_carry_forward(db, 2026, ADMIN, today=date(2026, 12, 31))
    old = version(db, 2026, status="COMMITTED", code="2026.W21.Master.v01")
    vrow(db, old, "o2")
    db.commit()
    old_id = old.id
    lc.archive_year(db, 2026, ADMIN)
    f = tmp_path / "2026" / "planning_versions.jsonl.gz"
    f.write_bytes(f.read_bytes() + b"x")                                                 # tệp bị sửa
    with pytest.raises(HTTPException) as e:
        lc.restore_year(db, 2026, ADMIN)
    assert "SHA-256" in e.value.detail
    assert db.get(PlanningVersion, old_id) is None                                       # rollback: không phục hồi một nửa


def test_overview_lists_years_with_status_and_policy(db):
    seed_year(db)
    ov = lc.year_overview(db, today=date(2028, 6, 1))
    y = {r["year"]: r for r in ov["years"]}
    assert y[2026]["past"] and y[2026]["due_by_policy"] and y[2026]["counts"]["planning_versions"] == 1 and y[2028]["past"] is False
    assert ov["retention_online_years"] == settings.retention_online_years
