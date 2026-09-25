"""Task 5 (Issue #11) — Roadmap Simulation Foundation. Service layer với SQLite in-memory; nguồn revenue/output dựng bằng fixture
(production không bị ghi). Rule fixture APPROVED chỉ tồn tại trong test — hệ thống thật KHÔNG seed rule nào."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import roadmap as rm_api
from app.core.permissions import permissions_for
from app.db.session import Base
from app.models.core import Factory
from app.models.data import PoPackDaily, PoProgress, RevenueDaily, RevenueMonthly, RevenueYearly, SyncRun
from app.models.future_technology import FutureTechnologyCandidate, FutureTechnologyEvidence
from app.models.resources import LaborStandard, LaborStandardGradeDetail, MachineCapacity, MachineModel, MachineType
from app.models.roadmap import (
    RoadmapMilestone,
    RoadmapProposal,
    RoadmapProposalDecisionHistory,
    RoadmapRule,
    RoadmapRun,
    RoadmapRunTargetResult,
    RoadmapScenario,
    RoadmapScenarioVersion,
    RoadmapStatusHistory,
    RoadmapTarget,
    RoadmapTechnologyLink,
)
from app.models.technology_process import TechnologyProcess, TechnologyProcessOperation, TechnologyProcessVersion
from app.services import roadmap as rm
from app.services import roadmap_baseline as rb
from app.services import roadmap_engine as eng

ADMIN = SimpleNamespace(username="admin", role="ADMIN", id=1)
PLANNER = SimpleNamespace(username="planner", role="PLANNER", id=2)
_TABLES = [
    Factory, MachineType, MachineModel, RevenueDaily, RevenueMonthly, RevenueYearly, PoPackDaily, PoProgress, SyncRun, LaborStandard, LaborStandardGradeDetail, MachineCapacity,
    FutureTechnologyCandidate, FutureTechnologyEvidence, TechnologyProcess, TechnologyProcessVersion, TechnologyProcessOperation,
    RoadmapScenario, RoadmapScenarioVersion, RoadmapMilestone, RoadmapTarget, RoadmapTechnologyLink, RoadmapRule, RoadmapRun, RoadmapRunTargetResult,
    RoadmapProposal, RoadmapProposalDecisionHistory, RoadmapStatusHistory,
]


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[m.__table__ for m in _TABLES])
    s = sessionmaker(bind=engine)()
    events: list[str] = []
    for mod in (rm, eng):
        monkeypatch.setattr(mod, "write_audit", lambda action, **kw: events.append(action))
    s.audit = events  # type: ignore[attr-defined]
    for i, code in enumerate(("XN1", "XN2", "XN3"), 1):
        s.add(Factory(id=i, code=code, name=code, is_active=True))
    for code in ("1K", "2K"):
        s.add(MachineType(code=code, name=code, status="ACTIVE"))
    s.commit()
    yield s
    s.close()


def _now(hours_ago=1):
    return datetime.now(timezone.utc) - timedelta(hours=hours_ago)


def _sync(db, status="SUCCEEDED", hours_ago=1, code=None):
    n = db.query(SyncRun).count() + 1
    r = SyncRun(run_code=code or f"SYNC-T-{n:04d}", source="EGMF_REVENUE", status=status, started_at=_now(hours_ago), finished_at=_now(hours_ago))
    db.add(r)
    db.commit()
    return r


def _seed_revenue(db):
    """2026-08: plan 100/200/300 (=600), actual 90/180/270 (=540); năm 2026 khớp Σ tháng."""
    for fid, plan, actual in ((1, 100.0, 90.0), (2, 200.0, 180.0), (3, 300.0, 270.0)):
        db.add(RevenueMonthly(factory_id=fid, year=2026, month=8, plan=plan, actual=actual))
        db.add(RevenueYearly(factory_id=fid, year=2026, plan=plan, actual=actual))
    db.commit()


def _seed_pack(db):
    """po_pack_daily phủ 2026-01-02 → 2026-09-23; Aug tổng 1500."""
    for d, q in ((date(2026, 1, 2), 10), (date(2026, 8, 5), 1000), (date(2026, 8, 20), 500), (date(2026, 9, 10), 300), (date(2026, 9, 23), 5)):
        db.add(PoPackDaily(po=f"PO{d.isoformat()}", day=d, qty=q))
    db.commit()


def _scenario(db, scope="TOTAL", value="", name="Roadmap A"):
    s = rm.create_scenario(db, ADMIN, {"name": name, "scope_type": scope, "scope_value": value})
    v = rm.create_version(db, ADMIN, s.id)
    return s, v


def _ms(db, v, code="M1", d="2026-08-31", seq=None):
    return rm.add_milestone(db, ADMIN, v.id, {"code": code, "name": code, "target_date": d, **({"sequence": seq} if seq else {})})


def _tgt(db, ms, **kw):
    d = {"metric_code": "REVENUE", "target_kind": "ABSOLUTE", "target_value": 1000, "unit": "USD", "baseline_basis": "PLAN"}
    d.update(kw)
    return rm.add_target(db, ADMIN, ms.id, d)


def _ready(db, v):
    return rm.transition_version(db, ADMIN, v.id, "READY")


def _run(db, v):
    return eng.run_simulation(db, ADMIN, v.id)


def _rev_run(db, **tkw):
    """Scenario TOTAL, 1 milestone 2026-08, 1 target revenue -> run."""
    _seed_revenue(db)
    _sync(db)
    s, v = _scenario(db)
    m = _ms(db, v)
    t = _tgt(db, m, **tkw)
    _ready(db, v)
    return s, v, m, t, _run(db, v)


def _result(run, i=0):
    return run["run"]["results"][i]


def _rule(db, code="LAB1", ptype="LABOR_RECRUITMENT", machine=None, approve=True, parameters=None, **kw):
    """Rule registry chỉ là METADATA trong Task 5 (không thực thi số). Fixture approved metadata rule."""
    r = rm.create_rule(db, ADMIN, {"rule_code": code, "proposal_type": ptype, "formula_type": kw.get("formula_type", "UNSPECIFIED"),
                                    "formula_description": kw.get("formula_description", "fixture description"), "parameters": parameters or {},
                                    "machine_type_code": machine, "basis_note": kw.get("basis_note", "fixture basis"), "title": code})
    return rm.approve_rule(db, ADMIN, r.id) if approve else r


def _output_run(db, target_value=2000, **tkw):
    _seed_pack(db)
    _sync(db)
    s, v = _scenario(db)
    m = _ms(db, v)
    _tgt(db, m, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="PACK_QTY", target_value=target_value, **tkw)
    _ready(db, v)
    return s, v, _run(db, v)


# =================================================================== lifecycle / governance
def test_no_roadmap_data_or_rules_seeded(db):
    assert rm.list_scenarios(db) == [] and rm.list_rules(db) == [] and db.query(RoadmapRule).count() == 0  # KHÔNG seed rule APPROVED nào


def test_scenario_create_code_immutable_history_and_scope_validation(db):
    s = rm.create_scenario(db, ADMIN, {"name": "S", "scope_type": "FACTORY", "scope_value": "XN2"})
    assert s.scenario_code == f"RM-{s.id:06d}" and s.status == "DRAFT" and s.owner == "admin"
    assert rm.list_history(db, "SCENARIO", s.id)[0]["to_status"] == "DRAFT"
    with pytest.raises(HTTPException):
        rm.create_scenario(db, ADMIN, {"name": ""})
    with pytest.raises(HTTPException):
        rm.create_scenario(db, ADMIN, {"name": "x", "scope_type": "LINE", "scope_value": "1"})  # Task 5 không LINE
    with pytest.raises(HTTPException):
        rm.create_scenario(db, ADMIN, {"name": "x", "scope_type": "FACTORY", "scope_value": "NOPE"})
    with pytest.raises(HTTPException):
        rm.update_scenario(db, ADMIN, s.id, {"scenario_code": "HACK"})


def test_scenario_scope_locked_once_versions_exist(db):
    s = rm.create_scenario(db, ADMIN, {"name": "S"})
    rm.update_scenario(db, ADMIN, s.id, {"scope_type": "FACTORY", "scope_value": "XN1"})
    rm.create_version(db, ADMIN, s.id)
    with pytest.raises(HTTPException) as e:
        rm.update_scenario(db, ADMIN, s.id, {"scope_type": "TOTAL"})
    assert e.value.status_code == 409


def test_scenario_and_version_lifecycle_forward_only(db):
    s, v = _scenario(db)
    with pytest.raises(HTTPException) as e:
        rm.transition_scenario(db, ADMIN, s.id, "APPROVED")  # DRAFT -> APPROVED không hợp lệ
    assert e.value.status_code == 409
    for to in ("READY", "REVIEWED", "APPROVED"):
        rm.transition_scenario(db, ADMIN, s.id, to)
    assert rm.get_scenario(db, s.id).approved_by == "admin"
    with pytest.raises(HTTPException):
        rm.transition_scenario(db, ADMIN, s.id, "ARCHIVED")  # thiếu reason
    rm.transition_scenario(db, ADMIN, s.id, "ARCHIVED", "kết thúc")
    with pytest.raises(HTTPException) as e:
        rm.transition_scenario(db, ADMIN, s.id, "READY")
    assert e.value.status_code == 409
    assert [h["to_status"] for h in rm.list_history(db, "SCENARIO", s.id)] == ["DRAFT", "READY", "REVIEWED", "APPROVED", "ARCHIVED"]
    with pytest.raises(HTTPException):
        rm.create_version(db, ADMIN, s.id)  # scenario ARCHIVED


def test_version_ready_requires_milestone_and_target_and_locks_inputs(db):
    _s, v = _scenario(db)
    with pytest.raises(HTTPException) as e:
        _ready(db, v)  # chưa có milestone/target
    assert e.value.status_code == 422
    m = _ms(db, v)
    with pytest.raises(HTTPException):
        _ready(db, v)  # có milestone nhưng chưa có target
    t = _tgt(db, m)
    _ready(db, v)
    db.refresh(v)
    assert v.status == "READY" and v.locked_at is not None  # khóa từ READY
    for fn in (lambda: _ms(db, v, "M2", "2026-09-30"), lambda: _tgt(db, m), lambda: rm.update_target(db, ADMIN, t.id, {"target_value": 5}),
               lambda: rm.remove_target(db, ADMIN, t.id), lambda: rm.update_milestone(db, ADMIN, m.id, {"name": "x"}), lambda: rm.remove_milestone(db, ADMIN, m.id)):
        with pytest.raises(HTTPException) as e:
            fn()
        assert e.value.status_code == 409


def test_run_only_on_ready_or_reviewed_not_draft_or_approved(db):
    _seed_revenue(db)
    _sync(db)
    _s, v = _scenario(db)
    m = _ms(db, v)
    _tgt(db, m)
    with pytest.raises(HTTPException) as e:
        _run(db, v)  # DRAFT
    assert e.value.status_code == 409
    _ready(db, v)
    assert _run(db, v)["created"] is True
    rm.transition_version(db, ADMIN, v.id, "REVIEWED")
    assert _run(db, v)["created"] is False  # REVIEWED chạy được (no-op vì cùng input)
    rm.transition_version(db, ADMIN, v.id, "APPROVED")
    with pytest.raises(HTTPException) as e:
        _run(db, v)
    assert e.value.status_code == 409


def test_new_version_copies_inputs_and_is_independent(db):
    _seed_revenue(db)
    s, v = _scenario(db)
    m = _ms(db, v)
    _tgt(db, m)
    rm.add_link(db, ADMIN, v.id, "FUTURE_CANDIDATE", _candidate(db).id)
    _ready(db, v)
    v2 = rm.create_version(db, ADMIN, s.id, copy_from_version_id=v.id, note="đổi target")
    assert v2.version_no == 2 and v2.status == "DRAFT" and v2.copied_from_version_id == v.id
    d2 = rm.version_view(db, v2)
    assert len(d2["milestones"]) == 1 and len(d2["milestones"][0]["targets"]) == 1 and len(d2["technology_links"]) == 1
    rm.update_target(db, ADMIN, d2["milestones"][0]["targets"][0]["id"], {"target_value": 2000})
    assert rm.version_view(db, v)["milestones"][0]["targets"][0]["target_value"] == 1000  # version cũ không đổi
    other, ov = _scenario(db, name="Other")
    with pytest.raises(HTTPException):
        rm.create_version(db, ADMIN, s.id, copy_from_version_id=ov.id)  # khác scenario


# =================================================================== milestone / target validation
def test_milestone_validation_and_uniqueness(db):
    _s, v = _scenario(db)
    with pytest.raises(HTTPException):
        rm.add_milestone(db, ADMIN, v.id, {"code": "", "target_date": "2026-08-31"})
    with pytest.raises(HTTPException):
        rm.add_milestone(db, ADMIN, v.id, {"code": "M1", "target_date": "2026-13-45"})
    _ms(db, v, "M1", "2026-08-31", 1)
    with pytest.raises(HTTPException) as e:
        _ms(db, v, "M1", "2026-09-30", 2)
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        _ms(db, v, "M2", "2026-09-30", 1)
    assert e.value.status_code == 409
    assert _ms(db, v, "M3", "2026-10-31").sequence == 2  # tự tăng


@pytest.mark.parametrize("bad", [
    {"metric_code": "PROFIT"}, {"target_kind": "DELTA"}, {"target_value": "abc"}, {"target_value": float("nan")}, {"target_value": float("inf")}, {"target_value": True},
    {"target_value": -5}, {"unit": ""}, {"unit": None}, {"scope_type": "LINE", "scope_value": "1"}, {"scope_type": "FACTORY", "scope_value": "NOPE"},
    {"baseline_basis": "PACK_QTY"}, {"period_type": "WEEK"}, {"period_month": 13}, {"baseline_ref_month": 3}, {"baseline_ref_year": 2025},
])
def test_target_validation_rejects_invalid(db, bad):
    _s, v = _scenario(db)
    m = _ms(db, v)
    with pytest.raises(HTTPException) as e:
        _tgt(db, m, **bad)
    assert e.value.status_code == 422
    assert db.query(RoadmapTarget).count() == 0


def test_target_defaults_period_scope_and_output_basis(db):
    _s, v = _scenario(db, "FACTORY", "XN2")
    m = _ms(db, v, d="2026-10-31")
    t = _tgt(db, m, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="PACK_QTY")
    assert (t.period_type, t.period_year, t.period_month) == ("MONTH", 2026, 10)  # mặc định từ target_date
    assert (t.scope_type, t.scope_value) == ("FACTORY", "XN2")  # mặc định = scope version
    y = _tgt(db, m, period_type="YEAR")
    assert y.period_month is None and y.baseline_basis == "PLAN"
    none_basis = _tgt(db, m, baseline_basis=None)
    assert none_basis.baseline_basis is None  # cho phép lưu, run sẽ NEEDS_INPUT


# =================================================================== revenue gap
def test_revenue_absolute_gap_total_is_sum_of_factories(db):
    _s, _v, _m, _t, r = _rev_run(db, target_value=1000)
    x = _result(r)
    assert x["result_status"] == "CALCULATED" and x["baseline_value"] == 600.0 and x["effective_target"] == 1000 and x["gap"] == 400.0
    assert x["source_identity"]["factory_values"] == {"XN1": 100.0, "XN2": 200.0, "XN3": 300.0} and x["baseline_unit"] == "USD" and x["baseline_basis"] == "PLAN"
    assert x["completeness"] == "COMPLETE" and r["run"]["summary"]["completeness"] == "COMPLETE"


def test_revenue_increment_records_increment_effective_target_and_gap(db):
    _s, _v, _m, _t, r = _rev_run(db, target_kind="INCREMENT", target_value=400)
    x = _result(r)
    assert x["increment_value"] == 400 and x["baseline_value"] == 600.0 and x["effective_target"] == 1000.0 and x["gap"] == 400.0 and x["target_kind"] == "INCREMENT"


def test_revenue_actual_basis_and_negative_gap_not_clamped(db):
    _s, _v, _m, _t, r = _rev_run(db, baseline_basis="ACTUAL", target_value=500)
    x = _result(r)
    assert x["baseline_value"] == 540.0 and x["gap"] == -40.0  # âm, không clamp
    assert {p["status"] for p in r["run"]["proposals"]} == {"NOT_APPLICABLE"}  # gap <= 0 => không cần đề xuất


def test_revenue_factory_scope_and_year_period(db):
    _seed_revenue(db)
    _sync(db)
    _s, v = _scenario(db, "FACTORY", "XN2")
    m = _ms(db, v)
    _tgt(db, m, period_type="YEAR", target_value=250)
    _ready(db, v)
    x = _result(_run(db, v))
    assert x["baseline_value"] == 200.0 and x["gap"] == 50.0 and x["period_label"] == "2026"


def test_missing_baseline_for_future_period_no_extrapolation_or_copy(db):
    _seed_revenue(db)
    _sync(db)
    _s, v = _scenario(db)
    m = _ms(db, v, "M2027", "2027-06-30")
    _tgt(db, m)  # kỳ 2027-06 không có dòng nguồn
    _ready(db, v)
    x = _result(_run(db, v))
    assert x["result_status"] == "MISSING_BASELINE" and x["baseline_value"] is None and x["gap"] is None and "MISSING_BASELINE" in x["data_quality_flags"]


def test_future_period_with_explicit_reference_period_uses_that_history(db):
    _seed_revenue(db)
    _sync(db)
    _s, v = _scenario(db)
    m = _ms(db, v, "M2027", "2027-08-31")
    _tgt(db, m, baseline_ref_year=2026, baseline_ref_month=8, target_value=900)
    _ready(db, v)
    x = _result(_run(db, v))
    assert x["result_status"] == "CALCULATED" and x["baseline_value"] == 600.0 and x["gap"] == 300.0
    assert x["period_label"] == "2027-08" and x["baseline_period_label"] == "2026-08"


def test_missing_baseline_basis_is_needs_input(db):
    _s, _v, _m, _t, r = _rev_run(db, baseline_basis=None)
    x = _result(r)
    assert x["result_status"] == "NEEDS_INPUT" and x["gap"] is None and any("baseline_basis" in m for m in x["missing_inputs"])


def test_partial_total_when_one_factory_missing_not_used_as_total(db):
    _seed_revenue(db)
    db.query(RevenueMonthly).filter_by(factory_id=3).delete()
    db.commit()
    _sync(db)
    _s, v = _scenario(db)
    m = _ms(db, v)
    _tgt(db, m)
    _ready(db, v)
    x = _result(_run(db, v))
    assert x["result_status"] == "PARTIAL_SOURCE" and x["baseline_value"] is None and "PARTIAL_SOURCE_COVERAGE" in x["data_quality_flags"]


@pytest.mark.parametrize("unit", ["VND", "usd", "KUSD"])
def test_unit_mismatch_no_silent_conversion(db, unit):
    _s, _v, _m, _t, r = _rev_run(db, unit=unit)
    x = _result(r)
    assert x["result_status"] == "UNIT_MISMATCH" and x["gap"] is None and x["baseline_value"] is None and "UNIT_MISMATCH" in x["data_quality_flags"]


def test_output_unit_alias_is_mismatch_not_converted(db):
    _seed_pack(db)
    _sync(db)
    _s, v = _scenario(db)
    m = _ms(db, v)
    _tgt(db, m, metric_code="OUTPUT_QTY", unit="pcs", baseline_basis="PACK_QTY")
    _ready(db, v)
    assert _result(_run(db, v))["result_status"] == "UNIT_MISMATCH"


def test_scope_mismatch_no_auto_rollup(db):
    _seed_revenue(db)
    _sync(db)
    _s, v = _scenario(db, "TOTAL")
    m = _ms(db, v)
    _tgt(db, m, scope_type="FACTORY", scope_value="XN1")  # override khác scope scenario
    _ready(db, v)
    x = _result(_run(db, v))
    assert x["result_status"] == "SCOPE_MISMATCH" and x["gap"] is None and "SCOPE_MISMATCH" in x["data_quality_flags"]


# =================================================================== output (PACK_QTY)
def test_output_total_month_calculated_with_pack_definition(db):
    _s, _v, r = _output_run(db, target_value=2000)
    x = _result(r)
    assert x["result_status"] == "CALCULATED" and x["baseline_value"] == 1500.0 and x["gap"] == 500.0 and x["unit"] == "sp"
    assert x["output_definition"] == "PACK_QTY" and x["source_identity"]["output_definition"] == "PACK_QTY" and x["baseline_basis"] == "PACK_QTY"


def test_output_partial_period_not_fully_covered_is_partial_source(db):
    _seed_pack(db)
    _sync(db)
    _s, v = _scenario(db)
    m = _ms(db, v, "M9", "2026-09-30")  # nguồn chỉ tới 2026-09-23
    _tgt(db, m, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="PACK_QTY", target_value=5000)
    _ready(db, v)
    x = _result(_run(db, v))
    assert x["result_status"] == "PARTIAL_SOURCE" and x["gap"] is None and "PARTIAL_SOURCE_COVERAGE" in x["data_quality_flags"]
    assert x["source_meta"]["diagnostics"]["source_day_range"] == ["2026-01-02", "2026-09-23"]


def test_output_factory_scope_is_partial_source_never_calculated(db):
    _seed_pack(db)
    db.add(PoProgress(po="PO2026-08-05", factory_id=1, qty=1))
    db.commit()
    _sync(db)
    _s, v = _scenario(db, "FACTORY", "XN1")
    m = _ms(db, v)
    _tgt(db, m, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="PACK_QTY")
    _ready(db, v)
    x = _result(_run(db, v))
    assert x["result_status"] == "PARTIAL_SOURCE" and x["baseline_value"] is None
    assert x["source_meta"]["diagnostics"]["po_factory_mapping"]["packed_pos"] == 2  # diagnostic mapping coverage, không dùng để tính


def test_sewn_output_never_used_as_baseline(db):
    assert rb.output_baseline.__doc__ is None or "sewn" not in (rb.output_baseline.__doc__ or "").lower()
    _seed_pack(db)
    _sync(db)
    _s, v = _scenario(db)
    m = _ms(db, v)
    with pytest.raises(HTTPException):
        _tgt(db, m, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="SEWN_QTY")  # chỉ PACK_QTY


# =================================================================== data quality / freshness
def test_failed_last_sync_flags_but_does_not_block_run(db):
    _seed_revenue(db)
    _sync(db, "PARTIAL", hours_ago=48)
    _sync(db, "FAILED", hours_ago=1)
    _s, v = _scenario(db)
    m = _ms(db, v)
    _tgt(db, m)
    _ready(db, v)
    r = _run(db, v)
    x = _result(r)
    assert x["result_status"] == "CALCULATED" and "SOURCE_STALE_OR_LAST_SYNC_FAILED" in x["data_quality_flags"]
    fr = r["run"]["snapshot"]["source_freshness"]
    assert fr["latest_success"]["status"] == "PARTIAL" and fr["last_attempt"]["status"] == "FAILED" and fr["source_age_hours"] >= 47
    assert x["source_meta"]["stale_or_last_sync_failed"] is True


def test_never_synced_source_flagged_but_run_allowed(db):
    _seed_revenue(db)
    _s, v = _scenario(db)
    m = _ms(db, v)
    _tgt(db, m)
    _ready(db, v)
    x = _result(_run(db, v))
    assert "SOURCE_STALE_OR_LAST_SYNC_FAILED" in x["data_quality_flags"] and x["result_status"] == "CALCULATED"


def test_invalid_source_date_row_flagged_excluded_and_source_untouched(db):
    _seed_revenue(db)
    db.add(RevenueDaily(factory_id=1, report_date=date(1, 1, 1), plan=5, actual=5))
    db.commit()
    _sync(db)
    _s, v = _scenario(db)
    m = _ms(db, v)
    _tgt(db, m)
    _ready(db, v)
    x = _result(_run(db, v))
    assert "INVALID_SOURCE_DATE" in x["data_quality_flags"] and x["baseline_value"] == 600.0
    assert db.query(RevenueDaily).count() == 1  # Roadmap không xóa/sửa/clean nguồn


def test_year_vs_monthly_inconsistency_warning_not_deleted(db):
    _seed_revenue(db)
    db.query(RevenueYearly).filter_by(factory_id=1).update({"plan": 80000000.0})  # yearly bất thường so với Σ monthly
    db.commit()
    _sync(db)
    _s, v = _scenario(db)
    m = _ms(db, v)
    _tgt(db, m, period_type="YEAR", target_value=90000000)
    _ready(db, v)
    x = _result(_run(db, v))
    assert x["result_status"] == "CALCULATED" and "SOURCE_INCONSISTENT_PERIODS" in x["data_quality_flags"]
    assert db.query(RevenueYearly).filter_by(factory_id=1).one().plan == 80000000.0  # không tự sửa/xóa


def test_baseline_preview_endpoint_helper_is_read_only(db):
    _seed_revenue(db)
    before = db.query(RoadmapRun).count()
    b = rb.baseline_for(db, "REVENUE", "PLAN", "MONTH", 2026, 8, "TOTAL", "")
    assert b["status"] == "OK" and b["value"] == 600.0 and db.query(RoadmapRun).count() == before


# =================================================================== snapshot / idempotency / reproducibility
def test_run_snapshot_retained_after_source_changes(db):
    _s, v, _m, _t, r1 = _rev_run(db)
    rid = r1["run"]["id"]
    db.query(RevenueMonthly).filter_by(factory_id=1, year=2026, month=8).update({"plan": 999.0})
    db.commit()
    stored = eng.run_view(db, eng.get_run(db, rid))
    assert stored["results"][0]["baseline_value"] == 600.0 and stored["results"][0]["gap"] == 400.0  # run cũ không đổi
    assert stored["snapshot"]["version"]["milestones"][0]["targets"][0]["target_value"] == 1000
    r2 = _run(db, v)
    assert r2["created"] is True and r2["run"]["results"][0]["baseline_value"] == 1499.0 and r2["run"]["run_no"] == 2
    assert db.query(RoadmapRun).count() == 2 and eng.run_view(db, eng.get_run(db, rid))["results"][0]["baseline_value"] == 600.0


def test_same_inputs_idempotent_and_new_sync_same_numbers_no_new_run(db):
    _s, v, _m, _t, r1 = _rev_run(db)
    assert r1["created"] is True
    r2 = _run(db, v)
    assert r2["created"] is False and r2["run"]["id"] == r1["run"]["id"]
    _sync(db, "SUCCEEDED", hours_ago=0)  # sync mới, số không đổi -> timestamp/sync_run_id chỉ là evidence
    r3 = _run(db, v)
    assert r3["created"] is False and db.query(RoadmapRun).count() == 1


def test_baseline_change_creates_new_run_keeps_old(db):
    _s, v, _m, _t, r1 = _rev_run(db)
    db.query(RevenueMonthly).filter_by(factory_id=2, year=2026, month=8).update({"plan": 250.0})
    db.commit()
    r2 = _run(db, v)
    assert r2["created"] is True and r2["run"]["id"] != r1["run"]["id"] and db.query(RoadmapRun).count() == 2


def test_target_change_via_new_version_creates_new_run(db):
    s, v, _m, _t, r1 = _rev_run(db)
    v2 = rm.create_version(db, ADMIN, s.id, copy_from_version_id=v.id)
    d2 = rm.version_view(db, v2)
    rm.update_target(db, ADMIN, d2["milestones"][0]["targets"][0]["id"], {"target_value": 1500})
    _ready(db, v2)
    r2 = _run(db, v2)
    assert r2["created"] is True and r2["run"]["version_id"] == v2.id and r2["run"]["results"][0]["gap"] == 900.0
    assert r1["run"]["results"][0]["gap"] == 400.0


def test_rule_change_creates_new_run(db):
    _s, v, r1 = _output_run(db)
    assert r1["created"] is True
    _rule(db, "LAB1")
    r2 = _run(db, v)
    assert r2["created"] is True  # rule APPROVED (metadata) mới => fingerprint đổi => run mới
    assert _run(db, v)["created"] is False


# =================================================================== proposals
def _labor(db, factory="XN1", total=50):
    db.add(LaborStandard(factory_code=factory, line="1", total_labor=total, effective_from=date(2026, 1, 1), status="ACTIVE"))
    db.commit()


def _machines(db, factory="XN1", mtype="1K", qty=10):
    db.add(MachineCapacity(factory_code=factory, line="1", machine_type=mtype, quantity=qty, status="ACTIVE"))
    db.commit()


def _by_type(run, ptype):
    return [p for p in run["run"]["proposals"] if p["proposal_type"] == ptype]


def test_without_approved_rules_all_quantity_proposals_needs_input_not_invented(db):
    _labor(db)
    _machines(db)
    _s, _v, r = _output_run(db)
    for pt in ("LABOR_RECRUITMENT", "MACHINE_PURCHASE", "CAPACITY_CHANGE", "TECHNOLOGY_ADOPTION"):
        (p,) = _by_type(r, pt)
        assert p["calc_status"] == "NEEDS_INPUT" and p["quantity"] is None and p["missing_inputs"]
    assert any("approved calculation rule" in m for m in _by_type(r, "LABOR_RECRUITMENT")[0]["missing_inputs"])
    assert r["run"]["summary"]["proposal_status_counts"] == {"NEEDS_INPUT": 4}


def test_approved_metadata_rule_never_calculates_labor_quantity(db):
    """GPT review PR #12: Task 5 không thực thi công thức nghiệp vụ nào — kể cả khi rule APPROVED khai formula_type/parameters giống 'gap/rate'."""
    _labor(db, "XN1", 50)
    _labor(db, "XN2", 30)
    _rule(db, "LAB1", "LABOR_RECRUITMENT", formula_type="GAP_PER_UNIT_RATE", parameters={"rate_value": 100, "rate_period": "MONTH"})
    _s, _v, r = _output_run(db, target_value=2000)  # gap 500 sp, có labor baseline, có rule APPROVED
    (p,) = _by_type(r, "LABOR_RECRUITMENT")
    assert p["calc_status"] == "NEEDS_INPUT" and p["quantity"] is None and p["unit"] == ""
    assert p["calculation_rule_version"] == "LAB1@v1" and p["completeness"] == "PARTIAL"
    assert any("executable calculation adapter" in m for m in p["missing_inputs"])
    assert p["input_snapshot"]["available_baseline"]["total_labor"] == 80 and p["input_snapshot"]["rule"]["parameters"] == {"rate_value": 100, "rate_period": "MONTH"}
    assert p["input_snapshot"]["rule"]["executable"] is False and p["evidence_refs"][0]["rule_code"] == "LAB1"
    assert r["run"]["snapshot"]["approved_rules"][0]["formula_type"] == "GAP_PER_UNIT_RATE"  # metadata được snapshot nhưng không thực thi


