"""Task 8 (Issue #17) — Investment Evidence & Executive Decision Package. Evidence fixture chỉ tồn tại trong test; production không seed giá/cost nào."""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import roadmap as rm_api
from app.db.session import Base
from app.models.future_technology import FutureTechnologyCandidate, FutureTechnologyEvidence
from app.models.resources import MachineModel
from app.models.roadmap import RoadmapAssetRef, RoadmapCostEvidence, RoadmapDecisionPackage, RoadmapPackageBinding
from app.services import roadmap as rm
from app.services import roadmap_action_plan as ap
from app.services import roadmap_cost as rc
from app.services import roadmap_decision_package as dp
from tests.test_roadmap import ADMIN, PLANNER, db  # noqa: F401
from tests.test_roadmap_action_plan import _pick, _plan, _setup, _submit_approve, pdb  # noqa: F401
from tests.test_roadmap_exec import ADMIN2

FORBIDDEN = ("grand_total", "roi", "npv", "irr", "payback", "rank", "score", "cheapest", "best", "winner", "recommendation", "total_investment")


@pytest.fixture()
def cdb(pdb, monkeypatch):  # noqa: F811
    Base.metadata.create_all(pdb.get_bind(), tables=[m.__table__ for m in (RoadmapCostEvidence, RoadmapAssetRef, RoadmapDecisionPackage, RoadmapPackageBinding)])
    for mod in (rc, dp):
        monkeypatch.setattr(mod, "write_audit", lambda *a, **kw: None)
    return pdb


def _mev(code="M-EV", **kw):
    d = {"evidence_code": code, "cost_family": "MACHINE_UNIT_PRICE", "machine_type_code": "1K", "amount": "1500.5", "currency": "USD", "price_basis": "EX_WORKS_MACHINE_ONLY",
         "source_kind": "APPROVED_CONTRACT_PRICE", "source_ref": "CONTRACT-1", "evidence_date": "2026-01-05", "effective_from": "2026-01-01"}
    d.update(kw)
    return d


def _lev(code="L-EV", **kw):
    d = {"evidence_code": code, "cost_family": "LABOR_COST_PER_WORKER_PERIOD", "scope_type": "TOTAL", "cost_period": "MONTH", "amount": "800", "currency": "USD",
         "source_kind": "HR_APPROVED_COST_STANDARD", "source_ref": "HR-STD-1", "evidence_date": "2026-01-05", "effective_from": "2026-01-01"}
    d.update(kw)
    return d


def _ev(db, d, approve=True):
    e = rc.create_evidence(db, ADMIN, d)
    if approve:
        rc.submit_review(db, ADMIN, e.id)
        e = rc.approve_evidence(db, ADMIN2, e.id)
    return e


