from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import dashboard_rules as dr
from app.core.permissions import permissions_for
from app.db.session import Base, utcnow
from app.models.core import Factory
from app.models.dashboard_cfg import (
    DashboardIndicator,
    DashboardIndicatorGroup,
    DashboardLayout,
    DashboardLayoutItem,
    DashboardRuleRegistry,
)
from app.models.data import SyncRun
from app.services import dashboard_meta as m

ADMIN = SimpleNamespace(username="admin", role="ADMIN")


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[Factory.__table__, SyncRun.__table__, DashboardIndicatorGroup.__table__, DashboardIndicator.__table__, DashboardRuleRegistry.__table__,
                DashboardLayout.__table__, DashboardLayoutItem.__table__],
    )
    s = sessionmaker(bind=engine)()
    s.add_all([Factory(code=f"XN{n}", name=f"Xí nghiệp {n}", sql_xn_id=n, display_order=n) for n in (1, 2, 3)])
    s.add(DashboardIndicatorGroup(group_code="G", group_name="Nhóm thử"))
    s.commit()
    events: list[str] = []
    monkeypatch.setattr(m, "write_audit", lambda action, **kw: events.append(action))
    monkeypatch.setattr(m, "seed_events", events, raising=False)
    m.clear_cache()
    s.audit = events  # type: ignore[attr-defined]

    def good_rule(ctx):
        return {"value": 42, "scope": ctx.scope, "items": [{"id": 1}]}

    def boom_rule(ctx):
        raise RuntimeError("nguồn dữ liệu hỏng")

    for code, fn in (("T_GOOD", good_rule), ("T_BOOM", boom_rule)):
        dr.register_for_tests(dr.RuleInfo(code, code, fn, "tests", fn.__name__, "rule thử"))
        s.add(DashboardRuleRegistry(rule_code=code, rule_name=code))
    s.commit()
    yield s
    for code in ("T_GOOD", "T_BOOM"):
        dr.RULES.pop(code, None)
    s.close()


def ind(code="I1", **kw):
    base = dict(indicator_code=code, indicator_name=code, group_code="G", display_type="KPI_CARD", rule_code="T_GOOD", default_scope="BOTH", drilldown_type="NONE",
                refresh_mode="ON_LOAD", config_json={})
    return {**base, **kw}


def item(code, x=0, y=0, w=6, h=3, **kw):
    return {"indicator_code": code, "grid_x": x, "grid_y": y, "width": w, "height": h, **kw}


def publish_layout(db, code, items, scope_type="COMPANY", scope_value="", name=None):
    l = m.create_layout(db, ADMIN, {"layout_code": code, "layout_name": name or code, "scope_type": scope_type, "scope_value": scope_value, "items": items})
    return m.publish_layout(db, ADMIN, l.id)


def test_create_indicator_and_audit(db):
    row = m.save_indicator(db, ADMIN, ind())
    assert row.indicator_code == "I1" and "DASHBOARD_INDICATOR_CREATE" in db.audit
    with pytest.raises(HTTPException) as e:
        m.save_indicator(db, ADMIN, ind())
    assert e.value.status_code == 409


@pytest.mark.parametrize("patch", [{"rule_code": "NOT_REGISTERED"}, {"display_type": "PIE_3D"}, {"group_code": "NOPE"}, {"default_scope": "GALAXY"}, {"config_json": "text"}])
def test_invalid_indicator_rejected(db, patch):
    with pytest.raises(HTTPException) as e:
        m.save_indicator(db, ADMIN, ind(**patch))
    assert e.value.status_code == 422


def test_inactive_rule_rejected(db):
    db.query(DashboardRuleRegistry).filter_by(rule_code="T_GOOD").update({"is_active": False})
    db.commit()
    with pytest.raises(HTTPException, match="vô hiệu"):
        m.save_indicator(db, ADMIN, ind())


def test_no_arbitrary_code_path(db):
    # rule chỉ được chọn theo mã đã đăng ký; đường dẫn file / module không được chấp nhận
    for bad in (r"C:\abc\xyz.py", "os.system", "app.dashboard_rules:build_revenue_summary"):
        with pytest.raises(HTTPException):
            m.save_indicator(db, ADMIN, ind(rule_code=bad))