def test_no_code_path_derives_quantity_from_gap_and_rate(db):
    import inspect

    for mod in (eng, rm, rb):  # không còn code path production nào tính quantity từ gap/rate
        src = inspect.getsource(mod)
        assert "math.ceil" not in src and "ceil(" not in src and "rate_value" not in src and "GAP_PER_UNIT_RATE" not in src, mod.__name__
    _labor(db)
    _machines(db, "XN1", "2K", 10)
    _rule(db, "LAB1", parameters={"rate_value": 300})
    _rule(db, "MCH1", "MACHINE_PURCHASE", machine="2K", parameters={"rate_value": 250})
    _s, _v, r = _output_run(db, target_value=2000)
    for pt in ("LABOR_RECRUITMENT", "MACHINE_PURCHASE", "CAPACITY_CHANGE", "TECHNOLOGY_ADOPTION"):
        assert all(p["quantity"] is None and p["calc_status"] == "NEEDS_INPUT" for p in _by_type(r, pt)), pt
    assert all(p["quantity"] is None for p in r["run"]["proposals"]) and r["run"]["summary"]["proposal_status_counts"] == {"NEEDS_INPUT": 4}


def test_machine_rule_is_metadata_only_needs_input_with_or_without_inventory(db):
    _rule(db, "MCH1", "MACHINE_PURCHASE", machine="2K", parameters={"rate_value": 250})
    _s, v, r = _output_run(db, target_value=2000)  # chưa có inventory
    (p,) = _by_type(r, "MACHINE_PURCHASE")
    assert p["calc_status"] == "NEEDS_INPUT" and p["quantity"] is None
    _machines(db, "XN2", "2K", 4)  # có inventory đúng loại máy của rule
    r2 = _run(db, v)
    (p2,) = _by_type(r2, "MACHINE_PURCHASE")
    assert r2["created"] is True and p2["calc_status"] == "NEEDS_INPUT" and p2["quantity"] is None  # vẫn không tính số
    assert p2["input_snapshot"]["available_baseline"]["by_machine_type"] == {"2K": 4}