def _base(db, machine_qty=2, labor_qty=3, date="2026-08-20", extra=False):
    """Action Plan APPROVED: labor 3 worker (M1), machine 2 (M1), capacity UNRESOLVED; optional extra items ở M2."""
    s, v, run = _setup(db)
    pv = _plan(db, run)
    items = {}
    items["lab"] = ap.add_item(db, ADMIN, pv.id, {"proposal_id": _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")["id"], "planned_effective_date": date, "selected_quantity": labor_qty})
    items["mac"] = ap.add_item(db, ADMIN, pv.id, {"proposal_id": _pick(run, "MACHINE_PURCHASE", "M1")["id"], "planned_effective_date": date, "selected_quantity": machine_qty})
    items["cap"] = ap.add_item(db, ADMIN, pv.id, {"proposal_id": _pick(run, "CAPACITY_CHANGE", "M1")["id"], "planned_effective_date": date})
    items["tech"] = ap.add_item(db, ADMIN, pv.id, {"proposal_id": _pick(run, "TECHNOLOGY_ADOPTION", "M1")["id"], "planned_effective_date": date})
    if extra:
        items["lab2"] = ap.add_item(db, ADMIN, pv.id, {"proposal_id": _pick(run, "LABOR_RECRUITMENT", "M2", "LAB-A@v1")["id"], "planned_effective_date": "2026-09-05", "selected_quantity": 2})
        items["mac2"] = ap.add_item(db, ADMIN, pv.id, {"proposal_id": _pick(run, "MACHINE_PURCHASE", "M2")["id"], "planned_effective_date": "2026-10-05", "selected_quantity": 1})
    apv = _submit_approve(db, pv)
    return s, v, run, apv, items


def _pkg(db, apv):
    return dp.create_package(db, ADMIN, apv.id, {"note": "t"})


def _line(pkg, item_id):
    pj = pkg.package_json
    return [x for x in pj["selected_actions"] + pj["unresolved_actions"] if x["item_id"] == item_id][0]


def _freeze(db, pkg):
    dp.submit_review(db, ADMIN, pkg.id)
    return dp.get_package(db, pkg.id)


def _walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield path + "/" + str(k), k
            yield from _walk(v, path + "/" + str(k))
    elif isinstance(o, list):
        for x in o:
            yield from _walk(x, path)


def _no_forbidden(o):
    bad = [p for p, k in _walk(o) if str(k).lower() in FORBIDDEN]
    assert not bad, bad


# =================================================================== cost evidence governance
def test_no_cost_evidence_or_asset_or_package_seeded(cdb):
    assert rc.list_evidence(cdb) == [] and rc.list_assets(cdb) == [] and dp.list_packages(cdb) == []


@pytest.mark.parametrize("family,kind,ok", [
    ("M", "SUPPLIER_QUOTATION", True), ("M", "APPROVED_CONTRACT_PRICE", True), ("M", "APPROVED_BUDGET_STANDARD", True), ("M", "CONTROLLED_PURCHASE_HISTORY", True),
    ("M", "HR_APPROVED_COST_STANDARD", False), ("M", "BROCHURE", False), ("M", "CLAIMED", False), ("M", "ESTIMATE", False), ("M", "DEFAULT", False), ("M", "PLACEHOLDER", False),
    ("M", "UNVERIFIED_WEB_PRICE", False), ("L", "HR_APPROVED_COST_STANDARD", True), ("L", "APPROVED_BUDGET_STANDARD", True), ("L", "CONTROLLED_PURCHASE_HISTORY", False),
    ("L", "SUPPLIER_QUOTATION", False), ("L", "ESTIMATE", False),
])
def test_source_kind_allowlist_per_family(cdb, family, kind, ok):
    d = _mev(source_kind=kind, vendor="ACME", quote_valid_until="2026-12-31") if family == "M" else _lev(source_kind=kind, vendor="ACME", quote_valid_until="2026-12-31")
    e = rc.create_evidence(cdb, ADMIN, d)  # lưu DRAFT/UNDER_REVIEW được với mọi kind
    rc.submit_review(cdb, ADMIN, e.id)
    if ok:
        assert rc.approve_evidence(cdb, ADMIN2, e.id).status == "APPROVED"
    else:
        with pytest.raises(HTTPException) as x:
            rc.approve_evidence(cdb, ADMIN2, e.id)
        assert x.value.status_code == 409 and rc.get_evidence(cdb, e.id).status == "UNDER_REVIEW"


def test_evidence_workflow_four_eyes_immutable_versioning_retire(cdb):
    e = rc.create_evidence(cdb, ADMIN, _mev())
    with pytest.raises(HTTPException):
        rc.approve_evidence(cdb, ADMIN2, e.id)  # DRAFT
    rc.submit_review(cdb, ADMIN, e.id)
    with pytest.raises(HTTPException) as x:
        rc.approve_evidence(cdb, ADMIN, e.id)
    assert x.value.status_code == 409 and "Four-eyes" in x.value.detail
    rc.approve_evidence(cdb, ADMIN2, e.id)
    e = rc.get_evidence(cdb, e.id)
    with pytest.raises(HTTPException):
        rc.update_evidence(cdb, ADMIN, e.id, {"amount": "9"})  # APPROVED bất biến
    v2 = rc.new_version(cdb, ADMIN, e.id)
    assert v2.evidence_version == 2 and v2.status == "DRAFT" and v2.amount == e.amount
    with pytest.raises(HTTPException):
        rc.new_version(cdb, ADMIN, e.id)  # đã có DRAFT
    with pytest.raises(HTTPException):
        rc.retire_evidence(cdb, ADMIN2, v2.id, "x")  # DRAFT không retire
    with pytest.raises(HTTPException):
        rc.retire_evidence(cdb, ADMIN2, e.id, " ")
    assert rc.retire_evidence(cdb, ADMIN2, e.id, "hết hiệu lực").status == "RETIRED"
    assert [h["to_status"] for h in rm.list_history(cdb, "COST_EVID", e.id)] == ["DRAFT", "UNDER_REVIEW", "APPROVED", "RETIRED"]
    # nhiều evidence APPROVED cùng subject/window hợp lệ (không overlap-block / không supersede)
    _ev(cdb, _mev("M-A")), _ev(cdb, _mev("M-B", amount="1400"))
    assert [x.status for x in rc.list_evidence(cdb, status="APPROVED")] == ["APPROVED", "APPROVED"]


def test_evidence_validation_and_completeness(cdb):
    for bad in (_mev(amount="0"), _mev(amount="-1"), _mev(amount="abc"), _mev(amount="1.1234567"), _mev(currency="usd1"), _mev(currency="US"), _mev(cost_family="TECHNOLOGY_COST"),
                _mev(machine_type_code="NOPE"), _mev(price_basis="VAT_INCLUDED"), _mev(effective_to="2025-01-01"), _mev(scope_type="TOTAL"),
                _lev(cost_period="DAY"), _lev(scope_type="FACTORY", scope_value="ZZ"), _lev(machine_type_code="1K"), _lev(amount=True)):
        with pytest.raises(HTTPException):
            rc.create_evidence(cdb, ADMIN, {**bad, "evidence_code": "BAD"})
    assert cdb.query(RoadmapCostEvidence).count() == 0
    for missing, kw in (("price_basis", {"price_basis": ""}), ("source_ref", {"source_ref": ""}), ("evidence_date", {"evidence_date": None}), ("effective_from", {"effective_from": None})):
        e = rc.create_evidence(cdb, ADMIN, _mev(f"M-{missing}", **kw))
        with pytest.raises(HTTPException) as x:
            rc.submit_review(cdb, ADMIN, e.id)
        assert missing in x.value.detail
    q = rc.create_evidence(cdb, ADMIN, _mev("M-Q", source_kind="SUPPLIER_QUOTATION"))
    with pytest.raises(HTTPException) as x:
        rc.submit_review(cdb, ADMIN, q.id)
    assert "vendor" in x.value.detail and "quote_valid_until" in x.value.detail
    l = rc.create_evidence(cdb, ADMIN, _lev("L-X", cost_period="MONTH", source_ref=""))
    with pytest.raises(HTTPException):
        rc.submit_review(cdb, ADMIN, l.id)
    assert rc.create_evidence(cdb, ADMIN, _mev("M-OK", amount="0.000001")).amount == Decimal("0.000001")  # scale 6, Decimal chính xác


def test_asset_refs_reference_only(cdb):
    for ok in ({"subject_type": "MACHINE_TYPE", "subject_ref": "1K", "asset_kind": "IMAGE", "uri": "https://cdn.example.com/a.png"},
               {"subject_type": "MACHINE_TYPE", "subject_ref": "1K", "asset_kind": "MODEL_3D", "asset_ref": "assets/3d/1k.glb"},
               {"subject_type": "MACHINE_TYPE", "subject_ref": "1K", "asset_kind": "DATASHEET", "uri": "https://example.com/ds.pdf"}):
        assert rc.create_asset(cdb, ADMIN, ok).active is True
    for bad in ({"uri": "http://x.com/a"}, {"uri": "javascript:alert(1)"}, {"uri": "data:text/html;base64,AAA"}, {"uri": "file:///etc/passwd"}, {"uri": "https://x.com/<script>"},
                {"asset_ref": "javascript:alert(1)"}, {"asset_ref": "data:x"}, {"asset_ref": "a b"}, {"uri": "https://x.com/a", "asset_ref": "y"}, {}):
        with pytest.raises(HTTPException):
            rc.create_asset(cdb, ADMIN, {"subject_type": "MACHINE_TYPE", "subject_ref": "1K", "asset_kind": "IMAGE", **bad})
    for bad in ({"subject_ref": "NOPE"}, {"asset_kind": "VIDEO"}, {"subject_type": "MACHINE_MODEL", "subject_ref": "99"}):
        with pytest.raises(HTTPException):
            rc.create_asset(cdb, ADMIN, {"subject_type": "MACHINE_TYPE", "subject_ref": "1K", "asset_kind": "IMAGE", "uri": "https://x.com/a", **bad})
    a = rc.list_assets(cdb)[0]
    assert rc.set_asset_active(cdb, ADMIN, a.id, False).active is False and len(rc.list_assets(cdb, active_only=True)) == 2


# =================================================================== package creation / unpriced
def test_package_only_from_approved_action_plan(cdb):
    _s, _v, run = _setup(cdb)
    pv = _plan(cdb, run)
    ap.add_item(cdb, ADMIN, pv.id, {"proposal_id": _pick(run, "LABOR_RECRUITMENT", "M1", "LAB-A@v1")["id"], "planned_effective_date": "2026-08-20"})
    with pytest.raises(HTTPException) as x:
        dp.create_package(cdb, ADMIN, pv.id, {})  # DRAFT
    assert x.value.status_code == 409
    ap.submit_review(cdb, ADMIN, pv.id)
    with pytest.raises(HTTPException):
        dp.create_package(cdb, ADMIN, pv.id, {})  # UNDER_REVIEW
    apv = ap.approve(cdb, ADMIN2, pv.id)
    p = dp.create_package(cdb, ADMIN, apv.id, {})
    assert p.status == "DRAFT" and p.package_code.startswith("DP-") and p.package_no == 1
    with pytest.raises(HTTPException):
        dp.create_package(cdb, ADMIN, apv.id, {})  # đã có package mở


def test_without_evidence_everything_unpriced_no_invented_numbers(cdb):
    _s, _v, _run, apv, items = _base(cdb)
    pkg = _pkg(cdb, apv)
    pj = pkg.package_json
    assert pj["completeness"]["pricing"] == "UNPRICED" and pj["direct_cost_summary"]["MACHINE_CAPEX"] == [] and pj["direct_cost_summary"]["LABOR_RECURRING_COST"] == []
    assert _line(pkg, items["mac"].id)["cost_status_reason"] == "MISSING_PRICE_EVIDENCE" and _line(pkg, items["lab"].id)["cost_status_reason"] == "MISSING_LABOR_COST_BASIS"
    assert {"MISSING_PRICE_EVIDENCE", "MISSING_LABOR_COST_BASIS", "UNPRICED_ACTION", "UNRESOLVED_ACTION"} <= set(pj["warning_codes"])
    assert all(x["amount"] is None for x in pj["selected_actions"] + pj["unresolved_actions"])
    assert _line(pkg, items["cap"].id)["cost_status_reason"] == "UNSUPPORTED_COST_FAMILY" and _line(pkg, items["tech"].id)["cost_status_reason"] == "UNSUPPORTED_COST_FAMILY"
    assert pj["completeness"]["unresolved_count"] == 2
    _no_forbidden(pj)


def test_unapproved_or_wrong_evidence_cannot_be_bound_or_priced(cdb):
    _s, _v, _run, apv, items = _base(cdb)
    pkg = _pkg(cdb, apv)
    draft = _ev(cdb, _mev("M-D"), approve=False)
    with pytest.raises(HTTPException):
        dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": draft.id})  # chưa APPROVED
    lab_ev, mac_ev = _ev(cdb, _lev()), _ev(cdb, _mev())
    with pytest.raises(HTTPException):
        dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": lab_ev.id})  # sai family
    with pytest.raises(HTTPException):
        dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["lab"].id, "evidence_id": mac_ev.id})
    for k in ("cap", "tech"):
        with pytest.raises(HTTPException):
            dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items[k].id, "evidence_id": mac_ev.id})  # unresolved/technology/capacity không bind
    other = _ev(cdb, _mev("M-2K", machine_type_code="2K"))
    with pytest.raises(HTTPException):
        dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": other.id})  # sai machine_type
    fev = _ev(cdb, _lev("L-F", scope_type="FACTORY", scope_value="XN1"))
    with pytest.raises(HTTPException):
        dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["lab"].id, "evidence_id": fev.id})  # scope phải exact
    assert cdb.query(RoadmapPackageBinding).count() == 0