def test_disabled_indicator_excluded_from_runtime_and_disable_audited(db):
    m.save_indicator(db, ADMIN, ind("A"))
    m.save_indicator(db, ADMIN, ind("B"))
    publish_layout(db, "L", [item("A", 0, 0), item("B", 6, 0)])
    out = m.build_runtime(db, ADMIN, "TONG")
    assert {i["indicator"]["indicator_code"] for i in out["items"]} == {"A", "B"}
    m.save_indicator(db, ADMIN, {"is_active": False}, "B")
    out = m.build_runtime(db, ADMIN, "TONG")
    assert {i["indicator"]["indicator_code"] for i in out["items"]} == {"A"}
    assert "DASHBOARD_INDICATOR_DISABLE" in db.audit
    assert db.query(DashboardIndicator).filter_by(indicator_code="B").one()  # disable không phải delete


def test_published_layout_is_immutable_and_draft_editable(db):
    m.save_indicator(db, ADMIN, ind("A"))
    l = publish_layout(db, "L", [item("A")])
    with pytest.raises(HTTPException) as e:
        m.update_layout(db, ADMIN, l.id, {"items": [item("A", 3, 0)]})
    assert e.value.status_code == 409
    draft = m.clone_layout(db, ADMIN, l.id)
    assert draft.status == "DRAFT" and draft.version == 2
    m.update_layout(db, ADMIN, draft.id, {"items": [item("A", 6, 0)]})
    with pytest.raises(HTTPException, match="bản nháp"):
        m.clone_layout(db, ADMIN, l.id)  # đã có Draft


def test_draft_move_does_not_change_published_runtime_until_publish(db):
    m.save_indicator(db, ADMIN, ind("A"))
    l = publish_layout(db, "L", [item("A", 0, 0)])
    draft = m.clone_layout(db, ADMIN, l.id)
    m.update_layout(db, ADMIN, draft.id, {"items": [item("A", 6, 2)]})
    pos = m.build_runtime(db, ADMIN, "TONG")["items"][0]["position"]
    assert (pos["x"], pos["y"]) == (0, 0)  # người dùng thường vẫn thấy bản Published
    m.publish_layout(db, ADMIN, draft.id)
    pos = m.build_runtime(db, ADMIN, "TONG")["items"][0]["position"]
    assert (pos["x"], pos["y"]) == (6, 2)
    statuses = {(l.version, l.status) for l in db.query(DashboardLayout).filter_by(layout_code="L")}
    assert statuses == {(1, "RETIRED"), (2, "PUBLISHED")}  # Publish thay thế bản cũ
    assert {"DASHBOARD_LAYOUT_CREATE", "DASHBOARD_LAYOUT_PUBLISH"} <= set(db.audit)


def test_publish_supersedes_other_default_for_same_scope(db):
    m.save_indicator(db, ADMIN, ind("A"))
    first = publish_layout(db, "ONE", [item("A")])
    second = publish_layout(db, "TWO", [item("A", 3, 0)])
    db.refresh(first)
    assert first.status == "RETIRED" and second.status == "PUBLISHED"
    assert m.resolve_layout(db, "TONG").layout_code == "TWO"


def test_scope_layout_resolution_factory_specific_generic_and_company_fallback(db):
    m.save_indicator(db, ADMIN, ind("A"))
    publish_layout(db, "CORP", [item("A")], "COMPANY")
    assert m.resolve_layout(db, "XN2").layout_code == "CORP"  # chưa có bố cục XN -> dùng Company
    publish_layout(db, "FAC", [item("A")], "FACTORY", "")
    assert m.resolve_layout(db, "XN2").layout_code == "FAC" and m.resolve_layout(db, "TONG").layout_code == "CORP"
    publish_layout(db, "XN2ONLY", [item("A")], "FACTORY", "XN2")
    assert m.resolve_layout(db, "XN2").layout_code == "XN2ONLY" and m.resolve_layout(db, "XN1").layout_code == "FAC"


def test_overlap_and_out_of_grid_rejected(db):
    m.save_indicator(db, ADMIN, ind("A"))
    m.save_indicator(db, ADMIN, ind("B"))
    l = m.create_layout(db, ADMIN, {"layout_code": "L", "layout_name": "L", "items": [item("A", 0, 0, 6, 3), item("B", 3, 1, 6, 3)]})
    with pytest.raises(HTTPException, match="chồng lấn"):
        m.publish_layout(db, ADMIN, l.id)
    with pytest.raises(HTTPException, match="vượt lưới"):
        m.update_layout(db, ADMIN, l.id, {"items": [item("A", 10, 0, 6, 3)]})
    with pytest.raises(HTTPException, match="hai lần"):
        m.update_layout(db, ADMIN, l.id, {"items": [item("A"), item("A", 6, 0)]})