def test_multiple_approved_rules_yield_separate_lines_no_ranking(db):
    _labor(db)
    _rule(db, "LAB1")
    _rule(db, "LAB2")
    _s, _v, r = _output_run(db, target_value=2000)
    lines = _by_type(r, "LABOR_RECRUITMENT")
    assert sorted(p["calculation_rule_version"] for p in lines) == ["LAB1@v1", "LAB2@v1"]  # mỗi rule một dòng, không chọn "best"
    forbidden = {"rank", "score", "best", "priority"}
    assert not forbidden & set(lines[0]) and not forbidden & set(r["run"]["results"][0]) and not forbidden & set(r["run"]["summary"])
    assert all(p["decision_status"] is None and p["status"] == "NEEDS_INPUT" and p["quantity"] is None for p in lines)  # không auto SELECTED


def test_revenue_gap_does_not_imply_labor_machine_capacity(db):
    _labor(db)
    _rule(db, "LAB1")
    _s, _v, _m, _t, r = _rev_run(db, target_value=1000)
    for pt in ("LABOR_RECRUITMENT", "MACHINE_PURCHASE", "CAPACITY_CHANGE"):
        (p,) = _by_type(r, pt)
        assert p["calc_status"] == "NOT_APPLICABLE" and p["quantity"] is None
    assert _by_type(r, "TECHNOLOGY_ADOPTION")[0]["calc_status"] == "NEEDS_INPUT"