# =================================================================== arithmetic
def test_machine_and_labor_exact_multiplication_and_grouping(cdb):
    _s, _v, _run, apv, items = _base(cdb, machine_qty=2, labor_qty=3)
    m = _ev(cdb, _mev(amount="1500.5"))
    l = _ev(cdb, _lev(amount="800.25"))
    pkg = _pkg(cdb, apv)
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": m.id})
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["lab"].id, "evidence_id": l.id})
    pkg = dp.get_package(cdb, pkg.id)
    ml, ll = _line(pkg, items["mac"].id), _line(pkg, items["lab"].id)
    assert ml["cost_status"] == "PRICED" and ml["amount"] == "3001.000000" and ml["cost_class"] == "MACHINE_CAPEX" and ml["currency"] == "USD" and ml["price_basis"] == "EX_WORKS_MACHINE_ONLY"
    assert ll["amount"] == "2400.750000" and ll["cost_class"] == "LABOR_RECURRING_COST" and ll["cost_period"] == "MONTH"
    s = pkg.package_json["direct_cost_summary"]
    assert s["MACHINE_CAPEX"][0]["currency"] == "USD" and s["MACHINE_CAPEX"][0]["amount"] == "3001.000000" and s["LABOR_RECURRING_COST"][0]["amount"] == "2400.750000"  # tách, không cộng CAPEX+OPEX
    assert pkg.package_json["completeness"] == {"pricing": "COMPLETE_PRICING", "supported_action_count": 2, "priced_action_count": 2, "unresolved_count": 2}
    assert [u["reason"] for u in s["UNPRICED_ACTIONS"]] == ["UNSUPPORTED_COST_FAMILY", "UNSUPPORTED_COST_FAMILY"]
    _no_forbidden(pkg.package_json)


