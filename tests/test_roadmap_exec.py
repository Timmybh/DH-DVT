"""Task 6 (Issue #13) — Executable Calculation Rules & Capacity Impact. Rule fixture chỉ tồn tại trong test — hệ thống thật KHÔNG seed rule nào,
productivity KHÔNG suy từ bảng nguồn (capacity_definitions / productivity_grades / machine placeholder)."""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import roadmap as rm_api
from app.models.resources import MachineCapacity
from app.models.roadmap import RoadmapExecutableRule, RoadmapRun
from app.services import roadmap as rm
from app.services import roadmap_adapters as ad
from app.services import roadmap_baseline as rb
from app.services import roadmap_engine as eng
from app.services import roadmap_exec_rules as xr
from tests.test_roadmap import ADMIN, PLANNER, _labor, _machines, _ms, _output_run, _ready, _run, _scenario, _seed_pack, _seed_revenue, _sync, _tgt, _by_type, db  # noqa: F401

ADMIN2 = SimpleNamespace(username="admin2", role="ADMIN", id=3)
LAB, MAC = "LABOR_GAP_REQUIREMENT_V1", "MACHINE_GAP_REQUIREMENT_V1"


@pytest.fixture()
def xdb(db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(xr, "write_audit", lambda *a, **kw: None)
    return db


def _body(adapter=LAB, prod=120.0, period="MONTH", **kw):
    res = "worker" if adapter == LAB else "machine"
    d = {"rule_code": kw.pop("rule_code", "LAB-A" if adapter == LAB else "MAC-A"), "adapter_code": adapter, "scope_type": "TOTAL", "period_type": period,
         "productivity_value": prod, "productivity_unit": f"sp/{res}/{period}", "owner": "IE", "source_kind": "IE_APPROVED_STUDY", "source_ref": "IE-2026-01",
         "effective_from": "2026-01-01", "assumptions": "1 ca, hiệu suất chuẩn"}
    if adapter == MAC:
        d["machine_type_code"] = "1K"
    d.update(kw)
    inp = {"gap_output": 500, "gap_unit": "sp", "period_type": d["period_type"], ("productivity_per_worker" if adapter == LAB else "productivity_per_machine"): d["productivity_value"],
           "productivity_unit": d["productivity_unit"], ("available_labor" if adapter == LAB else "available_machines"): 10}
    if adapter == MAC:
        inp["machine_type_code"] = d.get("machine_type_code")
    if "sample_input" not in d:
        d["sample_input"] = inp
    if "sample_expected" not in d:
        try:
            out = ad.run_adapter(adapter, d["sample_input"])
            d["sample_expected"] = {k: out[k] for k in ad.get_adapter(adapter).result_keys}
        except ad.AdapterInputError:
            d["sample_expected"] = {}
    return d


def _xrule(db, adapter=LAB, approve=True, **kw):
    r = xr.create_rule(db, ADMIN, _body(adapter, **kw))
    if approve:
        xr.submit_review(db, ADMIN, r.id)
        r = xr.approve_rule(db, ADMIN2, r.id)
    return r


# =================================================================== adapter formula (contract GPT)
def test_allowlist_is_exactly_the_two_gap_adapters():
    assert ad.ALLOWLISTED_ADAPTERS == ("LABOR_GAP_REQUIREMENT_V1", "MACHINE_GAP_REQUIREMENT_V1")
    for old in ("LABOR_REQUIREMENT_V1", "MACHINE_REQUIREMENT_V1", "GAP_PER_UNIT_RATE"):
        with pytest.raises(ad.AdapterInputError) as e:
            ad.run_adapter(old, {})
        assert e.value.code == "ADAPTER_NOT_ALLOWLISTED"


def test_labor_formula_ceil_incremental_gap_and_signed_remaining():
    o = ad.run_adapter(LAB, {"gap_output": 500, "gap_unit": "sp", "period_type": "MONTH", "productivity_per_worker": 120, "productivity_unit": "sp/worker/MONTH", "available_labor": 3})
    assert o["requirement_basis"] == "INCREMENTAL_GAP" and o["rounding_rule"] == "CEIL"
    assert o["required_incremental_labor"] == o["additional_labor"] == 5 and isinstance(o["additional_labor"], int)
    assert o["proposed_increment"] == 600 and o["remaining_gap_after_proposal"] == -100  # giữ dấu: âm = vượt gap do làm tròn
    assert o["available_labor"] == 3  # context — không trừ vào công thức
    o2 = ad.run_adapter(LAB, {"gap_output": 500, "gap_unit": "sp", "period_type": "MONTH", "productivity_per_worker": 120, "productivity_unit": "sp/worker/MONTH", "available_labor": 9999})
    assert o2["additional_labor"] == 5  # available lớn/nhỏ không đổi kết quả


def test_machine_formula_and_exact_division_and_float_safe_ceil():
    m = ad.run_adapter(MAC, {"gap_output": 600, "gap_unit": "sp", "period_type": "YEAR", "machine_type_code": "1K", "productivity_per_machine": 300, "productivity_unit": "sp/machine/YEAR", "available_machines": 0})
    assert m["additional_machines"] == 2 and m["remaining_gap_after_proposal"] == 0 and m["machine_type_code"] == "1K"
    # sai số float: 3.3/1.1 = 3.0000000000000004 trong float -> CEIL vẫn phải là 3, không 4
    f = ad.run_adapter(LAB, {"gap_output": 3.3, "gap_unit": "sp", "period_type": "MONTH", "productivity_per_worker": 1.1, "productivity_unit": "sp/worker/MONTH", "available_labor": 1})
    assert f["additional_labor"] == 3
    tiny = ad.run_adapter(LAB, {"gap_output": 0.5, "gap_unit": "sp", "period_type": "MONTH", "productivity_per_worker": 120, "productivity_unit": "sp/worker/MONTH", "available_labor": 1})
    assert tiny["additional_labor"] == 1  # CEIL, không banker rounding, không 0


@pytest.mark.parametrize("patch,code", [
    ({"gap_output": 0}, "INVALID_INPUT"), ({"gap_output": -5}, "INVALID_INPUT"), ({"gap_output": float("nan")}, "INVALID_INPUT"), ({"gap_output": True}, "INVALID_INPUT"),
    ({"gap_unit": "USD"}, "UNIT_MISMATCH"), ({"period_type": "DAY"}, "PERIOD_MISMATCH"), ({"productivity_unit": "sp/worker/YEAR"}, "PERIOD_MISMATCH"),
    ({"productivity_unit": "sp/machine/MONTH"}, "PERIOD_MISMATCH"), ({"productivity_per_worker": 0}, "INVALID_INPUT"), ({"productivity_per_worker": -1}, "INVALID_INPUT"),
    ({"available_labor": -1}, "INVALID_INPUT"), ({"available_labor": 1.5}, "INVALID_INPUT"), ({"available_labor": None}, "INVALID_INPUT"),
])
def test_labor_adapter_rejects_bad_dimensions(patch, code):
    inp = {"gap_output": 500, "gap_unit": "sp", "period_type": "MONTH", "productivity_per_worker": 120, "productivity_unit": "sp/worker/MONTH", "available_labor": 3, **patch}
    with pytest.raises(ad.AdapterInputError) as e:
        ad.run_adapter(LAB, inp)
    assert e.value.code == code


def test_machine_adapter_requires_explicit_machine_type():
    inp = {"gap_output": 500, "gap_unit": "sp", "period_type": "MONTH", "productivity_per_machine": 300, "productivity_unit": "sp/machine/MONTH", "available_machines": 1}
    with pytest.raises(ad.AdapterInputError):
        ad.run_adapter(MAC, inp)
    with pytest.raises(ad.AdapterInputError):
        ad.run_adapter(MAC, {**inp, "machine_type_code": "  "})


# =================================================================== rule structure & governance
def test_no_executable_rule_seeded(xdb):
    assert xr.list_rules(xdb) == [] and xdb.query(RoadmapExecutableRule).count() == 0


def test_create_rejects_non_allowlisted_adapter_and_bad_dimensions(xdb):
    for bad in ({"adapter_code": "LABOR_REQUIREMENT_V1"}, {"adapter_code": "ANYTHING"}, {"productivity_value": 0}, {"productivity_value": -3}, {"productivity_value": None},
                {"productivity_unit": "sp/worker/YEAR"}, {"productivity_unit": "sp/day"}, {"period_type": "DAY"}, {"machine_type_code": "1K"}, {"scope_type": "FACTORY", "scope_value": "ZZ"},
                {"scope_type": "LINE"}, {"effective_from": "2026-05-01", "effective_to": "2026-04-01"}, {"effective_to": "2026-04-01", "effective_from": None}):
        with pytest.raises(HTTPException) as e:
            xr.create_rule(xdb, ADMIN, _body(rule_code="BAD", **bad))
        assert e.value.status_code in (409, 422), bad
    for bad in ({"machine_type_code": None}, {"machine_type_code": "NOPE"}, {"productivity_unit": "sp/machine/YEAR"}):
        with pytest.raises(HTTPException):
            xr.create_rule(xdb, ADMIN, _body(MAC, rule_code="BADM", **bad))
    assert xdb.query(RoadmapExecutableRule).count() == 0


def test_lifecycle_four_eyes_and_immutability(xdb):
    r = xr.create_rule(xdb, ADMIN, _body())
    assert r.status == "DRAFT" and r.adapter_version == "1" and r.proposal_type == "LABOR_RECRUITMENT"
    with pytest.raises(HTTPException) as e:  # DRAFT không thể APPROVE trực tiếp
        xr.approve_rule(xdb, ADMIN2, r.id)
    assert e.value.status_code == 409
    xr.submit_review(xdb, ADMIN, r.id)
    r = xr.get_rule(xdb, r.id)
    assert r.status == "UNDER_REVIEW" and r.reviewed_by == "admin"
    with pytest.raises(HTTPException) as e:  # reviewer == approver
        xr.approve_rule(xdb, ADMIN, r.id)
    assert e.value.status_code == 409 and "Four-eyes" in e.value.detail and xr.get_rule(xdb, r.id).status == "UNDER_REVIEW"
    with pytest.raises(HTTPException):
        xr.update_rule(xdb, ADMIN, r.id, {"productivity_value": 999})  # UNDER_REVIEW không sửa
    xr.approve_rule(xdb, ADMIN2, r.id)
    r = xr.get_rule(xdb, r.id)
    assert r.status == "APPROVED" and r.approved_by == "admin2" and r.reviewed_by != r.approved_by
    with pytest.raises(HTTPException):
        xr.update_rule(xdb, ADMIN, r.id, {"productivity_value": 999})  # APPROVED bất biến
    with pytest.raises(HTTPException):
        xr.submit_review(xdb, ADMIN, r.id)
    assert [h["to_status"] for h in rm.list_history(xdb, "EXEC_RULE", r.id)] == ["DRAFT", "UNDER_REVIEW", "APPROVED"]
    with pytest.raises(HTTPException) as e:
        xr.retire_rule(xdb, ADMIN2, r.id, " ")
    assert e.value.status_code == 422
    xr.retire_rule(xdb, ADMIN2, r.id, "hết hiệu lực")
    assert xr.get_rule(xdb, r.id).status == "RETIRED" and rm.list_history(xdb, "EXEC_RULE", r.id)[-1]["reason"] == "hết hiệu lực"


@pytest.mark.parametrize("kind", ["ESTIMATE", "DEFAULT", "CLAIMED", "BROCHURE", "PLACEHOLDER", "UNVERIFIED", "WHATEVER", ""])
def test_blocked_or_unknown_source_kind_cannot_be_approved_but_can_be_drafted(xdb, kind):
    if kind == "":
        with pytest.raises(HTTPException):  # thiếu source_kind => không đủ điều kiện review
            r = xr.create_rule(xdb, ADMIN, _body(source_kind=kind))
            xr.submit_review(xdb, ADMIN, r.id)
        return
    r = xr.create_rule(xdb, ADMIN, _body(source_kind=kind))  # lưu DRAFT được (nghiên cứu)
    xr.submit_review(xdb, ADMIN, r.id)  # UNDER_REVIEW được
    with pytest.raises(HTTPException) as e:
        xr.approve_rule(xdb, ADMIN2, r.id)
    assert e.value.status_code == 409 and xr.get_rule(xdb, r.id).status == "UNDER_REVIEW"


@pytest.mark.parametrize("kind", list(("IE_APPROVED_STUDY", "TIME_MOTION_STUDY", "APPROVED_CAPACITY_STUDY", "CONTROLLED_PRODUCTION_TRIAL")))
def test_allowed_source_kinds_approve(xdb, kind):
    assert _xrule(xdb, source_kind=kind).status == "APPROVED"


@pytest.mark.parametrize("missing", ["owner", "source_ref", "effective_from", "assumptions"])
def test_incomplete_rule_cannot_enter_review_or_approval(xdb, missing):
    r = xr.create_rule(xdb, ADMIN, _body(**{missing: None if missing == "effective_from" else ""}))
    with pytest.raises(HTTPException) as e:
        xr.submit_review(xdb, ADMIN, r.id)
    assert missing in e.value.detail


def test_sample_calculation_is_re_run_and_must_match(xdb):
    good = _body()
    bad_expected = {**good["sample_expected"], "additional_labor": 4}
    r = xr.create_rule(xdb, ADMIN, {**good, "sample_expected": bad_expected})
    assert xr.verify_sample(r)["ok"] is False
    with pytest.raises(HTTPException) as e:
        xr.submit_review(xdb, ADMIN, r.id)
    assert "additional_labor" in e.value.detail
    xr.update_rule(xdb, ADMIN, r.id, {"sample_expected": good["sample_expected"]})
    assert xr.verify_sample(xr.get_rule(xdb, r.id))["ok"] is True
    # sample không chứng minh đúng rule (productivity lệch) => chặn
    other = xr.create_rule(xdb, ADMIN, _body(rule_code="LAB-B", sample_input={**good["sample_input"], "productivity_per_worker": 100}))
    assert xr.verify_sample(other)["ok"] is False
    # thiếu sample
    none = xr.create_rule(xdb, ADMIN, _body(rule_code="LAB-C", sample_input={}, sample_expected={}))
    assert xr.verify_sample(none)["ok"] is False


def test_new_version_and_overlap_guard(xdb):
    v1 = _xrule(xdb, effective_to="2026-12-31")
    v2 = xr.new_version(xdb, ADMIN, v1.id)
    assert v2.rule_version == 2 and v2.status == "DRAFT" and v2.reviewed_by == "" and v2.approved_by == ""
    with pytest.raises(HTTPException):  # đã có DRAFT
        xr.new_version(xdb, ADMIN, v1.id)
    xr.update_rule(xdb, ADMIN, v2.id, {"effective_from": "2026-06-01", "effective_to": None})  # chồng hiệu lực v1
    xr.submit_review(xdb, ADMIN, v2.id)
    with pytest.raises(HTTPException) as e:
        xr.approve_rule(xdb, ADMIN2, v2.id)
    assert e.value.status_code == 409 and "chồng" in e.value.detail
    xr.retire_rule(xdb, ADMIN2, v1.id, "thay bằng v2")
    assert xr.approve_rule(xdb, ADMIN2, v2.id).status == "APPROVED"


# =================================================================== engine: proposals
def _gap500(db, **tkw):
    """Aug pack 1500, target 2000 => gap 500 sp (MONTH, milestone 2026-08-31)."""
    return _output_run(db, target_value=2000, **tkw)


def test_without_executable_rules_production_behaviour_needs_input(xdb):
    _labor(xdb)
    _machines(xdb)
    xdb.query(MachineCapacity).update({"efficiency": 0.85, "nominal_output_per_day": 1000})  # placeholder giống production: KHÔNG được dùng
    xdb.commit()
    _s, _v, r = _gap500(xdb)
    for pt in ("LABOR_RECRUITMENT", "MACHINE_PURCHASE"):
        (p,) = _by_type(r, pt)
        assert p["calc_status"] == "NEEDS_INPUT" and p["quantity"] is None and p["capacity_impact"] is None
    assert r["run"]["engine_version"] == "RM_ENGINE_V2"


def test_labor_rule_calculates_incremental_gap_with_capacity_impact(xdb):
    _labor(xdb, "XN1", 50)
    _xrule(xdb)
    _s, _v, r = _gap500(xdb)
    (p,) = _by_type(r, "LABOR_RECRUITMENT")
    assert p["calc_status"] == "CALCULATED" and p["quantity"] == 5 and p["unit"] == "worker" and p["completeness"] == "COMPLETE"
    assert p["calculation_rule_version"] == "LAB-A@v1" and p["calculation"]["requirement_basis"] == "INCREMENTAL_GAP"
    ci = p["capacity_impact"]
    assert ci["baseline_capacity"] is None and ci["resulting_capacity"] is None and ci["proposed_increment"] == 600 and ci["remaining_gap"] == -100
    assert ci["capacity_unit"] == "sp" and ci["period_type"] == "MONTH" and ci["completeness"] == "PARTIAL"
    assert not {"utilization", "bottleneck"} & set(ci)
    assert p["input_snapshot"]["available_baseline"]["total_labor"] == 50  # context được snapshot, không tham gia công thức
    assert p["input_snapshot"]["executable_rule"]["productivity_value"] == 120.0 and p["evidence_refs"][0]["source_ref"] == "IE-2026-01"


def test_available_labor_is_context_only_quantity_unchanged(xdb):
    _xrule(xdb)
    _labor(xdb, "XN1", 1)
    _s, _v, r1 = _gap500(xdb)
    q1 = _by_type(r1, "LABOR_RECRUITMENT")[0]["quantity"]
    from app.models.resources import LaborStandard

    xdb.query(LaborStandard).update({"total_labor": 100000})
    xdb.commit()
    r2 = _run(xdb, _v)
    assert _by_type(r2, "LABOR_RECRUITMENT")[0]["quantity"] == q1 == 5
    assert r2["created"] is True  # baseline đổi => fingerprint đổi => run mới, nhưng kết quả gap-based giữ nguyên


def test_missing_labor_baseline_is_needs_input_no_fallback(xdb):
    _xrule(xdb)  # không có labor_standards
    from app.models.resources import LaborStandard  # noqa: F401

    _s, _v, r = _gap500(xdb)
    (p,) = _by_type(r, "LABOR_RECRUITMENT")
    assert p["calc_status"] == "NEEDS_INPUT" and p["quantity"] is None and any("available labor" in m for m in p["missing_inputs"])


def test_machine_rule_uses_available_machines_formula(xdb):
    xdb.add(MachineCapacity(factory_code="XN1", line="1", machine_type="1K", quantity=10, maintenance_quantity=2, down_quantity=1, status="ACTIVE"))
    xdb.add(MachineCapacity(factory_code="XN2", line="1", machine_type="1K", quantity=3, maintenance_quantity=2, down_quantity=5, status="ACTIVE"))  # max(0, -4) = 0
    xdb.add(MachineCapacity(factory_code="XN1", line="2", machine_type="2K", quantity=99, status="ACTIVE"))  # loại máy khác: không tính
    xdb.add(MachineCapacity(factory_code="XN1", line="3", machine_type="1K", quantity=50, status="INACTIVE"))
    xdb.commit()
    assert rb.machine_available(xdb, "TOTAL", "", "1K")["available_machines"] == 7
    assert rb.machine_available(xdb, "FACTORY", "XN2", "1K")["available_machines"] == 0
    assert rb.machine_available(xdb, "TOTAL", "", "NOPE") is None
    _xrule(xdb, MAC, prod=300.0)
    _s, _v, r = _gap500(xdb)
    (p,) = _by_type(r, "MACHINE_PURCHASE")
    assert p["calc_status"] == "CALCULATED" and p["quantity"] == 2 and p["unit"] == "machine"
    assert p["calculation"]["available_machines"] == 7 and p["calculation"]["machine_type_code"] == "1K"
    assert p["capacity_impact"]["remaining_gap"] == -100 and p["capacity_impact"]["baseline_capacity"] is None


def test_machine_without_inventory_for_type_needs_input(xdb):
    _machines(xdb, "XN1", "2K", 5)  # có máy nhưng không phải 1K
    _xrule(xdb, MAC, prod=300.0)
    _s, _v, r = _gap500(xdb)
    (p,) = _by_type(r, "MACHINE_PURCHASE")
    assert p["calc_status"] == "NEEDS_INPUT" and p["quantity"] is None and any("available machines" in m for m in p["missing_inputs"])


def test_period_mismatch_no_conversion(xdb):
    _labor(xdb)
    _xrule(xdb, period="YEAR", prod=1440.0)  # rule YEAR, target MONTH
    _s, _v, r = _gap500(xdb)
    (p,) = _by_type(r, "LABOR_RECRUITMENT")
    assert p["calc_status"] == "NEEDS_INPUT" and p["quantity"] is None and any("PERIOD_MISMATCH" in m for m in p["missing_inputs"])
    assert p["input_snapshot"]["flags"] == ["PERIOD_MISMATCH"]


def test_effective_window_uses_milestone_date(xdb):
    _labor(xdb)
    _xrule(xdb, effective_from="2026-09-01")  # sau milestone 2026-08-31
    _s, _v, r = _gap500(xdb)
    (p,) = _by_type(r, "LABOR_RECRUITMENT")
    assert p["calc_status"] == "NEEDS_INPUT" and p["calculation_rule_version"] == "NONE"
    r2 = _xrule(xdb, rule_code="LAB-B", effective_from="2026-08-31", effective_to="2026-08-31")  # đúng ngày biên
    _s2, v2 = _scenario(xdb, name="B")
    m = _ms(xdb, v2)
    _tgt(xdb, m, metric_code="OUTPUT_QTY", unit="sp", baseline_basis="PACK_QTY", target_value=2000)
    _ready(xdb, v2)
    lines = _by_type(_run(xdb, v2), "LABOR_RECRUITMENT")
    assert [x["calculation_rule_version"] for x in lines] == ["LAB-B@v1"] and r2.status == "APPROVED"


def test_scope_must_match_exactly_no_rollup(xdb):
    _labor(xdb, "XN1", 50)
    _xrule(xdb, scope_type="FACTORY", scope_value="XN1")  # rule XN1 KHÔNG áp cho scenario TOTAL
    _s, _v, r = _gap500(xdb)
    (p,) = _by_type(r, "LABOR_RECRUITMENT")
    assert p["calc_status"] == "NEEDS_INPUT" and p["quantity"] is None


def test_multiple_effective_rules_one_line_each_no_rank(xdb):
    _labor(xdb)
    _xrule(xdb, rule_code="LAB-A", prod=120.0)
    _xrule(xdb, rule_code="LAB-B", prod=200.0)
    _s, _v, r = _gap500(xdb)
    lines = _by_type(r, "LABOR_RECRUITMENT")
    assert sorted((x["calculation_rule_version"], x["quantity"]) for x in lines) == [("LAB-A@v1", 5.0), ("LAB-B@v1", 3.0)]
    assert not any("rank" in k or "score" in k or "best" in k for x in lines for k in x)


def test_unapproved_rules_are_never_used(xdb):
    _labor(xdb)
    xr.create_rule(xdb, ADMIN, _body())  # DRAFT
    r2 = xr.create_rule(xdb, ADMIN, _body(rule_code="LAB-U"))
    xr.submit_review(xdb, ADMIN, r2.id)  # UNDER_REVIEW
    r3 = _xrule(xdb, rule_code="LAB-R")
    xr.retire_rule(xdb, ADMIN2, r3.id, "x")
    _s, _v, r = _gap500(xdb)
    (p,) = _by_type(r, "LABOR_RECRUITMENT")
    assert p["calc_status"] == "NEEDS_INPUT" and p["quantity"] is None


def test_gap_not_positive_is_not_applicable_and_revenue_never_uses_rules(xdb):
    _labor(xdb)
    _xrule(xdb)
    _s, _v, r = _output_run(xdb, target_value=1000)  # gap = -500
    assert {p["calc_status"] for p in r["run"]["proposals"] if p["proposal_type"] in ("LABOR_RECRUITMENT", "MACHINE_PURCHASE")} == {"NOT_APPLICABLE"}
    _seed_revenue(xdb)
    _sync(xdb)
    _s2, v2 = _scenario(xdb, name="Rev")
    m = _ms(xdb, v2)
    _tgt(xdb, m, target_value=1000)
    _ready(xdb, v2)
    rr = _run(xdb, v2)
    assert {p["calc_status"] for p in rr["run"]["proposals"] if p["proposal_type"] in ("LABOR_RECRUITMENT", "MACHINE_PURCHASE", "CAPACITY_CHANGE")} == {"NOT_APPLICABLE"}


def test_capacity_change_and_technology_still_never_calculate(xdb):
    _labor(xdb)
    _xrule(xdb)
    _s, _v, r = _gap500(xdb)
    for pt in ("CAPACITY_CHANGE", "TECHNOLOGY_ADOPTION"):
        (p,) = _by_type(r, pt)
        assert p["calc_status"] == "NEEDS_INPUT" and p["quantity"] is None


def test_fingerprint_reflects_rule_version_and_productivity_and_is_idempotent(xdb):
    _labor(xdb)
    v1 = _xrule(xdb)
    s, v, r1 = _gap500(xdb)
    assert _run(xdb, v)["created"] is False  # cùng input => run cũ
    xr.retire_rule(xdb, ADMIN2, v1.id, "thay")
    v2 = xr.new_version(xdb, ADMIN, v1.id)
    xr.update_rule(xdb, ADMIN, v2.id, {"productivity_value": 250.0,
                                       "sample_input": {**v1.sample_input_json, "productivity_per_worker": 250.0},
                                       "sample_expected": {"required_incremental_labor": 2, "additional_labor": 2, "proposed_increment": 500, "remaining_gap_after_proposal": 0}})
    xr.submit_review(xdb, ADMIN, v2.id)
    xr.approve_rule(xdb, ADMIN2, v2.id)
    r2 = _run(xdb, v)
    assert r2["created"] is True and r2["run"]["run_fingerprint"] != r1["run"]["run_fingerprint"]
    assert _by_type(r2, "LABOR_RECRUITMENT")[0]["quantity"] == 2 and _by_type(r2, "LABOR_RECRUITMENT")[0]["calculation_rule_version"] == "LAB-A@v2"
    # run cũ bất biến, vẫn reproduce được dù rule đã bị supersede/retire
    old = eng.run_view(xdb, xdb.get(RoadmapRun, r1["run"]["id"]))
    op = [x for x in old["proposals"] if x["proposal_type"] == "LABOR_RECRUITMENT"][0]
    assert op["quantity"] == 5 and op["calculation_rule_version"] == "LAB-A@v1"
    assert old["snapshot"]["executable_rules"][0]["productivity_value"] == 120.0
    assert op["input_snapshot"]["executable_rule"]["adapter_code"] == LAB and op["input_snapshot"]["adapter_input"]["productivity_per_worker"] == 120.0


def test_compare_runs_shows_quantity_change(xdb):
    _labor(xdb)
    _xrule(xdb)
    _s, v, r1 = _gap500(xdb)
    xdb.add(MachineCapacity(factory_code="XN1", line="9", machine_type="1K", quantity=1, status="ACTIVE"))
    xdb.commit()
    _xrule(xdb, MAC, prod=300.0)
    r2 = _run(xdb, v)
    cmp_ = eng.compare_runs(xdb, r1["run"]["id"], r2["run"]["id"])
    row = [x for x in cmp_["proposals"] if x["proposal_type"] == "MACHINE_PURCHASE" and x["rule"] == "MAC-A@v1"][0]
    assert row["a"] is None and row["b"]["quantity"] == 2


def test_source_tables_untouched_and_no_derivation_from_placeholders(xdb):
    """Productivity chỉ đến từ rule; bảng nguồn placeholder (nominal 1000 / efficiency 0.85) đổi giá trị không ảnh hưởng quantity."""
    xdb.add(MachineCapacity(factory_code="XN1", line="1", machine_type="1K", quantity=10, nominal_output_per_day=1000, efficiency=0.85, status="ACTIVE"))
    xdb.commit()
    _xrule(xdb, MAC, prod=300.0)
    _s, v, r1 = _gap500(xdb)
    xdb.query(MachineCapacity).update({"nominal_output_per_day": 1, "efficiency": 0.01})
    xdb.commit()
    r2 = _run(xdb, v)
    assert _by_type(r1, "MACHINE_PURCHASE")[0]["quantity"] == 2 == _by_type(r2, "MACHINE_PURCHASE")[0]["quantity"]
    assert r2["created"] is False  # placeholder không tham gia fingerprint


# =================================================================== API layer
def test_api_permissions_and_options(xdb):
    body = rm_api.ExecRuleBody(**_body())
    r = rm_api.create_exec_rule(body, xdb, ADMIN)
    rid = r["id"]
    rm_api.submit_exec_rule_review(rid, xdb, ADMIN)
    with pytest.raises(HTTPException) as e:
        rm_api.approve_exec_rule(rid, xdb, PLANNER)  # thiếu roadmap.approve
    assert e.value.status_code == 403 and xr.get_rule(xdb, rid).status == "UNDER_REVIEW"
    with pytest.raises(HTTPException) as e:
        rm_api.retire_exec_rule(rid, rm_api.RetireBody(reason="x"), xdb, PLANNER)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        rm_api.approve_exec_rule(rid, xdb, ADMIN)  # four-eyes: cùng reviewer
    assert e.value.status_code == 409
    assert rm_api.approve_exec_rule(rid, xdb, ADMIN2)["status"] == "APPROVED"
    assert rm_api.verify_exec_rule_sample(rid, xdb, ADMIN)["ok"] is True
    assert [h["to_status"] for h in rm_api.exec_rule_history(rid, xdb, ADMIN)] == ["DRAFT", "UNDER_REVIEW", "APPROVED"]
    opts = rm_api.options(ADMIN)
    assert [a["adapter_code"] for a in opts["adapters"]] == [LAB, MAC] and "ESTIMATE" in opts["exec_blocked_source_kinds"]


def test_http_executable_rules_routes(xdb):
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.db.session import get_db
    from app.main import app

    admin = SimpleNamespace(username="admin", role="ADMIN", id=1, is_active=True, must_change_password=False)
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_db] = lambda: xdb
    try:
        c = TestClient(app)
        B = "/api/roadmap/executable-rules"
        assert c.get(B).json() == []
        assert c.post(B, json={**_body(), "adapter_code": "LABOR_REQUIREMENT_V1"}).status_code == 422
        rid = c.post(B, json=_body()).json()["id"]
        assert c.get(f"{B}/{rid}").json()["executable"] is False
        assert c.post(f"{B}/{rid}/submit-review").status_code == 200
        assert c.post(f"{B}/{rid}/approve").status_code == 409  # cùng user => four-eyes
        assert c.get("/api/roadmap/options").json()["adapters"][0]["adapter_code"] == LAB
    finally:
        app.dependency_overrides.clear()