def test_capacity_change_always_needs_input_even_with_rules(db):
    _labor(db)
    _rule(db, "LAB1")
    _s, _v, r = _output_run(db)
    (p,) = _by_type(r, "CAPACITY_CHANGE")
    assert p["calc_status"] == "NEEDS_INPUT" and p["quantity"] is None and any("capacity-change" in m for m in p["missing_inputs"])


def test_non_calculated_target_gives_needs_input_proposals(db):
    _seed_revenue(db)
    _sync(db)
    _s, v = _scenario(db)
    m = _ms(db, v, "M27", "2027-01-31")
    _tgt(db, m)
    _ready(db, v)
    r = _run(db, v)
    assert {p["calc_status"] for p in r["run"]["proposals"]} == {"NEEDS_INPUT"} and len(r["run"]["proposals"]) == 4


# =================================================================== technology evidence (chỉ link/snapshot)
def _candidate(db, with_evidence=True):
    c = FutureTechnologyCandidate(candidate_code=f"FTC-{db.query(FutureTechnologyCandidate).count() + 1:06d}", machine_type_code="2K", brand="TEST_ONLY", status="TRIAL")
    db.add(c)
    db.commit()
    if with_evidence:
        db.add(FutureTechnologyEvidence(candidate_id=c.id, source_ref="brochure", basis="CLAIMED", metric_code="OUTPUT", value=9999.0, unit="pcs/day"))
        db.commit()
    return c