def test_decimal_arithmetic_has_no_float_error(cdb):
    _s, _v, _run, apv, items = _base(cdb, machine_qty=2, labor_qty=3)
    pkg = _pkg(cdb, apv)
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["lab"].id, "evidence_id": _ev(cdb, _lev(amount="0.1")).id})  # 3 × 0.1 = 0.3 (float: 0.30000000000000004)
    assert _line(dp.get_package(cdb, pkg.id), items["lab"].id)["amount"] == "0.300000"


def test_milestone_buckets_run_rate_and_mixed_currency_groups(cdb):
    _s, _v, _run, apv, items = _base(cdb, extra=True)
    pkg = _pkg(cdb, apv)
    usd_m, usd_l, vnd_l = _ev(cdb, _mev()), _ev(cdb, _lev()), _ev(cdb, _lev("L-VND", amount="20000000", currency="VND"))
    vnd_m = _ev(cdb, _mev("M-VND", amount="30000000", currency="VND"))
    for item, ev in ((items["mac"], usd_m), (items["lab"], usd_l), (items["lab2"], vnd_l), (items["mac2"], vnd_m)):
        dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": item.id, "evidence_id": ev.id})
    pkg = dp.get_package(cdb, pkg.id)
    pj = pkg.package_json
    assert _line(pkg, items["mac"].id)["milestone_bucket"] == "M1" and _line(pkg, items["lab2"].id)["milestone_bucket"] == "M2" and _line(pkg, items["mac2"].id)["milestone_bucket"] == "AFTER_LAST_MILESTONE"
    cap = {g["currency"]: g for g in pj["direct_cost_summary"]["MACHINE_CAPEX"]}
    assert set(cap) == {"USD", "VND"} and cap["USD"]["amount"] == "3001.000000" and cap["VND"]["by_milestone_bucket"] == {"AFTER_LAST_MILESTONE": "30000000.000000"}
    lab = {(g["currency"], g["cost_period"]): g["amount"] for g in pj["direct_cost_summary"]["LABOR_RECURRING_COST"]}
    assert lab == {("USD", "MONTH"): "2400.000000", ("VND", "MONTH"): "40000000.000000"}  # nhóm riêng, không FX
    assert "CURRENCY_MISMATCH" not in pj["warning_codes"]
    rr = [(r["milestone_code"], r["currency"], r["run_rate_per_period"]) for r in pj["direct_cost_summary"]["labor_run_rate_by_milestone"]]
    assert ("M1", "USD", "2400.000000") in rr and ("M2", "USD", "2400.000000") in rr and ("M2", "VND", "40000000.000000") in rr and not any(r[0] == "M1" and r[1] == "VND" for r in rr)  # run-rate, không tích lũy
    _no_forbidden(pj)


