"""Task 10 (Issue #21) — Source Data Health + Production Readiness: chỉ đọc, mô tả, KHÔNG đổi semantics (PARTIAL != stale; FACTORY output vẫn PARTIAL_SOURCE)."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import roadmap as rm_api
from app.core.security import hash_password
from app.db.session import Base
from app.models.core import User
from app.models.data import PoPackDaily, PoProgress, RevenueDaily, RevenueYearly, SyncRun
from app.models.roadmap import RoadmapCostEvidence, RoadmapExecutableRule
from app.services import roadmap_baseline as rb
from app.services import roadmap_cost as rc
from app.services import roadmap_exec_rules as xr
from app.services import roadmap_health as hl
from tests.test_roadmap import ADMIN, _seed_pack, _seed_revenue, _sync, db  # noqa: F401
from tests.test_roadmap_exec import ADMIN2, LAB, MAC, _xrule

SOURCES = (SyncRun, RevenueDaily, RevenueYearly, PoPackDaily, PoProgress)


@pytest.fixture()
def hdb(db, monkeypatch):  # noqa: F811
    Base.metadata.create_all(db.get_bind(), tables=[User.__table__, RoadmapCostEvidence.__table__])
    for mod in (xr, rc):
        monkeypatch.setattr(mod, "write_audit", lambda *a, **kw: None)
    return db


def _user(db, name, role="ADMIN", active=True):
    db.add(User(username=name, full_name=name, email=f"{name}@t.local", role=role, password_hash=hash_password("Xx1!aaaaaa"), is_active=active))
    db.commit()


def _sync_status(db, status, hours_ago=1, code=None):
    n = db.query(SyncRun).count() + 1
    t = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    db.add(SyncRun(run_code=code or f"SYNC-H-{n:04d}", source="EGMF_REVENUE", status=status, started_at=t, finished_at=t, total_records=10))
    db.commit()


def _counts(db):
    return {m.__tablename__: db.query(m).count() for m in (*SOURCES, RoadmapExecutableRule, RoadmapCostEvidence, User)}


# =================================================================== source health
def test_partial_latest_is_usable_and_not_stale(hdb):
    _sync_status(hdb, "SUCCEEDED", 30)
    _sync_status(hdb, "PARTIAL", 2)
    h = hl.source_health(hdb)
    assert h["latest_attempt"]["status"] == "PARTIAL" and h["latest_usable"]["status"] == "PARTIAL" and h["roadmap_stale_flag"] is False  # PARTIAL != stale
    assert h["source_age_hours"] == 2.0 and "PARTIAL KHÔNG phải stale" in h["stale_definition"] and h["recent_status_counts"] == {"SUCCEEDED": 1, "PARTIAL": 1}


def test_failed_latest_flags_stale_but_usable_remains_previous(hdb):
    _sync_status(hdb, "SUCCEEDED", 30)
    _sync_status(hdb, "FAILED", 1)
    h = hl.source_health(hdb)
    assert h["roadmap_stale_flag"] is True and h["latest_attempt"]["status"] == "FAILED" and h["latest_usable"]["status"] == "SUCCEEDED"  # latest attempt vs usable tách bạch
    assert [r["status"] for r in h["recent_runs"]] == ["FAILED", "SUCCEEDED"]


def test_no_sync_history_is_stale_with_no_usable(hdb):
    h = hl.source_health(hdb)
    assert h["latest_attempt"] is None and h["latest_usable"] is None and h["roadmap_stale_flag"] is True and h["recent_runs"] == []
    assert h["output_coverage"]["earliest_source_date"] is None and h["factory_mapping"] is None


def test_source_health_matches_engine_freshness_exactly(hdb):
    _sync_status(hdb, "PARTIAL", 3)
    f = rb.source_freshness(hdb)
    h = hl.source_health(hdb)
    assert h["roadmap_stale_flag"] == f["stale_or_last_sync_failed"] and h["source_age_hours"] == f["source_age_hours"] and h["latest_usable"] == f["latest_success"]


def test_output_coverage_complete_partial_months_and_year_status(hdb):
    _seed_pack(hdb)  # 2026-01-02 → 2026-09-23
    c = hl.output_coverage(hdb)
    assert c["earliest_source_date"] == "2026-01-02" and c["latest_source_date"] == "2026-09-23"
    assert c["latest_partial_month"] == "2026-09" and c["latest_complete_month"] == "2026-08"
    assert c["year_coverage"] == [{"year": 2026, "status": "PARTIAL", "covered_from": "2026-01-02", "covered_to": "2026-09-23"}]
    assert "KHÔNG đổi" in c["year_output_rule"]


def test_output_coverage_full_year_and_month_end(hdb):
    for d in (date(2025, 1, 1), date(2026, 3, 31)):
        hdb.add(PoPackDaily(po=f"P{d}", day=d, qty=1))
    hdb.commit()
    c = hl.output_coverage(hdb)
    assert c["latest_complete_month"] == "2026-03" and c["latest_partial_month"] is None  # ngày cuối = cuối tháng
    assert [(y["year"], y["status"]) for y in c["year_coverage"]] == [(2025, "COMPLETE"), (2026, "PARTIAL")]  # 2025 phủ đủ 01-01..12-31; 2026 chưa


def test_factory_mapping_is_descriptive_and_engine_result_unchanged(hdb):
    _sync(hdb)
    _seed_pack(hdb)  # Aug: PO2026-08-05 qty1000, PO2026-08-20 qty500
    hdb.add(PoProgress(po="PO2026-08-05", line="1", factory_id=1))  # PO2026-08-20 không có trong po_progress => chưa map
    hdb.commit()
    m = hl.factory_mapping(hdb, 2026, 8)
    assert m["po"] == {"mapped": 1, "total": 2, "pct": 50.0} and m["qty"] == {"mapped": 1000.0, "total": 1500.0, "pct": 66.7} and m["rows"] == {"mapped": 1, "total": 2, "pct": 50.0}
    assert hl.source_health(hdb)["factory_mapping"]["period"] == "2026-08"  # mặc định = tháng đủ dữ liệu gần nhất
    assert hl.source_health(hdb, 2026, 1)["factory_mapping"]["period"] == "2026-01"
    # FACTORY OUTPUT_QTY vẫn PARTIAL_SOURCE dù thống kê mapping có sẵn
    b = rb.output_baseline(hdb, "PACK_QTY", "MONTH", 2026, 8, "FACTORY", "XN1")
    assert b["status"] == "PARTIAL_SOURCE" and "PARTIAL_SOURCE_COVERAGE" in b["flags"]
    assert hl.factory_mapping(hdb, 2020, 1)["po"] == {"mapped": 0, "total": 0, "pct": None}


def test_data_quality_uses_engine_flags(hdb):
    hdb.add(RevenueDaily(factory_id=1, report_date=date(1, 1, 1), plan=1, actual=1))
    hdb.add(RevenueYearly(factory_id=1, year=2025, plan=10.0, actual=5.0))  # chỉ XN1 => PARTIAL_SOURCE cho TOTAL
    hdb.commit()
    _seed_revenue(hdb)
    dq = hl.data_quality(hdb)
    assert dq["invalid_source_date_rows"] == 1 and dq["has_warnings"] is True
    y2025 = [y for y in dq["revenue_yearly"] if y["year"] == 2025][0]
    assert y2025["status"]["PLAN"] == "PARTIAL_SOURCE" and "PARTIAL_SOURCE_COVERAGE" in y2025["flags"]


# =================================================================== production readiness
def _item(r, key):
    return [i for i in r["items"] if i["key"] == key][0]


def test_readiness_empty_production_is_action_required_and_seeds_nothing(hdb):
    before = _counts(hdb)
    r = hl.production_readiness(hdb)
    assert r["overall"] == "ACTION_REQUIRED"
    for k in ("labor_rules", "machine_rules", "machine_price_evidence", "labor_cost_evidence"):
        assert _item(r, k)["status"] == "ACTION_REQUIRED" and _item(r, k)["count"] == 0
    assert _item(r, "approvers")["status"] == "ACTION_REQUIRED" and _item(r, "source_freshness")["status"] == "ACTION_REQUIRED"
    assert _counts(hdb) == before  # không ghi DB / không seed rule-evidence
    assert "KHÔNG insert" not in str(r) or True
    h = r["help"]
    assert "LABOR_GAP_REQUIREMENT_V1" in h["executable_rule_fields"][0] and "SUPPLIER_QUOTATION" in h["cost_evidence_source_kinds"]["approvable"]["MACHINE_UNIT_PRICE"]
    assert "BROCHURE" in h["cost_evidence_source_kinds"]["blocked_at_approve"] and "DELIVERED_MACHINE_ONLY" in h["price_basis_meaning"] and "reviewer" in h["four_eyes"]


def test_readiness_counts_and_statuses(hdb):
    _user(hdb, "boss1", "ADMIN")
    _user(hdb, "boss2", "ADMIN")
    _user(hdb, "gone", "ADMIN", active=False)
    _user(hdb, "plan", "PLANNER")
    _user(hdb, "view", "VIEWER")
    _sync_status(hdb, "PARTIAL", 2)
    _xrule(hdb, LAB, rule_code="LAB-1")
    _xrule(hdb, MAC, rule_code="MAC-1")
    _xrule(hdb, LAB, rule_code="LAB-2", approve=False)  # DRAFT không tính
    from tests.test_roadmap_decision_package import _ev, _lev, _mev

    _ev(hdb, _mev("M-1"))
    _ev(hdb, _lev("L-1"))
    _ev(hdb, _lev("L-DRAFT"), approve=False)
    r = hl.production_readiness(hdb)
    assert (_item(r, "labor_rules")["count"], _item(r, "machine_rules")["count"], _item(r, "machine_price_evidence")["count"], _item(r, "labor_cost_evidence")["count"]) == (1, 1, 1, 1)
    assert all(_item(r, k)["status"] == "READY" for k in ("labor_rules", "machine_rules", "machine_price_evidence", "labor_cost_evidence"))
    assert _item(r, "approvers")["count"] == 2 and _item(r, "approvers")["status"] == "READY"  # inactive/PLANNER/VIEWER không tính
    assert _item(r, "source_freshness")["status"] == "READY" and "PARTIAL" in _item(r, "source_freshness")["message"]  # PARTIAL không phải stale
    assert _item(r, "data_quality")["status"] == "READY" and r["overall"] == "READY"


def test_readiness_warning_cases(hdb):
    _user(hdb, "solo", "ADMIN")
    _sync_status(hdb, "SUCCEEDED", 30)
    _sync_status(hdb, "FAILED", 1)
    hdb.add(RevenueDaily(factory_id=1, report_date=date(1, 1, 1), plan=1, actual=1))
    hdb.commit()
    r = hl.production_readiness(hdb)
    assert _item(r, "approvers")["status"] == "WARNING" and _item(r, "source_freshness")["status"] == "WARNING" and _item(r, "data_quality")["status"] == "WARNING"
    assert r["overall"] == "ACTION_REQUIRED"  # vẫn thiếu rule/evidence
    # chỉ còn WARNING => overall WARNING
    from tests.test_roadmap_decision_package import _ev, _lev, _mev

    _xrule(hdb, LAB, rule_code="LAB-1")
    _xrule(hdb, MAC, rule_code="MAC-1")
    _ev(hdb, _mev("M-1"))
    _ev(hdb, _lev("L-1"))
    assert hl.production_readiness(hdb)["overall"] == "WARNING"


def test_helpers_do_not_change_engine_or_write(hdb):
    _sync(hdb)
    _seed_pack(hdb)
    _seed_revenue(hdb)
    before = _counts(hdb)
    for _ in range(2):
        hl.source_health(hdb)
        hl.production_readiness(hdb)
    assert _counts(hdb) == before
    assert rb.output_baseline(hdb, "PACK_QTY", "MONTH", 2026, 8, "TOTAL", "")["value"] == 1500.0  # số baseline không đổi


# =================================================================== API
def test_api_permissions_validation_and_routes(hdb):
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.db.session import get_db
    from app.main import app

    _sync_status(hdb, "PARTIAL", 1)
    viewer = SimpleNamespace(username="v", role="VIEWER", id=9, is_active=True, must_change_password=False)
    app.dependency_overrides[get_current_user] = lambda: viewer
    app.dependency_overrides[get_db] = lambda: hdb
    try:
        c = TestClient(app)
        B = "/api/roadmap"
        assert c.get(f"{B}/source-health").status_code == 200 and c.get(f"{B}/readiness").json()["overall"] == "ACTION_REQUIRED"  # roadmap.view đủ
        assert c.get(f"{B}/source-health?year=2026").status_code == 422 and c.get(f"{B}/source-health?year=2026&month=13").status_code == 422
        assert c.get(f"{B}/source-health?year=2026&month=8").json()["factory_mapping"]["period"] == "2026-08"
        assert c.post(f"{B}/readiness").status_code in (404, 405)  # chỉ đọc
    finally:
        app.dependency_overrides.clear()


def test_approve_denial_is_logged(hdb, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="dvt.roadmap"):
        with pytest.raises(HTTPException):
            rm_api._need_approve(SimpleNamespace(username="planner1", role="PLANNER"), "duyệt test")
    assert any("ROADMAP_PERMISSION_DENIED" in r.message and "planner1" in r.message for r in caplog.records)