def test_technology_adoption_links_evidence_but_invents_no_uplift(db):
    c = _candidate(db)
    _seed_pack(db)
    _sync(db)
    _s, v = _scenario(db)
    m = _ms(db, v)
    _tgt(db, m, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="PACK_QTY", target_value=2000)
    rm.add_link(db, ADMIN, v.id, "FUTURE_CANDIDATE", c.id)
    _ready(db, v)
    r = _run(db, v)
    (p,) = _by_type(r, "TECHNOLOGY_ADOPTION")
    assert p["calc_status"] == "NEEDS_INPUT" and p["quantity"] is None  # claimed 9999 pcs/day KHÔNG thành uplift
    assert p["evidence_refs"][0]["code"] == c.candidate_code and p["evidence_refs"][0]["evidence_count"] == 1
    snap = r["run"]["snapshot"]["technology_links"][0]
    assert snap["status"] == "TRIAL" and snap["evidence"][0]["value"] == 9999.0 and snap["evidence"][0]["basis"] == "CLAIMED"
    assert any("approved technology impact formula" in m for m in p["missing_inputs"])


def test_technology_evidence_change_creates_new_run_and_link_validation(db):
    c = _candidate(db, with_evidence=False)
    _seed_pack(db)
    _sync(db)
    _s, v = _scenario(db)
    m = _ms(db, v)
    _tgt(db, m, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="PACK_QTY", target_value=2000)
    rm.add_link(db, ADMIN, v.id, "FUTURE_CANDIDATE", c.id)
    with pytest.raises(HTTPException):
        rm.add_link(db, ADMIN, v.id, "FUTURE_CANDIDATE", c.id)  # trùng
    with pytest.raises(HTTPException):
        rm.add_link(db, ADMIN, v.id, "FUTURE_CANDIDATE", 9999)
    with pytest.raises(HTTPException):
        rm.add_link(db, ADMIN, v.id, "PROCESS_VERSION", 9999)
    with pytest.raises(HTTPException):
        rm.add_link(db, ADMIN, v.id, "BOGUS", 1)
    _ready(db, v)
    r1 = _run(db, v)
    db.add(FutureTechnologyEvidence(candidate_id=c.id, source_ref="trial#1", basis="TRIALED", metric_code="OUTPUT", value=1.0, unit="pcs/day"))
    db.commit()
    assert _run(db, v)["created"] is True and r1["created"] is True