# =================================================================== effective / quote / period / identity
def test_multiple_approved_quotes_no_auto_choice_until_user_binds(cdb):
    _s, _v, _run, apv, items = _base(cdb)
    _ev(cdb, _mev("Q1", amount="1000")), _ev(cdb, _mev("Q2", amount="900"))  # 2 evidence cùng match
    pkg = _pkg(cdb, apv)
    assert _line(pkg, items["mac"].id)["cost_status"] == "UNPRICED" and pkg.package_json["direct_cost_summary"]["MACHINE_CAPEX"] == []  # không chọn "rẻ nhất/mới nhất"
    q1 = [e for e in rc.list_evidence(cdb) if e.evidence_code == "Q1"][0]
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": q1.id})
    assert _line(dp.get_package(cdb, pkg.id), items["mac"].id)["amount"] == "2000.000000"


def test_quote_expiry_and_effective_window_do_not_price(cdb):
    _s, _v, _run, apv, items = _base(cdb, date="2026-08-20")
    pkg = _pkg(cdb, apv)
    expired = _ev(cdb, _mev("Q-EXP", source_kind="SUPPLIER_QUOTATION", vendor="ACME", quote_valid_until="2026-08-10"))
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": expired.id})  # bind được nhưng không price
    ln = _line(dp.get_package(cdb, pkg.id), items["mac"].id)
    assert ln["cost_status"] == "UNPRICED" and ln["cost_status_reason"] == "QUOTE_EXPIRED" and "QUOTE_EXPIRED" in ln["warnings"] and expired.status == "APPROVED"  # không tự retire
    ok = _ev(cdb, _mev("Q-OK", source_kind="SUPPLIER_QUOTATION", vendor="ACME", quote_valid_until="2026-08-20"))  # biên: planned_effective_date == quote_valid_until
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": ok.id})
    assert _line(dp.get_package(cdb, pkg.id), items["mac"].id)["cost_status"] == "PRICED"
    late = _ev(cdb, _lev("L-LATE", effective_from="2026-09-01"))
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["lab"].id, "evidence_id": late.id})
    ln = _line(dp.get_package(cdb, pkg.id), items["lab"].id)
    assert ln["cost_status_reason"] == "PRICE_OUTSIDE_EFFECTIVE_DATE" and ln["amount"] is None
    ended = _ev(cdb, _lev("L-END", effective_to="2026-08-19"))
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["lab"].id, "evidence_id": ended.id})
    assert _line(dp.get_package(cdb, pkg.id), items["lab"].id)["cost_status_reason"] == "PRICE_OUTSIDE_EFFECTIVE_DATE"


def test_labor_period_mismatch_no_conversion(cdb):
    _s, _v, _run, apv, items = _base(cdb)  # action period_type = MONTH
    pkg = _pkg(cdb, apv)
    yearly = _ev(cdb, _lev("L-YEAR", cost_period="YEAR", amount="9600"))
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["lab"].id, "evidence_id": yearly.id})
    ln = _line(dp.get_package(cdb, pkg.id), items["lab"].id)
    assert ln["cost_status"] == "UNPRICED" and ln["cost_status_reason"] == "COST_PERIOD_MISMATCH" and ln["amount"] is None
    assert "COST_PERIOD_MISMATCH" in dp.get_package(cdb, pkg.id).package_json["warning_codes"] and dp.get_package(cdb, pkg.id).package_json["direct_cost_summary"]["LABOR_RECURRING_COST"] == []


def test_model_and_candidate_identity_binding(cdb):
    cdb.add(MachineModel(machine_type_code="1K", brand="B1", model="X1"))
    cdb.add(MachineModel(machine_type_code="1K", brand="B2", model="X2"))
    cdb.add(MachineModel(machine_type_code="2K", brand="B3", model="Y1"))
    cdb.add(FutureTechnologyCandidate(candidate_code="FT-1", machine_type_code="1K", machine_model_id=1, brand="B1", model_name="X1", technology_name="Auto"))
    cdb.commit()
    cdb.add(FutureTechnologyEvidence(candidate_id=1, source_ref="SPEC-1", source_kind="MANUFACTURER_SPEC", basis="CLAIMED", metric_code="OUTPUT", value=10, unit="pcs/day"))
    cdb.commit()
    _s, _v, _run, apv, items = _base(cdb)
    pkg = _pkg(cdb, apv)
    specific = _ev(cdb, _mev("M-X1", machine_model_id=1))
    with pytest.raises(HTTPException) as x:
        dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": specific.id, "machine_model_id": 2})  # model khác
    assert x.value.status_code == 422
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": specific.id})  # tự điền đúng model của evidence
    b = cdb.query(RoadmapPackageBinding).one()
    assert b.machine_model_id == 1
    generic = _ev(cdb, _mev("M-GEN"))  # evidence chỉ machine_type: user có thể chọn model tùy ý cùng type
    with pytest.raises(HTTPException):
        dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": generic.id, "machine_model_id": 3})  # model thuộc machine_type khác
    with pytest.raises(HTTPException):
        dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": generic.id, "machine_model_id": 2, "future_candidate_id": 1})  # candidate gắn model 1 ≠ 2
    cand_ev = _ev(cdb, _mev("M-CAND", future_candidate_id=1))
    with pytest.raises(HTTPException):
        dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": cand_ev.id, "future_candidate_id": 2})
    with pytest.raises(HTTPException):
        rc.create_evidence(cdb, ADMIN, _mev("M-BAD", machine_type_code="1K", machine_model_id=3))  # evidence: model khác type
    rc.create_asset(cdb, ADMIN, {"subject_type": "MACHINE_TYPE", "subject_ref": "1K", "asset_kind": "IMAGE", "uri": "https://x.example.com/1k.png"})
    rc.create_asset(cdb, ADMIN, {"subject_type": "MACHINE_MODEL", "subject_ref": "1", "asset_kind": "MODEL_3D", "asset_ref": "assets/x1.glb"})
    rc.create_asset(cdb, ADMIN, {"subject_type": "FUTURE_CANDIDATE", "subject_ref": "1", "asset_kind": "DATASHEET", "uri": "https://x.example.com/ds.pdf"})
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": generic.id, "machine_model_id": 1, "future_candidate_id": 1})  # thay binding
    det = dp.get_package(cdb, pkg.id).package_json["machine_details"][0]
    assert det["machine_type_code"] == "1K" and det["bound_model_id"] == 1 and det["bound_candidate_id"] == 1
    assert det["details"]["machine_type"]["reference_placeholders"]["note"] and det["details"]["machine_model"]["brand"] == "B1"
    assert det["details"]["future_candidate"]["evidence"][0]["source_ref"] == "SPEC-1" and {a["asset_kind"] for a in det["details"]["asset_refs"]} == {"IMAGE", "MODEL_3D", "DATASHEET"}