def test_registered_rule_executes_and_exception_is_isolated(db):
    m.save_indicator(db, ADMIN, ind("GOOD"))
    m.save_indicator(db, ADMIN, ind("BAD", rule_code="T_BOOM"))
    publish_layout(db, "L", [item("GOOD", 0, 0), item("BAD", 6, 0)])
    out = {i["indicator"]["indicator_code"]: i["data"] for i in m.build_runtime(db, ADMIN, "XN1")["items"]}
    assert out["GOOD"]["status"] == "OK" and out["GOOD"]["payload"]["value"] == 42 and out["GOOD"]["payload"]["scope"] == "XN1"
    assert out["BAD"]["status"] == "ERROR" and "hỏng" in out["BAD"]["message"] and out["BAD"]["payload"] is None  # widget hỏng không làm sập Dashboard
    assert out["GOOD"]["meta"]["rule_version"] == "1" and "last_calculated_at" in out["GOOD"]["meta"]


def test_stale_status_propagates_from_source_sync_age(db):
    m.save_indicator(db, ADMIN, ind("A", data_freshness_requirement="1"))
    publish_layout(db, "L", [item("A")])
    assert m.build_runtime(db, ADMIN, "TONG")["items"][0]["data"]["meta"]["data_freshness"] == "UNKNOWN"  # chưa từng đồng bộ
    db.add(SyncRun(run_code="SYNC-1", source="EGMF_REVENUE", trigger_type="MANUAL", status="SUCCEEDED", started_at=utcnow() - timedelta(hours=5), triggered_by="x"))
    db.commit()
    data = m.build_runtime(db, ADMIN, "TONG")["items"][0]["data"]
    assert data["status"] == "STALE" and data["meta"]["data_freshness"] == "STALE" and data["payload"]["value"] == 42  # vẫn render, có dấu stale


def test_scope_restricted_indicators_hidden_in_other_view(db):
    m.save_indicator(db, ADMIN, ind("CO", default_scope="COMPANY"))
    m.save_indicator(db, ADMIN, ind("FA", default_scope="FACTORY"))
    publish_layout(db, "L", [item("CO", 0, 0), item("FA", 6, 0)], "COMPANY")
    corp = {i["indicator"]["indicator_code"] for i in m.build_runtime(db, ADMIN, "TONG")["items"]}
    fac = {i["indicator"]["indicator_code"] for i in m.build_runtime(db, ADMIN, "XN1")["items"]}
    assert corp == {"CO"} and fac == {"FA"}


def test_rule_test_records_last_test_and_audit(db):
    out = m.test_rule(db, ADMIN, "T_GOOD", "TONG")
    assert out["status"] == "OK"
    reg = db.query(DashboardRuleRegistry).filter_by(rule_code="T_GOOD").one()
    assert reg.last_test["status"] == "OK" and reg.last_test["by"] == "admin" and "DASHBOARD_RULE_TEST" in db.audit
    with pytest.raises(HTTPException) as e:
        m.test_rule(db, ADMIN, "NOT_REGISTERED")
    assert e.value.status_code == 404


def test_permissions_only_admin_can_configure():
    admin = set(permissions_for("ADMIN"))
    for perm in ("dashboard.config_view", "dashboard.config_manage", "dashboard.layout_manage", "dashboard.rule_test", "dashboard.publish"):
        assert perm in admin
        assert perm not in permissions_for("PLANNER") and perm not in permissions_for("VIEWER")
    assert "dashboard.view" in permissions_for("VIEWER")


def test_retire_refuses_last_default_layout(db):
    m.save_indicator(db, ADMIN, ind("A"))
    l = publish_layout(db, "ONLY", [item("A")])
    with pytest.raises(HTTPException, match="duy nhất"):
        m.retire_layout(db, ADMIN, l.id)


def test_group_crud_and_inactive_group_hides_indicators(db):
    m.save_group(db, ADMIN, {"group_code": "G2", "group_name": "Nhóm 2"})
    assert "DASHBOARD_GROUP_CREATE" in db.audit
    m.save_indicator(db, ADMIN, ind("A", group_code="G2"))
    publish_layout(db, "L", [item("A")])
    assert len(m.build_runtime(db, ADMIN, "TONG")["items"]) == 1
    m.save_group(db, ADMIN, {"is_active": False}, "G2")
    assert m.build_runtime(db, ADMIN, "TONG")["items"] == []
    with pytest.raises(HTTPException):
        m.save_group(db, ADMIN, {"group_code": "G3", "group_name": "x", "layout_mode": "MASONRY"})