def test_process_version_link_snapshots_status(db):
    p = TechnologyProcess(process_code="TP-X", style_cc="X", model_code="")
    db.add(p)
    db.commit()
    pv = TechnologyProcessVersion(technology_process_id=p.id, layer="OPTIMIZED_CURRENT_TECHNOLOGY", version_no=1, status="DRAFT", sam_status="INCOMPLETE")
    db.add(pv)
    db.commit()
    _seed_pack(db)
    _sync(db)
    _s, v = _scenario(db)
    m = _ms(db, v)
    _tgt(db, m, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="PACK_QTY", target_value=2000)
    rm.add_link(db, ADMIN, v.id, "PROCESS_VERSION", pv.id)
    _ready(db, v)
    snap = _run(db, v)["run"]["snapshot"]["technology_links"][0]
    assert snap["layer"] == "OPTIMIZED_CURRENT_TECHNOLOGY" and snap["code"] == "TP-X" and snap["sam_status"] == "INCOMPLETE"


# =================================================================== rule registry
def test_rule_registry_validation_approval_immutability_versioning(db):
    with pytest.raises(HTTPException):
        rm.create_rule(db, ADMIN, {"rule_code": "R", "proposal_type": "CAPACITY_CHANGE"})  # chưa có rule cho loại này
    with pytest.raises(HTTPException):
        rm.create_rule(db, ADMIN, {"rule_code": "R", "proposal_type": "MACHINE_PURCHASE"})  # thiếu machine_type_code
    with pytest.raises(HTTPException):
        rm.create_rule(db, ADMIN, {"rule_code": "R", "proposal_type": "MACHINE_PURCHASE", "machine_type_code": "NOPE"})
    with pytest.raises(HTTPException):
        rm.create_rule(db, ADMIN, {"rule_code": "R", "proposal_type": "LABOR_RECRUITMENT", "parameters": [1, 2]})  # parameters phải là object
    r = rm.create_rule(db, ADMIN, {"rule_code": "lab1", "proposal_type": "LABOR_RECRUITMENT", "parameters": {"note": "v1"}})
    assert r.rule_code == "LAB1" and r.approval_status == "DRAFT" and r.formula_type == "UNSPECIFIED"
    assert rm.rule_view(r)["executable"] is False
    with pytest.raises(HTTPException):
        rm.approve_rule(db, ADMIN, r.id)  # thiếu basis_note/formula_description
    rm.update_rule(db, ADMIN, r.id, {"basis_note": "IE study 2026", "formula_description": "mô tả rule do business sở hữu"})
    rm.approve_rule(db, ADMIN, r.id)
    db.refresh(r)
    assert r.approval_status == "APPROVED" and r.approved_by == "admin"
    with pytest.raises(HTTPException) as e:
        rm.update_rule(db, ADMIN, r.id, {"parameters": {"note": "đổi"}})  # APPROVED bất biến
    assert e.value.status_code == 409
    r2 = rm.new_rule_version(db, ADMIN, r.id)
    assert r2.rule_version == 2 and r2.approval_status == "DRAFT" and r2.parameters_json == {"note": "v1"}
    with pytest.raises(HTTPException):
        rm.new_rule_version(db, ADMIN, r.id)  # đã có DRAFT
    rm.update_rule(db, ADMIN, r2.id, {"parameters": {"note": "v2"}})
    rm.approve_rule(db, ADMIN, r2.id)
    db.refresh(r)
    assert r.approval_status == "RETIRED" and r.parameters_json == {"note": "v1"}  # v1 bị thay, giữ nguyên nội dung lịch sử
    with pytest.raises(HTTPException):
        rm.retire_rule(db, ADMIN, r2.id, "")
    rm.retire_rule(db, ADMIN, r2.id, "hết hiệu lực")
    assert [x.rule_version for x in rm.list_rules(db, approval_status="APPROVED")] == []
    assert [h["to_status"] for h in rm.list_history(db, "RULE", r.id)] == ["DRAFT", "APPROVED", "RETIRED"]