def test_machine_detail_valid_at_type_level_without_model_or_assets(cdb):
    _s, _v, _run, apv, items = _base(cdb)
    det = _pkg(cdb, apv).package_json["machine_details"][0]
    assert det["bound_model_id"] is None and det["details"]["machine_type"]["code"] == "1K" and det["details"]["asset_refs"] == [] and det["details"]["machine_model"] is None


# =================================================================== freeze / retire / verify
def test_evidence_retired_before_freeze_cannot_freeze_as_priced(cdb):
    _s, _v, _run, apv, items = _base(cdb)
    e = _ev(cdb, _mev())
    pkg = _pkg(cdb, apv)
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": e.id})
    assert _line(dp.get_package(cdb, pkg.id), items["mac"].id)["cost_status"] == "PRICED"
    rc.retire_evidence(cdb, ADMIN2, e.id, "sai giá")
    assert _line(dp.get_package(cdb, pkg.id), items["mac"].id)["cost_status"] == "PRICED"  # preview chưa refresh
    pkg = _freeze(cdb, pkg)
    ln = _line(pkg, items["mac"].id)
    assert ln["cost_status"] == "UNPRICED" and ln["cost_status_reason"] == "PRICE_NOT_APPROVED" and pkg.package_json["direct_cost_summary"]["MACHINE_CAPEX"] == []
    assert dp.approve(cdb, ADMIN2, pkg.id).status == "APPROVED"  # unpriced không chặn approve


def test_frozen_package_unchanged_after_evidence_retire_only_live_warning(cdb):
    _s, _v, _run, apv, items = _base(cdb)
    e = _ev(cdb, _mev())
    pkg = _pkg(cdb, apv)
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": e.id})
    pkg = _freeze(cdb, pkg)
    before, fp = json.dumps(pkg.package_json, sort_keys=True), pkg.package_fingerprint
    assert _line(pkg, items["mac"].id)["amount"] == "3001.000000"
    rc.retire_evidence(cdb, ADMIN2, e.id, "thay bằng báo giá mới")  # retire SAU freeze
    rc.new_version(cdb, ADMIN, e.id)
    pkg = dp.get_package(cdb, pkg.id)
    assert json.dumps(pkg.package_json, sort_keys=True) == before and pkg.package_fingerprint == fp  # số học + fingerprint không đổi
    view = dp.package_view(cdb, pkg)
    assert [w["code"] for w in view["live_warnings"]] == ["SOURCE_EVIDENCE_RETIRED_AFTER_SNAPSHOT"] and "SOURCE_EVIDENCE_RETIRED_AFTER_SNAPSHOT" not in pkg.package_json["warning_codes"]
    assert dp.approve(cdb, ADMIN2, pkg.id).status == "APPROVED"  # không auto-invalidate
    assert dp.verify(cdb, dp.get_package(cdb, pkg.id)) == []
    assert _line(dp.get_package(cdb, pkg.id), items["mac"].id)["amount"] == "3001.000000"