# =================================================================== GPT review round 1 (PR #14)
def test_retire_only_from_approved(xdb):
    r = xr.create_rule(xdb, ADMIN, _body())
    xr.submit_review(xdb, ADMIN, r.id)
    with pytest.raises(HTTPException) as e:
        xr.retire_rule(xdb, ADMIN2, r.id, "từ chối review")  # UNDER_REVIEW -> RETIRED không thuộc contract
    assert e.value.status_code == 409 and xr.get_rule(xdb, r.id).status == "UNDER_REVIEW"
    d = xr.create_rule(xdb, ADMIN, _body(rule_code="LAB-D"))
    with pytest.raises(HTTPException):
        xr.retire_rule(xdb, ADMIN2, d.id, "x")  # DRAFT -> RETIRED cũng không
    ok = _xrule(xdb, rule_code="LAB-OK")
    assert xr.retire_rule(xdb, ADMIN2, ok.id, "hết hiệu lực").status == "RETIRED"


def test_fingerprint_ignores_unrelated_executable_rules(xdb):
    _labor(xdb)
    _s, v, r1 = _gap500(xdb)
    assert _run(xdb, v)["created"] is False
    _xrule(xdb, rule_code="LAB-XN2", scope_type="FACTORY", scope_value="XN2")  # scope khác scenario TOTAL
    assert _run(xdb, v)["created"] is False
    _xrule(xdb, rule_code="LAB-FUT", effective_from="2027-01-01")  # hiệu lực ngoài mọi milestone (2026-08-31)
    assert _run(xdb, v)["created"] is False
    xr.retire_rule(xdb, ADMIN2, xr.list_rules(xdb)[0].id, "retire rule không liên quan")
    assert _run(xdb, v)["created"] is False
    rel = _xrule(xdb, rule_code="LAB-REL")  # đúng scope + hiệu lực => run mới
    r2 = _run(xdb, v)
    assert r2["created"] is True and _by_type(r2, "LABOR_RECRUITMENT")[0]["quantity"] == 5
    assert _run(xdb, v)["created"] is False
    assert [x["rule_code"] for x in r2["run"]["snapshot"]["executable_rules"]] == ["LAB-REL"]  # snapshot chỉ chứa rule relevant
    xr.retire_rule(xdb, ADMIN2, rel.id, "retire rule relevant")
    back = _run(xdb, v)  # retire rule relevant => effective inputs quay về trạng thái không rule => trả lại run gốc (idempotent), không tạo run trùng
    assert back["created"] is False and back["run"]["id"] == r1["run"]["id"]
    rel2 = _xrule(xdb, rule_code="LAB-REL2", prod=200.0)  # đổi rule relevant khác => run mới
    assert rel2.status == "APPROVED" and _run(xdb, v)["created"] is True