def test_run_keeps_rule_snapshot_after_rule_replaced_and_fingerprint_reflects_metadata(db):
    _labor(db)
    r1 = _rule(db, "LAB1", parameters={"note": "a"})
    _s, v, run1 = _output_run(db)
    assert _run(db, v)["created"] is False  # cùng rule metadata => idempotent
    v2 = rm.new_rule_version(db, ADMIN, r1.id)
    rm.update_rule(db, ADMIN, v2.id, {"parameters": {"note": "b"}})
    rm.approve_rule(db, ADMIN, v2.id)
    run2 = _run(db, v)
    assert run2["created"] is True  # metadata/version đổi => run mới
    stored = eng.run_view(db, eng.get_run(db, run1["run"]["id"]))
    assert stored["snapshot"]["approved_rules"][0]["parameters"] == {"note": "a"} and run2["run"]["snapshot"]["approved_rules"][0]["parameters"] == {"note": "b"}
    assert _by_type({"run": stored}, "LABOR_RECRUITMENT")[0]["calculation_rule_version"] == "LAB1@v1" and _by_type(run2, "LABOR_RECRUITMENT")[0]["calculation_rule_version"] == "LAB1@v2"


# =================================================================== proposal decision
def test_proposal_decision_manual_with_reason_and_append_only_history(db):
    _s, _v, r = _output_run(db)
    p = _by_type(r, "LABOR_RECRUITMENT")[0]
    assert p["decision_status"] is None
    with pytest.raises(HTTPException):
        eng.decide_proposal(db, ADMIN, p["id"], "SELECTED", "")  # thiếu reason
    with pytest.raises(HTTPException):
        eng.decide_proposal(db, ADMIN, p["id"], "EXECUTED", "x")
    eng.decide_proposal(db, ADMIN, p["id"], "SELECTED", "ghi nhận để theo dõi")
    with pytest.raises(HTTPException) as e:
        eng.decide_proposal(db, ADMIN, p["id"], "SELECTED", "lần nữa")
    assert e.value.status_code == 409
    eng.decide_proposal(db, ADMIN, p["id"], "REJECTED", "đổi ý")
    hist = eng.proposal_history(db, p["id"])
    assert [(h["from_status"], h["to_status"]) for h in hist] == [("NEEDS_INPUT", "SELECTED"), ("SELECTED", "REJECTED")]
    stored = next(x for x in eng.run_view(db, eng.get_run(db, r["run"]["id"]))["proposals"] if x["id"] == p["id"])
    assert stored["status"] == "REJECTED" and stored["calc_status"] == "NEEDS_INPUT" and stored["quantity"] is None  # nội dung không đổi
    assert "ROADMAP_PROPOSAL_DECISION" in db.audit  # type: ignore[attr-defined]


def test_needs_input_and_not_applicable_proposals_can_be_decided_too(db):
    _s, _v, r = _output_run(db)
    p = _by_type(r, "CAPACITY_CHANGE")[0]
    assert eng.decide_proposal(db, ADMIN, p["id"], "REJECTED", "chưa có rule").decision_status == "REJECTED"


