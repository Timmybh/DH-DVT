from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.core import Factory
from app.models.labor_snapshot import LaborSnapshot, LaborSnapshotLine
from app.services import labor_snapshot as ls
from app.services import snapshots as sn


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def rows(day=date(2026, 9, 20), a=(36, 37), b=(33, 33), c=(30, 31), cday=None):
    return [
        {"factory_code": "XN1", "line": "1", "day": day, "present": a[0], "total": a[1]},
        {"factory_code": "XN1", "line": "2", "day": day, "present": b[0], "total": b[1]},
        {"factory_code": "XN2", "line": "1", "day": cday or day, "present": c[0], "total": c[1]},
    ]


def test_snapshot_takes_latest_per_line_and_skips_unchanged_and_stale(db):
    older = [{"factory_code": "XN1", "line": "1", "day": date(2026, 9, 19), "present": 1, "total": 1}, *rows(), {"factory_code": "XN3", "line": "9", "day": date(2026, 9, 10), "present": 5, "total": 5}]
    s1 = ls.take_snapshot(db, 1, older)
    db.commit()
    assert (s1.as_of_date, s1.lines, s1.stale_lines, s1.present, s1.total) == (date(2026, 9, 20), 3, 1, 99, 101)     # lấy ngày mới nhất mỗi chuyền; XN3/9 quá cũ bị bỏ qua
    assert s1.by_factory["XN1"] == {"lines": 2, "total": 70, "present": 69}
    assert ls.take_snapshot(db, 2, rows()).id == s1.id and db.query(LaborSnapshot).count() == 1                    # số liệu không đổi -> không tạo ảnh chụp trùng
    s2 = ls.take_snapshot(db, 3, rows(a=(20, 37)))
    db.commit()
    assert s2.id != s1.id and db.query(LaborSnapshot).count() == 2 and db.query(LaborSnapshotLine).filter(LaborSnapshotLine.snapshot_id == s1.id).count() == 3   # bản cũ giữ nguyên
    assert ls.take_snapshot(db, 4, []) is None


def test_dashboard_summary_delta_and_trend(db):
    assert ls.dashboard_summary(db) is None
    ls.take_snapshot(db, 1, rows(day=date(2026, 9, 19), a=(30, 37)))
    ls.take_snapshot(db, 2, rows(day=date(2026, 9, 20), a=(36, 37)))
    db.commit()
    s = ls.dashboard_summary(db)
    assert s["as_of"] == "2026-09-20" and s["present"] == 99 and s["attendance_pct"] == round(99 / 101 * 100, 1)
    assert s["previous_as_of"] == "2026-09-19" and s["delta_present"] == 6 and s["by_factory"]["XN1"]["delta_present"] == 6 and s["by_factory"]["XN2"]["delta_present"] == 0
    assert [p["as_of"] for p in s["trend"]] == ["2026-09-19", "2026-09-20"]
    lines = ls.snapshot_lines(db, s["id"], ["XN1"])
    assert [(l.factory_code, l.line) for l in lines] == [("XN1", "1"), ("XN1", "2")]


def test_snapshot_catalog_lists_every_snapshot_table_and_pages_rows(db):
    db.add_all([Factory(id=1, code="XN1", name="XN1")])
    ls.take_snapshot(db, 1, rows())
    db.commit()
    cat = {d["key"]: d for d in sn.catalog(db)}
    for key in ("labor_snapshots", "labor_snapshot_lines", "actual_observations", "po_progress", "po_pack_daily", "qa_defect_daily", "labor_daily", "revenue_daily", "revenue_monthly", "revenue_yearly", "planning_versions", "plan_import_batches"):
        assert key in cat and cat[key]["used_by"] and cat[key]["retention"]
    assert cat["labor_snapshots"]["rows"] == 1 and cat["labor_snapshot_lines"]["rows"] == 3 and cat["labor_snapshots"]["latest"] == "2026-09-20"
    page = sn.rows(db, "labor_snapshot_lines", limit=2, parent_id=1)
    assert page["total"] == 3 and len(page["rows"]) == 2 and page["rows"][0]["factory_code"] == "XN1"
    assert sn.rows(db, "labor_snapshot_lines", factory="XN2")["total"] == 1
    assert sn.rows(db, "labor_snapshot_lines", date_from=date(2026, 9, 21))["total"] == 0
    with pytest.raises(Exception):
        sn.rows(db, "khong_co")