def test_period_mismatch_rule_is_relevant_and_fingerprinted(xdb):
    _labor(xdb)
    _s, v, _r = _gap500(xdb)
    _xrule(xdb, period="YEAR", prod=1440.0)  # tạo dòng NEEDS_INPUT PERIOD_MISMATCH => relevant
    assert _run(xdb, v)["created"] is True


def test_machine_inventory_only_matters_for_relevant_machine_rules(xdb):
    _machines(xdb, "XN1", "1K", 10)
    _xrule(xdb, MAC, rule_code="MAC-1K", prod=300.0)  # relevant (TOTAL, hiệu lực)
    _xrule(xdb, MAC, rule_code="MAC-2K", prod=300.0, machine_type_code="2K", scope_type="FACTORY", scope_value="XN2")  # không relevant với scenario TOTAL
    _s, v, r1 = _gap500(xdb)
    assert _by_type(r1, "MACHINE_PURCHASE")[0]["calculation_rule_version"] == "MAC-1K@v1"
    _machines(xdb, "XN2", "2K", 7)  # tồn kho loại máy chỉ thuộc rule không liên quan
    assert _run(xdb, v)["created"] is False
    _machines(xdb, "XN1", "1K", 3)  # tồn kho loại máy của rule relevant
    r3 = _run(xdb, v)
    assert r3["created"] is True and _by_type(r3, "MACHINE_PURCHASE")[0]["calculation"]["available_machines"] == 13