def test_run_is_immutable_no_public_update_or_delete(db):
    public = {n for n in dir(eng) if not n.startswith("_")}
    assert not {n for n in public if n in ("update_run", "delete_run", "remove_run", "edit_run")}
    _s, _v, r = _output_run(db)
    row = db.get(RoadmapRun, r["run"]["id"])
    assert row.status == "COMPLETED" and row.run_fingerprint


def test_compare_runs_shows_changes_without_ranking(db):
    _s, v, _m, _t, r1 = _rev_run(db)
    db.query(RevenueMonthly).filter_by(factory_id=1, year=2026, month=8).update({"plan": 200.0})
    db.commit()
    r2 = _run(db, v)
    c = eng.compare_runs(db, r1["run"]["id"], r2["run"]["id"])
    row = c["targets"][0]
    assert row["a"]["baseline"] == 600.0 and row["b"]["baseline"] == 700.0 and row["a"]["gap"] == 400.0 and row["b"]["gap"] == 300.0 and row["changed"] is True
    assert not {"rank", "score", "best"} & set(c) and not {"rank", "score", "best"} & set(row)
    assert [x["id"] for x in [eng.run_view(db, x, detail=False) for x in eng.list_runs(db, v.id)]] == [r2["run"]["id"], r1["run"]["id"]]


# =================================================================== audit / permissions / HTTP
def test_audit_events_emitted(db):
    _s, v, *_ = _rev_run(db)
    _rule(db, "LAB1")
    for a in ("ROADMAP_SCENARIO_CREATE", "ROADMAP_VERSION_CREATE", "ROADMAP_MILESTONE_ADD", "ROADMAP_TARGET_ADD", "ROADMAP_VERSION_TRANSITION", "ROADMAP_RUN",
              "ROADMAP_RULE_CREATE", "ROADMAP_RULE_APPROVE"):
        assert a in db.audit, a  # type: ignore[attr-defined]


def test_permission_baseline_roles():
    admin, planner, viewer = set(permissions_for("ADMIN")), set(permissions_for("PLANNER")), set(permissions_for("VIEWER"))
    assert {"roadmap.view", "roadmap.manage", "roadmap.run", "roadmap.approve"} <= admin
    assert {"roadmap.view", "roadmap.manage", "roadmap.run"} <= planner and "roadmap.approve" not in planner
    assert "roadmap.view" in viewer and not {"roadmap.manage", "roadmap.run", "roadmap.approve"} & viewer
    assert not any(p.startswith("roadmap.") for p in ()) and "technology_process.manage" not in planner  # domain riêng, không reuse technology_process.*


def test_approve_gates_in_api_layer(db):
    s, v, *_ = _rev_run(db)
    rm.transition_version(db, ADMIN, v.id, "REVIEWED")
    with pytest.raises(HTTPException) as e:
        rm_api.transition_version(v.id, rm_api.TransitionBody(to_status="APPROVED"), db, PLANNER)  # thiếu roadmap.approve
    assert e.value.status_code == 403 and rm.get_version(db, v.id).status == "REVIEWED"
    assert rm_api.transition_version(v.id, rm_api.TransitionBody(to_status="APPROVED"), db, ADMIN)["status"] == "APPROVED"
    r = rm.create_rule(db, ADMIN, {"rule_code": "L", "proposal_type": "LABOR_RECRUITMENT", "formula_description": "d", "basis_note": "b"})
    with pytest.raises(HTTPException) as e:
        rm_api.approve_rule(r.id, db, PLANNER)
    assert e.value.status_code == 403 and rm.get_rule(db, r.id).approval_status == "DRAFT"
    with pytest.raises(HTTPException) as e:
        rm_api.transition_scenario(s.id, rm_api.TransitionBody(to_status="APPROVED"), db, PLANNER)
    assert e.value.status_code == 403


def test_http_end_to_end_and_routes_not_shadowed(db):
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.db.session import get_db
    from app.main import app

    _seed_revenue(db)
    _sync(db)
    admin = SimpleNamespace(username="admin", role="ADMIN", id=1, is_active=True, must_change_password=False)
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app)
        B = "/api/roadmap"
        sid = c.post(f"{B}/scenarios", json={"name": "HTTP", "scope_type": "TOTAL"}).json()["id"]
        vid = c.post(f"{B}/scenarios/{sid}/versions", json={}).json()["id"]
        mid = c.post(f"{B}/versions/{vid}/milestones", json={"code": "M1", "target_date": "2026-08-31"}).json()["id"]
        assert c.post(f"{B}/milestones/{mid}/targets", json={"metric_code": "REVENUE", "target_value": 1000, "unit": "USD", "baseline_basis": "PLAN"}).status_code == 200
        assert c.post(f"{B}/milestones/{mid}/targets", json={"metric_code": "REVENUE", "target_value": 1000, "unit": ""}).status_code == 422
        assert c.post(f"{B}/versions/{vid}/runs").status_code == 409  # DRAFT chưa chạy được
        assert c.post(f"{B}/versions/{vid}/transition", json={"to_status": "READY"}).status_code == 200
        run = c.post(f"{B}/versions/{vid}/runs").json()
        assert run["created"] is True and run["run"]["results"][0]["gap"] == 400.0
        assert c.post(f"{B}/versions/{vid}/runs").json()["created"] is False
        rid = run["run"]["id"]
        assert c.get(f"{B}/runs/{rid}").status_code == 200 and len(c.get(f"{B}/versions/{vid}/runs").json()) == 1
        assert c.get(f"{B}/runs/{rid}/compare-with/{rid}").status_code == 200
        pid = run["run"]["proposals"][0]["id"]
        assert c.post(f"{B}/proposals/{pid}/decision", json={"decision": "REJECTED", "reason": "x"}).status_code == 200
        assert c.get(f"{B}/proposals/{pid}/history").json()[0]["to_status"] == "REJECTED"
        assert c.get(f"{B}/baseline-preview", params={"metric_code": "REVENUE", "baseline_basis": "PLAN", "period_type": "MONTH", "year": 2026, "month": 8}).json()["value"] == 600.0
        assert c.get(f"{B}/options").json()["canonical_units"] == {"REVENUE": "USD", "OUTPUT_QTY": "sp"}
        assert c.get(f"{B}/rules").json() == [] and c.get(f"{B}/scenarios").status_code == 200
    finally:
        app.dependency_overrides.clear()