def test_package_governance_four_eyes_frozen_and_archive(cdb):
    _s, _v, _run, apv, items = _base(cdb)
    e = _ev(cdb, _mev())
    pkg = _pkg(cdb, apv)
    with pytest.raises(HTTPException):
        dp.approve(cdb, ADMIN2, pkg.id)  # DRAFT
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": e.id})
    pkg = _freeze(cdb, pkg)
    assert pkg.status == "UNDER_REVIEW" and pkg.reviewed_by == "admin" and pkg.package_fingerprint and dp.verify(cdb, pkg) == []
    with pytest.raises(HTTPException) as x:
        dp.approve(cdb, ADMIN, pkg.id)
    assert x.value.status_code == 409 and "Four-eyes" in x.value.detail
    with pytest.raises(HTTPException):
        dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": e.id})  # bindings immutable sau freeze
    with pytest.raises(HTTPException):
        dp.unbind(cdb, ADMIN, pkg.id, items["mac"].id)
    with pytest.raises(HTTPException):
        dp.create_package(cdb, ADMIN, apv.id, {})  # đã có package mở
    dp.approve(cdb, ADMIN2, pkg.id)  # còn UNPRICED (labor) + unresolved + warnings vẫn được duyệt
    with pytest.raises(HTTPException):
        dp.archive(cdb, ADMIN2, pkg.id, " ")
    assert dp.archive(cdb, ADMIN2, pkg.id, "thay thế").status == "ARCHIVED"
    with pytest.raises(HTTPException):
        dp.archive(cdb, ADMIN2, pkg.id, "again")
    assert [h["to_status"] for h in dp.history(cdb, pkg.id)] == ["DRAFT", "UNDER_REVIEW", "APPROVED", "ARCHIVED"]


def test_tampered_frozen_package_fails_verify_and_approve(cdb):
    _s, _v, _run, apv, items = _base(cdb)
    e = _ev(cdb, _mev())
    pkg = _pkg(cdb, apv)
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": e.id})
    pkg = _freeze(cdb, pkg)
    pj = json.loads(json.dumps(pkg.package_json))
    pj["direct_cost_summary"]["MACHINE_CAPEX"][0]["amount"] = "1.000000"
    pkg.package_json = pj
    cdb.commit()
    with pytest.raises(HTTPException) as x:
        dp.approve(cdb, ADMIN2, pkg.id)
    assert x.value.status_code == 409 and "verify" in x.value.detail
    b = cdb.query(RoadmapPackageBinding).one()  # sửa snapshot giá cũng bị phát hiện
    pkg.package_json = json.loads(json.dumps(_fresh(cdb, pkg)))
    cdb.commit()
    b.snapshot_json = {**b.snapshot_json, "evidence": {**b.snapshot_json["evidence"], "amount": "1.000000"}}
    cdb.commit()
    assert dp.verify(cdb, pkg)


def _fresh(db, pkg):
    return dp.build_package(db, pkg, frozen=True)


def test_source_action_plan_must_stay_approved_and_scenario_guard(cdb):
    s, _v, _run, apv, items = _base(cdb)
    pkg = _pkg(cdb, apv)
    e = _ev(cdb, _mev())
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": e.id})
    pkg = _freeze(cdb, pkg)
    rm.transition_scenario(cdb, ADMIN, s.id, "ARCHIVED", "kết thúc")
    with pytest.raises(HTTPException) as x:
        dp.approve(cdb, ADMIN2, pkg.id)  # Scenario ARCHIVED
    assert x.value.status_code == 409 and dp.get_package(cdb, pkg.id).status == "UNDER_REVIEW"
    with pytest.raises(HTTPException):
        dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": e.id})
    with pytest.raises(HTTPException):
        dp.create_package(cdb, ADMIN, apv.id, {})


def test_scenario_archived_blocks_create_bind_submit_but_not_archive(cdb):
    s, _v, _run, apv, items = _base(cdb)
    e = _ev(cdb, _mev())
    draft = _pkg(cdb, apv)
    rm.transition_scenario(cdb, ADMIN, s.id, "ARCHIVED", "kết thúc")
    with pytest.raises(HTTPException):
        dp.bind(cdb, ADMIN, draft.id, {"action_item_id": items["mac"].id, "evidence_id": e.id})
    with pytest.raises(HTTPException):
        dp.submit_review(cdb, ADMIN, draft.id)


def test_archive_approved_package_allowed_when_scenario_archived(cdb):
    s, _v, _run, apv, items = _base(cdb)
    pkg = _pkg(cdb, apv)
    _freeze(cdb, pkg)
    dp.approve(cdb, ADMIN2, pkg.id)
    rm.transition_scenario(cdb, ADMIN, s.id, "ARCHIVED", "kết thúc")
    assert dp.archive(cdb, ADMIN2, pkg.id, "dọn dẹp").status == "ARCHIVED"


def test_package_reproducible_from_same_snapshot(cdb):
    _s, _v, _run, apv, items = _base(cdb)
    e = _ev(cdb, _mev())
    pkg = _pkg(cdb, apv)
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": e.id})
    pkg = _freeze(cdb, pkg)
    again = dp.build_package(cdb, pkg, frozen=True)  # build lại từ binding snapshot (không evidence sống)
    rc.retire_evidence(cdb, ADMIN2, e.id, "x")
    assert dp.build_package(cdb, pkg, frozen=True) == again == pkg.package_json
    assert dp._hash(again) == pkg.package_fingerprint


