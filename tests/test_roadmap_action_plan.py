"""Task 7 (Issue #15) — Roadmap Action Plan & Milestone Coverage. Rule fixture chỉ tồn tại trong test; production không seed gì."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import roadmap as rm_api
from app.db.session import Base
from app.models.data import PoPackDaily
from app.models.roadmap import RoadmapActionPlan, RoadmapActionPlanItem, RoadmapActionPlanVersion, RoadmapProposal, RoadmapRun
from app.services import roadmap as rm
from app.services import roadmap_action_plan as ap
from app.services import roadmap_engine as eng
from app.services import roadmap_exec_rules as xr
from tests.test_roadmap import ADMIN, PLANNER, _labor, _machines, _ms, _ready, _run, _scenario, _seed_pack, _sync, _tgt, db  # noqa: F401
from tests.test_roadmap_exec import ADMIN2, LAB, MAC, _xrule

ADMIN3 = SimpleNamespace(username="admin3", role="ADMIN", id=4)


@pytest.fixture()
def pdb(db, monkeypatch):  # noqa: F811
    Base.metadata.create_all(db.get_bind(), tables=[m.__table__ for m in (RoadmapActionPlan, RoadmapActionPlanVersion, RoadmapActionPlanItem)])
    for mod in (ap, xr):
        monkeypatch.setattr(mod, "write_audit", lambda *a, **kw: None)
    return db


def _setup(db, extra_rules=True):
    """M1 (2026-08-31): target Aug 2000 -> gap 500; M2 (2026-09-30): target Sep 1000 -> gap 694; M1 còn 1 target gap<0 (proposals NOT_APPLICABLE)."""
    _seed_pack(db)
    db.add(PoPackDaily(po="PO-SEP-END", day=date(2026, 9, 30), qty=1))  # baseline Sep = 306, phủ đủ kỳ
    db.commit()
    _sync(db)
    _labor(db, "XN1", 50)
    _machines(db, "XN1", "1K", 10)
    _xrule(db, LAB, rule_code="LAB-A", prod=120.0)
    _xrule(db, MAC, rule_code="MAC-A", prod=300.0)
    if extra_rules:
        _xrule(db, LAB, rule_code="LAB-B", prod=200.0, effective_to="2026-09-15")
    s, v = _scenario(db)
    m1, m2 = _ms(db, v, "M1", "2026-08-31"), _ms(db, v, "M2", "2026-09-30")
    _tgt(db, m1, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="PACK_QTY", target_value=2000)
    _tgt(db, m1, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="PACK_QTY", target_value=1000)  # gap -500 => NOT_APPLICABLE
    _tgt(db, m2, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="PACK_QTY", target_value=1000, period_month=9)
    _ready(db, v)
    run = _run(db, v)["run"]
    db.query(RoadmapRun).update({"created_at": datetime(2026, 8, 1, tzinfo=timezone.utc)})  # để test không phụ thuộc đồng hồ thật
    db.commit()
    return s, v, run


def _pick(run, ptype, milestone=None, rule=None, status=None):
    out = [p for p in run["proposals"] if p["proposal_type"] == ptype and (milestone is None or p["milestone_code"] == milestone)
           and (rule is None or p["calculation_rule_version"] == rule) and (status is None or p["calc_status"] == status)]
    assert out, (ptype, milestone, rule, status)
    return out[0]


def _plan(db, run, name="AP"):
    return ap.create_plan(db, ADMIN, run["id"], {"name": name})


def _cov(db, v, milestone):
    v = db.get(RoadmapActionPlanVersion, v.id)
    ap._refresh_preview(db, v)
    return [t for t in ap.compute_coverage(db, v)["targets"] if t["milestone_code"] == milestone][0]


# =================================================================== create / lineage / selection
def test_no_action_plan_seeded_and_create_from_run(pdb):
    assert ap.list_plans(pdb) == []
    _s, v, run = _setup(pdb)
    pv = _plan(pdb, run)
    assert pv.status == "DRAFT" and pv.version_no == 1 and pv.source_run_fingerprint == run["run_fingerprint"] and get_code(pdb, pv).startswith("AP-")
    cov = ap.compute_coverage(pdb, pv)
    assert [t["milestone_code"] for t in cov["targets"]] == ["M1", "M2"]  # gap<=0 không có coverage row (không NO_GAP)
    assert {t["overall_combined_status"] for t in cov["targets"]} == {"NOT_COVERED"} and cov["targets"][0]["remaining_gap_after_plan"] == 500


def get_code(db, pv):
    return ap.get_plan(db, pv.plan_id).action_plan_code


def test_run_stays_immutable_and_no_auto_select(pdb):
    _s, _v, run = _setup(pdb)
    before = pdb.query(RoadmapProposal).count()
    pv = _plan(pdb, run)
    assert ap.version_items(pdb, pv.id) == [] and pdb.query(RoadmapProposal).count() == before
    assert all(p["decision_status"] is None for p in eng.run_view(pdb, pdb.get(RoadmapRun, run["id"]))["proposals"])


def test_reject_cross_run_proposal(pdb):
    s, v, run1 = _setup(pdb)
    _labor(pdb, "XN2", 5)  # baseline đổi => run mới (fingerprint khác)
    run2 = _run(pdb, v)["run"]
    assert run2["id"] != run1["id"]
    pv2 = _plan(pdb, run2)
    p1 = _pick(run1, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")
    with pytest.raises(HTTPException) as e:
        ap.add_item(pdb, ADMIN, pv2.id, {"proposal_id": p1["id"], "planned_effective_date": "2026-08-20"})
    assert e.value.status_code == 409 and "Run khác" in e.value.detail


def test_selection_independent_of_proposal_decision(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    p = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")
    assert p["decision_status"] is None  # SELECTED không bắt buộc
    it = ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": p["id"], "planned_effective_date": "2026-08-20"})
    assert it.inclusion_status == "COUNTED" and it.source_proposal_decision_snapshot is None
    before = ap.compute_coverage(pdb, pv)
    eng.decide_proposal(pdb, ADMIN, p["id"], "REJECTED", "đổi ý sau")  # decision đổi sau khi snapshot
    v = ap.item_view(pdb, ap.get_item(pdb, it.id))
    assert v["current_proposal_decision_changed"] is True and v["source_proposal_decision_snapshot"] is None
    assert ap.compute_coverage(pdb, pv) == before  # coverage dùng snapshot
    with pytest.raises(HTTPException) as e:  # nhưng không thêm được item mới từ proposal đang REJECTED
        ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": p["id"], "planned_effective_date": "2026-08-25"})
    assert e.value.status_code == 409


def test_calculated_vs_needs_input_vs_not_applicable(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    cap = _pick(run, "CAPACITY_CHANGE", "M1", status="NEEDS_INPUT")
    it = ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": cap["id"], "planned_effective_date": "2026-08-20"})
    assert it.inclusion_status == "UNRESOLVED" and it.planned_increment is None and it.selected_quantity is None and it.impact_persistence == "UNSPECIFIED"
    with pytest.raises(HTTPException):  # UNRESOLVED là full-line, không numeric scaling
        ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": cap["id"], "planned_effective_date": "2026-08-21", "selected_quantity": 1})
    na = [p for p in run["proposals"] if p["calc_status"] == "NOT_APPLICABLE"][0]
    with pytest.raises(HTTPException) as e:
        ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": na["id"], "planned_effective_date": "2026-08-20"})
    assert e.value.status_code == 422
    t = _cov(pdb, pv, "M1")
    assert t["overall_combined_status"] == "NOT_COVERED" and t["has_unresolved_actions"] is True and t["counted_resource_types"] == []
    tech = _pick(run, "TECHNOLOGY_ADOPTION", "M1")
    assert ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": tech["id"], "planned_effective_date": "2026-08-20"}).inclusion_status == "UNRESOLVED"


def test_calculated_can_be_saved_as_unresolved_fullline(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    p = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")
    it = ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": p["id"], "planned_effective_date": "2026-08-20", "as_unresolved": True})
    assert it.inclusion_status == "UNRESOLVED" and it.planned_increment is None
    assert _cov(pdb, pv, "M1")["planned_increment"] == 0.0


# =================================================================== partial integer selection
def test_partial_labor_and_machine_integer_selection(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    lab = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")
    mac = _pick(run, "MACHINE_PURCHASE", "M1")
    assert lab["quantity"] == 5 and mac["quantity"] == 2
    i1 = ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": lab["id"], "planned_effective_date": "2026-08-20", "selected_quantity": 3})
    assert i1.selected_quantity == 3 and i1.planned_increment == 360.0 and i1.productivity_value == 120.0 and i1.impact_persistence == "PERSISTENT" and i1.unit == "worker"  # 3×120, không 600×3/5
    i2 = ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": mac["id"], "planned_effective_date": "2026-08-20", "selected_quantity": 1})
    assert i2.planned_increment == 300.0 and i2.unit == "machine"
    default_full = ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": _pick(run, "LABOR_RECRUITMENT", "M2", "LAB-A@v1")["id"], "planned_effective_date": "2026-09-01"})
    assert default_full.selected_quantity == 6 and default_full.planned_increment == 720.0  # mặc định full-line = proposal.quantity


@pytest.mark.parametrize("q", [0, -1, 6, 2.5, True, "3"])
def test_invalid_selected_quantity_rejected(pdb, q):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    p = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")
    with pytest.raises(HTTPException):
        ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": p["id"], "planned_effective_date": "2026-08-20", "selected_quantity": q})
    assert ap.version_items(pdb, pv.id) == []


def test_split_same_proposal_across_dates_but_total_capped_no_duplicates(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    p = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")
    ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": p["id"], "planned_effective_date": "2026-08-10", "selected_quantity": 3})
    with pytest.raises(HTTPException) as e:
        ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": p["id"], "planned_effective_date": "2026-08-12", "selected_quantity": 3})  # 3+3 > 5
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": p["id"], "planned_effective_date": "2026-08-10", "selected_quantity": 1})  # trùng proposal+ngày
    assert e.value.status_code == 409
    ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": p["id"], "planned_effective_date": "2026-08-25", "selected_quantity": 2})
    t = _cov(pdb, pv, "M1")
    assert t["coverage_by_proposal_type"]["LABOR_RECRUITMENT"]["planned_increment"] == 600.0  # 3×120 + 2×120, tổng đúng 5 (không đếm trùng)


# =================================================================== effective date rules
def test_effective_date_rules(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    a = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")
    with pytest.raises(HTTPException) as e:
        ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": a["id"], "planned_effective_date": "2026-07-31"})  # trước ngày tạo run 2026-08-01
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": a["id"]})
    b = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-B@v1")  # rule B hiệu lực đến 2026-09-15
    with pytest.raises(HTTPException) as e:
        ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": b["id"], "planned_effective_date": "2026-09-20"})  # ngoài window => không COUNTED
    assert "hiệu lực" in e.value.detail
    it = ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": b["id"], "planned_effective_date": "2026-09-20", "as_unresolved": True})  # nhưng theo dõi được
    assert it.inclusion_status == "UNRESOLVED" and it.planned_increment is None
    ap.remove_item(pdb, ADMIN, it.id)  # (UNRESOLVED cùng target/type của proposal khác sẽ chặn COUNTED — xem test alternative)
    # sau milestone nguồn vẫn hợp lệ (không bắt buộc <= target_date)
    late = ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": a["id"], "planned_effective_date": "2026-09-05", "selected_quantity": 2})
    assert late.inclusion_status == "COUNTED"


# =================================================================== coverage / cumulative
def test_milestone_cumulative_coverage_persistent_and_negative_remaining(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    a1 = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")
    ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": a1["id"], "planned_effective_date": "2026-08-20"})  # 5 × 120 = 600 (>500)
    m1, m2 = _cov(pdb, pv, "M1"), _cov(pdb, pv, "M2")
    l1 = m1["coverage_by_proposal_type"]["LABOR_RECRUITMENT"]
    assert l1["planned_increment"] == 600.0 and l1["remaining_gap"] == -100.0 and l1["status"] == "OVER_COVERED"  # giữ dấu âm
    assert m1["remaining_gap_after_plan"] == -100.0 and m1["overall_combined_status"] == "OVER_COVERED"
    l2 = m2["coverage_by_proposal_type"]["LABOR_RECRUITMENT"]  # PERSISTENT: item của M1 vẫn hiệu lực ở M2 (MONTH↔MONTH, không cần cùng period_label)
    assert l2["planned_increment"] == 600.0 and l2["remaining_gap"] == 94.0 and l2["status"] == "PARTIALLY_COVERED"
    # item bắt đầu sau M1: không cover M1, có cover M2
    pv2 = ap.new_version(pdb, ADMIN, _submit_approve(pdb, pv).id)
    it = ap.version_items(pdb, pv2.id)[0]
    ap.remove_item(pdb, ADMIN, it.id)
    ap.add_item(pdb, ADMIN, pv2.id, {"proposal_id": a1["id"], "planned_effective_date": "2026-09-05"})
    assert _cov(pdb, pv2, "M1")["overall_combined_status"] == "NOT_COVERED"
    assert _cov(pdb, pv2, "M2")["coverage_by_proposal_type"]["LABOR_RECRUITMENT"]["planned_increment"] == 600.0


def test_exact_status_boundaries(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    a1 = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")
    ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": a1["id"], "planned_effective_date": "2026-08-20", "selected_quantity": 4})  # 480 < 500
    assert _cov(pdb, pv, "M1")["overall_combined_status"] == "PARTIALLY_COVERED"
    mac = _pick(run, "MACHINE_PURCHASE", "M1")
    item = ap.get_item(pdb, ap.version_items(pdb, pv.id)[0].id)
    ap.remove_item(pdb, ADMIN, item.id)
    ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": mac["id"], "planned_effective_date": "2026-08-20", "selected_quantity": 2})  # 600 > 500
    assert _cov(pdb, pv, "M1")["overall_combined_status"] == "OVER_COVERED"


def test_labor_and_machine_never_summed_mixed_not_combinable(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")["id"], "planned_effective_date": "2026-08-20", "selected_quantity": 2})  # 240
    ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": _pick(run, "MACHINE_PURCHASE", "M1")["id"], "planned_effective_date": "2026-08-20", "selected_quantity": 1})  # 300
    t = _cov(pdb, pv, "M1")
    assert t["mixed_resource_types"] is True and t["counted_resource_types"] == ["LABOR_RECRUITMENT", "MACHINE_PURCHASE"]
    assert t["overall_combined_status"] == "NOT_COMBINABLE" and t["planned_increment"] is None and t["remaining_gap_after_plan"] is None
    assert t["coverage_by_proposal_type"]["LABOR_RECRUITMENT"]["remaining_gap"] == 260.0 and t["coverage_by_proposal_type"]["MACHINE_PURCHASE"]["remaining_gap"] == 200.0
    assert "combined_remaining_gap" not in t


def test_alternative_rules_same_target_type_blocked_and_unresolved_cannot_bypass(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    a = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")
    b = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-B@v1")
    ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": a["id"], "planned_effective_date": "2026-08-20"})
    with pytest.raises(HTTPException) as e:
        ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": b["id"], "planned_effective_date": "2026-08-20"})
    assert e.value.status_code == 409 and "phương án thay thế" in e.value.detail
    with pytest.raises(HTTPException) as e:  # UNRESOLVED cùng target/type không bypass khi đã có COUNTED
        ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": b["id"], "planned_effective_date": "2026-08-20", "as_unresolved": True})
    assert e.value.status_code == 409
    # ngược lại: có UNRESOLVED của proposal khác thì cũng không thêm được COUNTED thứ hai
    pv2 = _plan(pdb, run, "AP2")
    ap.add_item(pdb, ADMIN, pv2.id, {"proposal_id": b["id"], "planned_effective_date": "2026-08-20", "as_unresolved": True})
    with pytest.raises(HTTPException):
        ap.add_item(pdb, ADMIN, pv2.id, {"proposal_id": a["id"], "planned_effective_date": "2026-08-20"})
    # thay selection ở DRAFT được
    ap.remove_item(pdb, ADMIN, ap.version_items(pdb, pv2.id)[0].id)
    assert ap.add_item(pdb, ADMIN, pv2.id, {"proposal_id": a["id"], "planned_effective_date": "2026-08-20"}).inclusion_status == "COUNTED"


def test_one_time_is_never_counted_in_task7(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    it = ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")["id"], "planned_effective_date": "2026-08-20"})
    it.impact_persistence = "ONE_TIME"  # forward-compatible enum
    pdb.commit()
    assert _cov(pdb, pv, "M1")["overall_combined_status"] == "NOT_COVERED"


# =================================================================== snapshot / governance
def _submit_approve(db, pv):
    ap.submit_review(db, ADMIN, pv.id)
    return ap.approve(db, ADMIN2, pv.id)


def test_snapshot_retained_after_rule_retire_and_run_change(pdb):
    _s, v, run = _setup(pdb)
    pv = _plan(pdb, run)
    p = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")
    ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": p["id"], "planned_effective_date": "2026-08-20", "selected_quantity": 4})
    frozen = ap.compute_coverage(pdb, pv)
    rule = [r for r in xr.list_rules(pdb) if r.rule_code == "LAB-A"][0]
    xr.retire_rule(pdb, ADMIN2, rule.id, "hết hiệu lực")
    v2 = xr.new_version(pdb, ADMIN, rule.id)
    xr.update_rule(pdb, ADMIN, v2.id, {"productivity_value": 999.0})
    assert ap.compute_coverage(pdb, pv) == frozen  # không đọc live rule
    it = ap.item_view(pdb, ap.version_items(pdb, pv.id)[0])
    assert it["productivity_value"] == 120.0 and it["snapshot"]["lineage"]["rule"]["rule_code"] == "LAB-A" and it["snapshot"]["lineage"]["rule"]["productivity_value"] == 120.0
    assert it["snapshot"]["source_run_fingerprint"] == run["run_fingerprint"] and it["snapshot"]["lineage"]["capacity_impact"]["proposed_increment"] == 600.0
    assert it["snapshot"]["lineage"]["evidence_refs"][0]["source_ref"] == "IE-2026-01"


def test_governance_four_eyes_immutability_and_archive(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    with pytest.raises(HTTPException):
        ap.submit_review(pdb, ADMIN, pv.id)  # cần >=1 item
    with pytest.raises(HTTPException) as e:
        ap.approve(pdb, ADMIN2, pv.id)  # DRAFT không approve trực tiếp
    assert e.value.status_code == 409
    p = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")
    ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": p["id"], "planned_effective_date": "2026-08-20"})
    ap.submit_review(pdb, ADMIN, pv.id)
    pv = ap.get_version(pdb, pv.id)
    assert pv.status == "UNDER_REVIEW" and pv.reviewed_by == "admin" and pv.coverage_json["targets"]
    with pytest.raises(HTTPException) as e:
        ap.approve(pdb, ADMIN, pv.id)
    assert e.value.status_code == 409 and "Four-eyes" in e.value.detail
    with pytest.raises(HTTPException):
        ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": p["id"], "planned_effective_date": "2026-08-22", "selected_quantity": 1})  # UNDER_REVIEW bất biến
    ap.approve(pdb, ADMIN2, pv.id)
    pv = ap.get_version(pdb, pv.id)
    assert pv.status == "APPROVED" and pv.approved_by == "admin2"
    item = ap.version_items(pdb, pv.id)[0]
    for fn in (lambda: ap.remove_item(pdb, ADMIN, item.id), lambda: ap.update_item(pdb, ADMIN, item.id, {"selected_quantity": 1}), lambda: ap.submit_review(pdb, ADMIN, pv.id)):
        with pytest.raises(HTTPException):
            fn()
    with pytest.raises(HTTPException):
        ap.archive(pdb, ADMIN2, pv.id, " ")
    ap.archive(pdb, ADMIN2, pv.id, "kế hoạch thay thế")
    assert ap.get_version(pdb, pv.id).status == "ARCHIVED"
    with pytest.raises(HTTPException):
        ap.archive(pdb, ADMIN2, pv.id, "again")
    assert [h["to_status"] for h in ap.version_history(pdb, pv.id)] == ["DRAFT", "UNDER_REVIEW", "APPROVED", "ARCHIVED"]


def test_approve_allows_remaining_gap_and_unresolved(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": _pick(run, "CAPACITY_CHANGE", "M1")["id"], "planned_effective_date": "2026-08-20"})  # chỉ unresolved, chưa COVERED
    assert _submit_approve(pdb, pv).status == "APPROVED"


def test_approve_verifies_frozen_coverage_and_snapshots(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")["id"], "planned_effective_date": "2026-08-20"})
    ap.submit_review(pdb, ADMIN, pv.id)
    v = ap.get_version(pdb, pv.id)
    v.coverage_json = {**v.coverage_json, "targets": []}  # giả lập coverage đóng băng bị sửa
    pdb.commit()
    with pytest.raises(HTTPException) as e:
        ap.approve(pdb, ADMIN2, pv.id)
    assert e.value.status_code == 409 and "Coverage" in e.value.detail


def test_new_version_clones_items_keeps_source_run(pdb):
    _s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")["id"], "planned_effective_date": "2026-08-20", "selected_quantity": 4})
    with pytest.raises(HTTPException):
        ap.new_version(pdb, ADMIN, pv.id)  # còn DRAFT
    _submit_approve(pdb, pv)
    v2 = ap.new_version(pdb, ADMIN, pv.id)
    assert v2.version_no == 2 and v2.status == "DRAFT" and v2.source_run_id == pv.source_run_id and v2.copied_from_version_id == pv.id and v2.reviewed_by == ""
    (c,) = ap.version_items(pdb, v2.id)
    assert c.selected_quantity == 4 and c.planned_increment == 480.0 and c.snapshot_json["lineage"]["rule"]["productivity_value"] == 120.0
    def nums(cv):  # item_id khác (clone) nhưng số liệu coverage phải giống hệt
        return [(t["milestone_code"], t["overall_combined_status"], t["planned_increment"], t["remaining_gap_after_plan"]) for t in cv["targets"]]

    assert nums(v2.coverage_json) == nums(ap.get_version(pdb, pv.id).coverage_json)  # recompute từ snapshot cho cùng kết quả
    with pytest.raises(HTTPException):
        ap.new_version(pdb, ADMIN, v2.id)  # đã có DRAFT


def test_compare_versions_and_families_no_ranking(pdb):
    s, v, run = _setup(pdb)
    pv1 = _plan(pdb, run)
    a = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")
    ap.add_item(pdb, ADMIN, pv1.id, {"proposal_id": a["id"], "planned_effective_date": "2026-08-20", "selected_quantity": 4})
    _submit_approve(pdb, pv1)
    pv2 = ap.new_version(pdb, ADMIN, pv1.id)
    it = ap.version_items(pdb, pv2.id)[0]
    ap.update_item(pdb, ADMIN, it.id, {"selected_quantity": 5})
    c = ap.compare(pdb, pv1.id, pv2.id)
    assert c["same_source_run"] is True and any(t["changed"] for t in c["targets"]) and any(i["changed"] for i in c["items"])
    other = _plan(pdb, run, "B")  # family khác, cùng scenario_version
    assert ap.compare(pdb, pv1.id, other.id)["targets"]
    assert not {"rank", "score", "winner", "best"} & set(c) and not any({"rank", "score", "winner"} & set(x) for x in c["targets"] + c["items"])
    # khác scenario_version => chặn
    s2, v2 = _scenario(pdb, name="Other")
    m = _ms(pdb, v2, "MX", "2026-08-31")
    _tgt(pdb, m, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="PACK_QTY", target_value=2000)
    _ready(pdb, v2)
    r2 = _run(pdb, v2)["run"]
    foreign = _plan(pdb, r2, "C")
    with pytest.raises(HTTPException) as e:
        ap.compare(pdb, pv1.id, foreign.id)
    assert e.value.status_code == 409
    # khác source_run cùng scenario_version: hiện rõ run A/B
    _labor(pdb, "XN2", 5)
    run_b = _run(pdb, v)["run"]
    other_run = _plan(pdb, run_b, "D")
    cmpb = ap.compare(pdb, pv1.id, other_run.id)
    assert cmpb["same_source_run"] is False and cmpb["source_runs"]["a"]["fingerprint"] != cmpb["source_runs"]["b"]["fingerprint"]


# =================================================================== API
def test_api_permissions_and_http_routes(pdb):
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.db.session import get_db
    from app.main import app

    _s, _v, run = _setup(pdb)
    pid = _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")["id"]
    ver = rm_api.create_action_plan(run["id"], rm_api.ActionPlanBody(name="API"), pdb, PLANNER)  # planner có manage
    rm_api.add_action_item(ver["id"], rm_api.ActionItemBody(proposal_id=pid, planned_effective_date="2026-08-20"), pdb, PLANNER)
    rm_api.submit_action_plan_review(ver["id"], pdb, PLANNER)
    with pytest.raises(HTTPException) as e:
        rm_api.approve_action_plan(ver["id"], pdb, PLANNER)  # thiếu roadmap.approve
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        rm_api.archive_action_plan(ver["id"], rm_api.RetireBody(reason="x"), pdb, PLANNER)
    assert e.value.status_code == 403
    assert rm_api.approve_action_plan(ver["id"], pdb, ADMIN2)["status"] == "APPROVED"
    admin = SimpleNamespace(username="admin", role="ADMIN", id=1, is_active=True, must_change_password=False)
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_db] = lambda: pdb
    try:
        c = TestClient(app)
        B = "/api/roadmap"
        assert len(c.get(f"{B}/action-plans").json()) == 1
        v2 = c.post(f"{B}/runs/{run['id']}/action-plans", json={"name": "HTTP"}).json()
        assert c.post(f"{B}/action-plan-versions/{v2['id']}/items", json={"proposal_id": pid, "planned_effective_date": "2026-07-01"}).status_code == 422
        r = c.post(f"{B}/action-plan-versions/{v2['id']}/items", json={"proposal_id": pid, "planned_effective_date": "2026-08-20", "selected_quantity": 2})
        assert r.status_code == 200 and r.json()["planned_increment"] == 240.0
        assert c.put(f"{B}/action-plan-items/{r.json()['id']}", json={"selected_quantity": 3}).json()["planned_increment"] == 360.0
        assert c.get(f"{B}/action-plan-versions/{v2['id']}").json()["coverage"]["targets"][0]["coverage_by_proposal_type"]["LABOR_RECRUITMENT"]["planned_increment"] == 360.0
        assert c.get(f"{B}/action-plan-compare/{ver['id']}/{v2['id']}").status_code == 200
        assert c.post(f"{B}/action-plan-versions/{v2['id']}/submit-review").status_code == 200
        assert c.post(f"{B}/action-plan-versions/{v2['id']}/approve").status_code == 409  # cùng reviewer
        assert c.get(f"{B}/action-plan-versions/{v2['id']}/history").json()[-1]["to_status"] == "UNDER_REVIEW"
        assert c.get(f"{B}/options").json()["action_plan_statuses"] == ["DRAFT", "UNDER_REVIEW", "APPROVED", "ARCHIVED"]
        assert c.delete(f"{B}/action-plan-items/{r.json()['id']}").status_code == 409  # UNDER_REVIEW bất biến
    finally:
        app.dependency_overrides.clear()


def test_scenario_archived_blocks_action_plan_changes(pdb):
    s, _v, run = _setup(pdb)
    pv = _plan(pdb, run)
    rm.transition_scenario(pdb, ADMIN, s.id, "ARCHIVED", "test")
    with pytest.raises(HTTPException):
        ap.add_item(pdb, ADMIN, pv.id, {"proposal_id": _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")["id"], "planned_effective_date": "2026-08-20"})
    with pytest.raises(HTTPException):
        _plan(pdb, run, "X")


def _add_labor(db, run, pv):
    return ap.add_item(db, ADMIN, pv.id, {"proposal_id": _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")["id"], "planned_effective_date": "2026-08-20"})


def test_archived_scenario_blocks_submit_review_and_approve_but_not_archive(pdb):
    s, _v, run = _setup(pdb)
    d = _plan(pdb, run, "DRAFT-PLAN")
    _add_labor(pdb, run, d)
    r = _plan(pdb, run, "REVIEW-PLAN")
    _add_labor(pdb, run, r)
    ap.submit_review(pdb, ADMIN, r.id)  # UNDER_REVIEW trước khi Scenario bị ARCHIVED
    a = _plan(pdb, run, "APPROVED-PLAN")
    _add_labor(pdb, run, a)
    _submit_approve(pdb, a)
    rm.transition_scenario(pdb, ADMIN, s.id, "ARCHIVED", "kết thúc")
    with pytest.raises(HTTPException) as e:  # 1) DRAFT -> UNDER_REVIEW
        ap.submit_review(pdb, ADMIN, d.id)
    assert e.value.status_code == 409 and ap.get_version(pdb, d.id).status == "DRAFT"
    with pytest.raises(HTTPException) as e:  # 2) UNDER_REVIEW -> APPROVED
        ap.approve(pdb, ADMIN2, r.id)
    assert e.value.status_code == 409 and ap.get_version(pdb, r.id).status == "UNDER_REVIEW"
    assert ap.archive(pdb, ADMIN2, a.id, "dọn dẹp").status == "ARCHIVED"  # 3) vẫn đóng được plan APPROVED
    # 4) guard cũ vẫn giữ
    with pytest.raises(HTTPException):
        _add_labor(pdb, run, d)
    with pytest.raises(HTTPException):
        ap.update_item(pdb, ADMIN, ap.version_items(pdb, d.id)[0].id, {"selected_quantity": 1})
    with pytest.raises(HTTPException):
        ap.new_version(pdb, ADMIN, a.id)
    with pytest.raises(HTTPException):
        _plan(pdb, run, "X")