def test_compare_packages_no_ranking(cdb):
    _s, v, run, apv, items = _base(cdb)
    e1, e2 = _ev(cdb, _mev("Q1", amount="1000")), _ev(cdb, _mev("Q2", amount="900", currency="VND"))
    p1 = _pkg(cdb, apv)
    dp.bind(cdb, ADMIN, p1.id, {"action_item_id": items["mac"].id, "evidence_id": e1.id})
    _freeze(cdb, p1)
    dp.approve(cdb, ADMIN2, p1.id)
    dp.archive(cdb, ADMIN2, p1.id, "phương án khác")
    p2 = _pkg(cdb, apv)
    assert p2.package_no == 2
    dp.bind(cdb, ADMIN, p2.id, {"action_item_id": items["mac"].id, "evidence_id": e2.id})
    _freeze(cdb, p2)
    c = dp.compare(cdb, p1.id, p2.id)
    assert c["machine_capex"]["a"][0]["currency"] == "USD" and c["machine_capex"]["b"][0]["currency"] == "VND" and c["same_source_run"] is True
    assert c["evidence_versions"] == {"a": ["Q1@v1"], "b": ["Q2@v1"]} and any(a["changed"] for a in c["actions"])
    assert c["lineage"]["a"]["package_fingerprint"] != c["lineage"]["b"]["package_fingerprint"] and c["completeness"]["a"]["pricing"] == "PARTIAL_PRICING"
    _no_forbidden(c)
    # khác scenario_version => chặn
    from tests.test_roadmap import _ms, _ready, _run, _scenario, _tgt

    s2, v2 = _scenario(cdb, name="Other")
    m = _ms(cdb, v2, "MX", "2026-08-31")
    _tgt(cdb, m, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="PACK_QTY", target_value=2000)
    _ready(cdb, v2)
    r2 = _run(cdb, v2)["run"]
    pv = _plan(cdb, r2, "F")
    ap.add_item(cdb, ADMIN, pv.id, {"proposal_id": _pick(r2, "CAPACITY_CHANGE", "MX")["id"], "planned_effective_date": "2026-09-30"})
    fapv = _submit_approve(cdb, pv)
    foreign = _pkg(cdb, fapv)
    with pytest.raises(HTTPException) as x:
        dp.compare(cdb, p1.id, foreign.id)
    assert x.value.status_code == 409


# =================================================================== API
def test_api_permissions_and_http_routes(cdb):
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.db.session import get_db
    from app.main import app

    _s, _v, _run, apv, items = _base(cdb)
    ev = rm_api.create_cost_evidence(rm_api.CostEvidenceBody(**_mev()), cdb, PLANNER)  # planner có manage
    rm_api.submit_cost_evidence_review(ev["id"], cdb, PLANNER)
    for fn, args in ((rm_api.approve_cost_evidence, (ev["id"], cdb, PLANNER)), (rm_api.retire_cost_evidence, (ev["id"], rm_api.RetireBody(reason="x"), cdb, PLANNER))):
        with pytest.raises(HTTPException) as x:
            fn(*args)
        assert x.value.status_code == 403
    assert rm_api.approve_cost_evidence(ev["id"], cdb, ADMIN2)["status"] == "APPROVED"
    pk = rm_api.create_decision_package(apv.id, rm_api.PackageBody(note="api"), cdb, PLANNER)
    rm_api.bind_package_evidence(pk["id"], rm_api.BindingBody(action_item_id=items["mac"].id, evidence_id=ev["id"]), cdb, PLANNER)
    rm_api.submit_decision_package_review(pk["id"], cdb, PLANNER)
    for fn, args in ((rm_api.approve_decision_package, (pk["id"], cdb, PLANNER)), (rm_api.archive_decision_package, (pk["id"], rm_api.RetireBody(reason="x"), cdb, PLANNER))):
        with pytest.raises(HTTPException) as x:
            fn(*args)
        assert x.value.status_code == 403
    assert rm_api.approve_decision_package(pk["id"], cdb, ADMIN2)["status"] == "APPROVED"
    admin = SimpleNamespace(username="admin", role="ADMIN", id=1, is_active=True, must_change_password=False)
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_db] = lambda: cdb
    try:
        c = TestClient(app)
        B = "/api/roadmap"
        assert len(c.get(f"{B}/cost-evidence").json()) == 1 and c.get(f"{B}/cost-evidence/{ev['id']}/history").json()[-1]["to_status"] == "APPROVED"
        assert c.post(f"{B}/cost-evidence", json={**_mev("BAD"), "amount": "0"}).status_code == 422
        assert c.post(f"{B}/asset-refs", json={"subject_type": "MACHINE_TYPE", "subject_ref": "1K", "asset_kind": "IMAGE", "uri": "javascript:alert(1)"}).status_code == 422
        a = c.post(f"{B}/asset-refs", json={"subject_type": "MACHINE_TYPE", "subject_ref": "1K", "asset_kind": "IMAGE", "uri": "https://x.example.com/a.png"})
        assert a.status_code == 200 and c.post(f"{B}/asset-refs/{a.json()['id']}/active", json={"active": False}).json()["active"] is False
        second = c.post(f"{B}/action-plan-versions/{apv.id}/decision-packages", json={})
        assert second.status_code == 200 and second.json()["package_no"] == 2  # package APPROVED không chặn package mới; package mở thì chặn
        assert c.post(f"{B}/action-plan-versions/{apv.id}/decision-packages", json={}).status_code == 409
    finally:
        app.dependency_overrides.clear()
    opts = rm_api.options(ADMIN)
    assert opts["cost_families"] == ["MACHINE_UNIT_PRICE", "LABOR_COST_PER_WORKER_PERIOD"] and "EX_WORKS_MACHINE_ONLY" in opts["machine_price_bases"] and "HR_APPROVED_COST_STANDARD" in opts["cost_approvable_source_kinds"]["LABOR_COST_PER_WORKER_PERIOD"]
