"""Metadata Dashboard: seed, kiểm tra hợp lệ, quản lý bố cục (Draft → Published), và Runtime dựng Dashboard từ metadata."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.dashboard_rules import RULES, DashboardContext, execute_rule
from app.db.session import utcnow
from app.models.core import User
from app.models.dashboard_cfg import (
    DashboardIndicator,
    DashboardIndicatorGroup,
    DashboardLayout,
    DashboardLayoutItem,
    DashboardLayoutSection,
    DashboardRuleRegistry,
)
from app.services import dashboard as svc
from app.services.audit import write_audit

DISPLAY_TYPES = (
    "KPI_CARD", "PROGRESS_BAR", "COMPARISON_BAR", "GAUGE", "COUNTER", "STATUS_COUNTER", "LINE_CHART", "BAR_CHART", "STACKED_BAR",
    "TABLE", "MATRIX", "TREND", "SIGNAL_LIST", "TEXT", "CUSTOM_COMPONENT",
)
SCOPES = ("COMPANY", "FACTORY", "BOTH")
DRILLDOWNS = ("NONE", "DRAWER", "PAGE", "MODAL", "CUSTOM")
REFRESH_MODES = ("REALTIME", "SYNC", "CACHED", "ON_LOAD")
SECTIONS = ("MAIN", "RIGHT_SIDEBAR", "BOTTOM", "FULL_WIDTH")
LAYOUT_MODES = ("GRID", "STACK", "CUSTOM")
GRID_COLUMNS = 12
LAYOUT_SCOPES = ("COMPANY", "FACTORY")
# Section presets của Layout Designer: số cột theo tỉ lệ trên lưới 12 (không resize pixel tự do)
SECTION_PRESETS: dict[str, list[int]] = {"100": [12], "50_50": [6, 6], "66_34": [8, 4], "34_66": [4, 8], "33_33_33": [4, 4, 4], "25_25_25_25": [3, 3, 3, 3]}
CUSTOM_PRESET = "CUSTOM"  # tỉ lệ % tự do theo cột, xem DashboardLayoutSection.custom_spans


def section_spans(preset: str, custom_spans: list | None) -> list[float]:
    if preset == CUSTOM_PRESET:
        return [float(x) for x in custom_spans] if custom_spans else [50.0, 50.0]
    return SECTION_PRESETS.get(preset, [12])

_cache: dict[tuple, tuple[float, dict]] = {}


def clear_cache() -> None:
    _cache.clear()


# ------------------------------------------------------------------ seed
GROUPS = [
    ("REVENUE", "Doanh thu", "Doanh thu / thực hiện theo xí nghiệp", 1),
    ("ORDER_PROGRESS", "Tiến độ đơn hàng", "Tiến độ PO và rủi ro giao hàng", 2),
    ("QA", "Chất lượng", "Tổng số lỗi theo nhóm kiểm tra", 3),
    ("HR", "Nhân sự", "Lao động theo xí nghiệp/tổ", 4),
    ("SIGNALS", "Tín hiệu", "Tin tốt và cảnh báo", 5),
    ("GENERAL", "Chung", "Widget tĩnh (văn bản, tiêu đề)", 6),
    ("PRODUCTION", "Sản xuất trong ngày", "Sản lượng, hiệu suất, RFT hôm nay theo xí nghiệp", 7),
]

# code, name, group, display_type, rule, source, scope, drilldown_type, drilldown_target, refresh, config
INDICATORS = [
    ("REVENUE_EXECUTIVE_SUMMARY", "Doanh thu", "REVENUE", "CUSTOM_COMPONENT", "REVENUE_EXECUTIVE_SUMMARY", "eGMF/PostgreSQL", "BOTH", "DRAWER", "REVENUE_DETAIL",
     "CACHED", {"periodOptions": ["MONTH", "YTD"], "showCorporateTotal": True, "component": "REVENUE_EXECUTIVE_SUMMARY", "cache_seconds": 30}),
    ("ORDER_PROGRESS_MATRIX", "Tiến độ đơn hàng", "ORDER_PROGRESS", "MATRIX", "ORDER_PROGRESS_MATRIX", "eGMF/PostgreSQL", "BOTH", "DRAWER", "ORDER_DETAIL",
     "CACHED", {"cache_seconds": 30}),
    ("QA_COMPARISON", "Chất lượng (QA)", "QA", "BAR_CHART", "QA_COMPARISON", "eGMF/PostgreSQL", "BOTH", "DRAWER", "QA_DETAIL", "CACHED", {"cache_seconds": 30}),
    ("PO_RISK_PIPELINE", "Tiến độ kế hoạch", "ORDER_PROGRESS", "CUSTOM_COMPONENT", "PO_RISK_PIPELINE", "Excel kế hoạch SX", "BOTH", "DRAWER", "PO_DETAIL",
     "SYNC", {"component": "PO_RISK_PIPELINE"}),
    ("HR_HEADCOUNT", "Nhân sự", "HR", "CUSTOM_COMPONENT", "HR_HEADCOUNT", "Excel kế hoạch SX", "BOTH", "DRAWER", "HR_DETAIL", "SYNC", {"component": "HR_HEADCOUNT"}),
    ("GOOD_NEWS", "Tin tốt", "SIGNALS", "SIGNAL_LIST", "GOOD_NEWS", "Tổng hợp", "BOTH", "DRAWER", "SIGNAL_DRILL", "ON_LOAD", {"zone": "GOOD"}),
    ("OUTPUT_TODAY", "Sản lượng hôm nay", "PRODUCTION", "GAUGE", "OUTPUT_TODAY", "eGMF/PostgreSQL", "BOTH", "NONE", "", "CACHED", {"cache_seconds": 60}),
    ("EFFICIENCY_TODAY", "Hiệu suất hôm nay", "PRODUCTION", "GAUGE", "EFFICIENCY_TODAY", "Tạm cố định", "BOTH", "NONE", "", "CACHED", {"cache_seconds": 60}),
    ("RFT_TODAY", "RFT hôm nay", "PRODUCTION", "GAUGE", "RFT_TODAY", "hiPro (tạm cố định)", "BOTH", "NONE", "", "CACHED", {"cache_seconds": 60}),
    ("TEXT_HEADING", "Văn bản / Tiêu đề", "GENERAL", "TEXT", "STATIC_TEXT", "Nhập tay", "BOTH", "NONE", "", "ON_LOAD", {"text": "", "heading": True}),
    ("WARNING_SIGNALS", "Cảnh báo / cần chú ý", "SIGNALS", "SIGNAL_LIST", "WARNING_SIGNALS", "Tổng hợp", "BOTH", "DRAWER", "SIGNAL_DRILL", "ON_LOAD", {"zone": "WARN"}),
]

# indicator_code, section, x, y, w, h
DEFAULT_ITEMS = [
    ("REVENUE_EXECUTIVE_SUMMARY", "MAIN", 0, 0, 8, 5),
    ("ORDER_PROGRESS_MATRIX", "MAIN", 0, 5, 8, 3),
    ("QA_COMPARISON", "MAIN", 0, 8, 8, 4),
    ("PO_RISK_PIPELINE", "MAIN", 0, 12, 8, 4),
    ("HR_HEADCOUNT", "MAIN", 0, 16, 8, 3),
    ("GOOD_NEWS", "RIGHT_SIDEBAR", 8, 0, 4, 4),
    ("WARNING_SIGNALS", "RIGHT_SIDEBAR", 8, 4, 4, 8),
]


def seed_dashboard_meta(db: Session) -> None:
    """Idempotent: nhóm, rule registry (đồng bộ từ whitelist trong code), chỉ số và bố cục mặc định giống Dashboard hiện tại."""
    have_groups = {g.group_code for g in db.query(DashboardIndicatorGroup.group_code)}
    for code, name, desc, order in GROUPS:
        if code not in have_groups:
            db.add(DashboardIndicatorGroup(group_code=code, group_name=name, description=desc, display_order=order, created_by="system", updated_by="system"))
    db.flush()

    have_rules = {r.rule_code: r for r in db.query(DashboardRuleRegistry)}
    for info in RULES.values():
        row = have_rules.get(info.code)
        fields = dict(rule_name=info.name, rule_module=info.module, rule_function=info.function, rule_version=info.version, description=info.description,
                      input_contract=info.input_contract, output_contract=info.output_contract)
        if row is None:
            db.add(DashboardRuleRegistry(rule_code=info.code, created_by="system", updated_by="system", **fields))
        else:
            for k, v in fields.items():
                setattr(row, k, v)

    have_ind = {i.indicator_code for i in db.query(DashboardIndicator.indicator_code)}
    for i, (code, name, group, dtype, rule, source, scope, dd_type, dd_target, refresh, cfg) in enumerate(INDICATORS, start=1):
        if code not in have_ind:
            db.add(DashboardIndicator(
                indicator_code=code, indicator_name=name, group_code=group, display_type=dtype, rule_code=rule, data_source=source, default_scope=scope,
                drilldown_type=dd_type, drilldown_target=dd_target, refresh_mode=refresh, display_order=i, config_json=cfg, created_by="system", updated_by="system",
                data_freshness_requirement="48" if "eGMF" in source else "",
            ))
    db.flush()

    for layout_code, name, scope_type in (("CORPORATE_DEFAULT", "Tổng công ty — mặc định", "COMPANY"), ("FACTORY_DEFAULT", "Xí nghiệp — mặc định", "FACTORY")):
        if db.query(DashboardLayout).filter(DashboardLayout.layout_code == layout_code).first():
            continue
        layout = DashboardLayout(layout_code=layout_code, layout_name=name, scope_type=scope_type, scope_value="", version=1, status="PUBLISHED", is_default=True,
                                 description="Bố cục mặc định giống Dashboard trước khi có metadata", created_by="system", published_by="system", published_at=utcnow())
        db.add(layout)
        db.flush()
        for n, (ind, section, x, y, w, h) in enumerate(DEFAULT_ITEMS, start=1):
            db.add(DashboardLayoutItem(layout_id=layout.id, indicator_code=ind, section=section, grid_x=x, grid_y=y, width=w, height=h, order_no=n))
    db.commit()


# ------------------------------------------------------------------ view helpers
def group_view(g: DashboardIndicatorGroup) -> dict:
    return {"id": g.id, "group_code": g.group_code, "group_name": g.group_name, "description": g.description, "default_enabled": g.default_enabled,
            "display_order": g.display_order, "layout_mode": g.layout_mode, "collapsible": g.collapsible, "is_active": g.is_active}


def indicator_view(i: DashboardIndicator) -> dict:
    return {"id": i.id, "indicator_code": i.indicator_code, "indicator_name": i.indicator_name, "group_code": i.group_code, "description": i.description,
            "display_type": i.display_type, "rule_code": i.rule_code, "data_source": i.data_source, "default_scope": i.default_scope,
            "drilldown_type": i.drilldown_type, "drilldown_target": i.drilldown_target, "refresh_mode": i.refresh_mode, "default_enabled": i.default_enabled,
            "is_active": i.is_active, "display_order": i.display_order, "owner": i.owner, "data_freshness_requirement": i.data_freshness_requirement,
            "config_json": i.config_json or {}}


def rule_view(r: DashboardRuleRegistry) -> dict:
    return {"id": r.id, "rule_code": r.rule_code, "rule_name": r.rule_name, "rule_module": r.rule_module, "rule_function": r.rule_function,
            "rule_version": r.rule_version, "description": r.description, "input_contract": r.input_contract, "output_contract": r.output_contract,
            "is_active": r.is_active, "last_test": r.last_test or {}, "registered": r.rule_code in RULES}


def item_view(it: DashboardLayoutItem) -> dict:
    return {"id": it.id, "indicator_code": it.indicator_code, "section": it.section, "grid_x": it.grid_x, "grid_y": it.grid_y, "width": it.width,
            "height": it.height, "order_no": it.order_no, "is_visible": it.is_visible, "collapsed": it.collapsed, "config_override_json": it.config_override_json or {},
            "section_id": it.section_id, "column_no": it.column_no}


def layout_view(db: Session, l: DashboardLayout, with_items: bool = False) -> dict:
    out = {"id": l.id, "layout_code": l.layout_code, "layout_name": l.layout_name, "scope_type": l.scope_type, "scope_value": l.scope_value, "version": l.version,
           "status": l.status, "is_default": l.is_default, "description": l.description, "created_by": l.created_by, "created_at": l.created_at.isoformat(),
           "published_by": l.published_by, "published_at": l.published_at.isoformat() if l.published_at else None,
           "retired_at": l.retired_at.isoformat() if l.retired_at else None}
    if with_items:
        out["items"] = [item_view(it) for it in db.query(DashboardLayoutItem).filter(DashboardLayoutItem.layout_id == l.id).order_by(DashboardLayoutItem.order_no, DashboardLayoutItem.id)]
        out["sections"] = [section_view(x) for x in _sections(db, l.id)]
    return out


def section_view(x: DashboardLayoutSection) -> dict:
    return {"id": x.id, "order_no": x.order_no, "title": x.title, "preset": x.preset, "custom_spans": x.custom_spans, "is_visible": x.is_visible, "spans": section_spans(x.preset, x.custom_spans)}


def _sections(db: Session, layout_id: int) -> list[DashboardLayoutSection]:
    return db.query(DashboardLayoutSection).filter(DashboardLayoutSection.layout_id == layout_id).order_by(DashboardLayoutSection.order_no, DashboardLayoutSection.id).all()


# ------------------------------------------------------------------ nhóm / chỉ số
def _bad(msg: str) -> HTTPException:
    return HTTPException(422, msg)


def validate_indicator(db: Session, d: dict, existing_code: str | None = None) -> None:
    if not d.get("indicator_code") or not d.get("indicator_name"):
        raise _bad("Cần mã và tên chỉ số")
    if existing_code is None and db.query(DashboardIndicator).filter(DashboardIndicator.indicator_code == d["indicator_code"]).first():
        raise HTTPException(409, f"Mã chỉ số '{d['indicator_code']}' đã tồn tại")
    if db.query(DashboardIndicatorGroup).filter(DashboardIndicatorGroup.group_code == d.get("group_code")).first() is None:
        raise _bad(f"Nhóm '{d.get('group_code')}' không tồn tại")
    rule = d.get("rule_code")
    if rule not in RULES:
        raise _bad(f"Rule '{rule}' chưa được đăng ký trong code — chỉ chọn được rule có trong Rule Registry")
    reg = db.query(DashboardRuleRegistry).filter(DashboardRuleRegistry.rule_code == rule).first()
    if reg is not None and not reg.is_active:
        raise _bad(f"Rule '{rule}' đang bị vô hiệu hóa")
    for key, allowed in (("display_type", DISPLAY_TYPES), ("default_scope", SCOPES), ("drilldown_type", DRILLDOWNS), ("refresh_mode", REFRESH_MODES)):
        if d.get(key) not in allowed:
            raise _bad(f"{key} = '{d.get(key)}' không hợp lệ (chọn: {', '.join(allowed)})")
    if not isinstance(d.get("config_json", {}), dict):
        raise _bad("config_json phải là một đối tượng JSON")
    fr = d.get("data_freshness_requirement", "")
    if fr not in ("", None):
        try:
            float(fr)
        except ValueError:
            raise _bad("Yêu cầu độ tươi dữ liệu phải là số giờ (VD 26) hoặc để trống")


INDICATOR_FIELDS = ("indicator_name", "group_code", "description", "display_type", "rule_code", "data_source", "default_scope", "drilldown_type", "drilldown_target",
                    "refresh_mode", "default_enabled", "is_active", "display_order", "owner", "data_freshness_requirement", "config_json")


def save_indicator(db: Session, user: User, d: dict, code: str | None = None) -> DashboardIndicator:
    d = {**d, "config_json": d.get("config_json") or {}}
    if code:
        row = db.query(DashboardIndicator).filter(DashboardIndicator.indicator_code == code).first()
        if row is None:
            raise HTTPException(404, "Không có chỉ số này")
        merged = {**indicator_view(row), **d, "indicator_code": code}
        validate_indicator(db, merged, existing_code=code)
        before = indicator_view(row)
        for f in INDICATOR_FIELDS:
            if f in merged:
                setattr(row, f, merged[f])
        row.updated_by, row.updated_at = user.username, utcnow()
        action = "DASHBOARD_INDICATOR_UPDATE"
        if before["is_active"] != row.is_active:
            action = "DASHBOARD_INDICATOR_ENABLE" if row.is_active else "DASHBOARD_INDICATOR_DISABLE"
    else:
        validate_indicator(db, d)
        row = DashboardIndicator(indicator_code=d["indicator_code"], created_by=user.username, updated_by=user.username, **{f: d[f] for f in INDICATOR_FIELDS if f in d})
        db.add(row)
        action, before = "DASHBOARD_INDICATOR_CREATE", {}
    db.commit()
    clear_cache()
    write_audit(action, user=user, object_type="DashboardIndicator", object_id=row.indicator_code, detail=json.dumps({"old": before, "new": indicator_view(row)}, ensure_ascii=False, default=str)[:900])
    return row


def save_group(db: Session, user: User, d: dict, code: str | None = None) -> DashboardIndicatorGroup:
    if d.get("layout_mode", "GRID") not in LAYOUT_MODES:
        raise _bad("layout_mode phải là GRID, STACK hoặc CUSTOM")
    if code:
        row = db.query(DashboardIndicatorGroup).filter(DashboardIndicatorGroup.group_code == code).first()
        if row is None:
            raise HTTPException(404, "Không có nhóm này")
        for f in ("group_name", "description", "default_enabled", "display_order", "layout_mode", "collapsible", "is_active"):
            if f in d:
                setattr(row, f, d[f])
        row.updated_by, row.updated_at = user.username, utcnow()
        action = "DASHBOARD_GROUP_UPDATE"
    else:
        if not d.get("group_code") or not d.get("group_name"):
            raise _bad("Cần mã và tên nhóm")
        if db.query(DashboardIndicatorGroup).filter(DashboardIndicatorGroup.group_code == d["group_code"]).first():
            raise HTTPException(409, f"Mã nhóm '{d['group_code']}' đã tồn tại")
        row = DashboardIndicatorGroup(group_code=d["group_code"], group_name=d["group_name"], description=d.get("description", ""), default_enabled=d.get("default_enabled", True),
                                      display_order=d.get("display_order", 0), layout_mode=d.get("layout_mode", "GRID"), collapsible=d.get("collapsible", False),
                                      created_by=user.username, updated_by=user.username)
        db.add(row)
        action = "DASHBOARD_GROUP_CREATE"
    db.commit()
    clear_cache()
    write_audit(action, user=user, object_type="DashboardIndicatorGroup", object_id=row.group_code, detail=json.dumps(group_view(row), ensure_ascii=False)[:600])
    return row


# ------------------------------------------------------------------ bố cục
def _validate_items(db: Session, items: list[dict], sections_mode: bool = False) -> None:
    seen = set()
    inds = {i.indicator_code: i for i in db.query(DashboardIndicator)}
    for it in items:
        code = it.get("indicator_code")
        if code not in inds:
            raise _bad(f"Chỉ số '{code}' không tồn tại")
        if code in seen and not sections_mode:  # Layout Designer cho Duplicate widget (cùng chỉ số, khác cấu hình)
            raise _bad(f"Chỉ số '{code}' xuất hiện hai lần trong cùng bố cục")
        seen.add(code)
        if sections_mode:
            if it.get("is_visible", True) and not inds[code].is_active:
                raise _bad(f"Chỉ số '{code}' đang bị vô hiệu hóa — không thể hiển thị trong bố cục mới")
            if not isinstance(it.get("config_override_json", {}), dict):
                raise _bad("config_override_json phải là đối tượng JSON")
            continue
        if it.get("section", "MAIN") not in SECTIONS:
            raise _bad(f"section '{it.get('section')}' không hợp lệ")
        x, w, y, h = int(it.get("grid_x", 0)), int(it.get("width", 1)), int(it.get("grid_y", 0)), int(it.get("height", 1))
        if x < 0 or y < 0 or w < 1 or h < 1 or x + w > GRID_COLUMNS:
            raise _bad(f"Vị trí của '{code}' vượt lưới {GRID_COLUMNS} cột (x={x}, w={w})")
        if it.get("is_visible", True) and not inds[code].is_active:
            raise _bad(f"Chỉ số '{code}' đang bị vô hiệu hóa — không thể hiển thị trong bố cục mới")
        if not isinstance(it.get("config_override_json", {}), dict):
            raise _bad("config_override_json phải là đối tượng JSON")


def find_overlaps(items: list[dict]) -> list[tuple[str, str]]:
    vis = [i for i in items if i.get("is_visible", True)]
    out = []
    for a in range(len(vis)):
        for b in range(a + 1, len(vis)):
            p, q = vis[a], vis[b]
            if p["grid_x"] < q["grid_x"] + q["width"] and q["grid_x"] < p["grid_x"] + p["width"] and p["grid_y"] < q["grid_y"] + q["height"] and q["grid_y"] < p["grid_y"] + p["height"]:
                out.append((p["indicator_code"], q["indicator_code"]))
    return out


def _validate_sections(sections: list[dict], items: list[dict]) -> None:
    refs = set()
    for s_ in sections:
        preset = s_.get("preset", "100")
        if preset == CUSTOM_PRESET:
            spans = s_.get("custom_spans") or []
            if len(spans) < 1 or len(spans) > 6:
                raise _bad("Tùy chỉnh %: cần từ 1 đến 6 cột")
            if any(not isinstance(x, (int, float)) or x <= 0 for x in spans):
                raise _bad("Tùy chỉnh %: mỗi cột phải là số dương")
            total = sum(spans)
            if not 90 <= total <= 110:
                raise _bad(f"Tùy chỉnh %: tổng các cột phải khoảng 100% (hiện {total:.0f}%)")
        elif preset not in SECTION_PRESETS:
            raise _bad(f"preset '{preset}' không hợp lệ (chọn: {', '.join(SECTION_PRESETS)}, {CUSTOM_PRESET})")
        ref = str(s_.get("ref", ""))
        if not ref or ref in refs:
            raise _bad("Mỗi Section cần một ref duy nhất")
        refs.add(ref)
    for it in items:
        if str(it.get("section_ref", "")) not in refs:
            raise _bad(f"Widget '{it.get('indicator_code')}' chưa thuộc Section nào")


def _replace_sections_items(db: Session, layout: DashboardLayout, sections: list[dict], items: list[dict]) -> None:
    """Ghi Section + widget. Vị trí lưới cũ (grid_x/width/grid_y/height) được suy ra từ preset để mọi nơi vẫn đọc được."""
    db.query(DashboardLayoutItem).filter(DashboardLayoutItem.layout_id == layout.id).delete()
    db.query(DashboardLayoutSection).filter(DashboardLayoutSection.layout_id == layout.id).delete()
    by_ref: dict[str, tuple[DashboardLayoutSection, int]] = {}
    for n, s_ in enumerate(sections, start=1):
        row = DashboardLayoutSection(layout_id=layout.id, order_no=n, title=s_.get("title", "") or "", preset=s_.get("preset", "100"),
                                    custom_spans=(s_.get("custom_spans") if s_.get("preset") == CUSTOM_PRESET else None), is_visible=bool(s_.get("is_visible", True)))
        db.add(row)
        by_ref[str(s_["ref"])] = (row, n)
    db.flush()
    rank: dict[tuple[str, int], int] = {}
    for n, it in enumerate(items, start=1):
        row, sec_idx = by_ref[str(it["section_ref"])]
        spans = section_spans(row.preset, row.custom_spans)
        col = max(0, min(int(it.get("column_no", 0)), len(spans) - 1))
        r = rank.get((str(it["section_ref"]), col), 0)
        rank[(str(it["section_ref"]), col)] = r + 1
        db.add(DashboardLayoutItem(
            layout_id=layout.id, indicator_code=it["indicator_code"], section="MAIN", grid_x=sum(spans[:col]), grid_y=sec_idx * 50 + r * 5, width=spans[col], height=5,
            order_no=n, is_visible=bool(it.get("is_visible", True)), collapsed=bool(it.get("collapsed", False)), config_override_json=it.get("config_override_json") or {},
            section_id=row.id, column_no=col,
        ))


def _replace_items(db: Session, layout: DashboardLayout, items: list[dict]) -> None:
    db.query(DashboardLayoutItem).filter(DashboardLayoutItem.layout_id == layout.id).delete()
    db.query(DashboardLayoutSection).filter(DashboardLayoutSection.layout_id == layout.id).delete()
    for n, it in enumerate(items, start=1):
        db.add(DashboardLayoutItem(
            layout_id=layout.id, indicator_code=it["indicator_code"], section=it.get("section", "MAIN"), grid_x=int(it.get("grid_x", 0)), grid_y=int(it.get("grid_y", 0)),
            width=int(it.get("width", 4)), height=int(it.get("height", 3)), order_no=int(it.get("order_no", n)), is_visible=bool(it.get("is_visible", True)),
            collapsed=bool(it.get("collapsed", False)), config_override_json=it.get("config_override_json") or {},
        ))


def create_layout(db: Session, user: User, d: dict) -> DashboardLayout:
    code = (d.get("layout_code") or "").strip().upper()
    if not code or not d.get("layout_name"):
        raise _bad("Cần mã và tên bố cục")
    if d.get("scope_type", "COMPANY") not in LAYOUT_SCOPES:
        raise _bad("scope_type phải là COMPANY hoặc FACTORY")
    last = db.query(DashboardLayout).filter(DashboardLayout.layout_code == code).order_by(DashboardLayout.version.desc()).first()
    layout = DashboardLayout(layout_code=code, layout_name=d["layout_name"], scope_type=d.get("scope_type", "COMPANY"), scope_value=d.get("scope_value", ""),
                             version=(last.version + 1) if last else 1, status="DRAFT", is_default=d.get("is_default", True), description=d.get("description", ""), created_by=user.username)
    db.add(layout)
    db.flush()
    items = d.get("items")
    if d.get("sections") is not None:
        _validate_items(db, items or [], True)
        _validate_sections(d["sections"], items or [])
        _replace_sections_items(db, layout, d["sections"], items or [])
    else:
        if items is None:  # bố cục mới: mỗi chỉ số default_enabled một Section 100%
            inds = list(db.query(DashboardIndicator).filter(DashboardIndicator.is_active.is_(True), DashboardIndicator.default_enabled.is_(True)).order_by(DashboardIndicator.display_order))
            secs = [{"ref": str(n), "title": i.indicator_name, "preset": "100"} for n, i in enumerate(inds)]
            its = [{"indicator_code": i.indicator_code, "section_ref": str(n), "column_no": 0} for n, i in enumerate(inds)]
            _replace_sections_items(db, layout, secs, its)
        else:
            _validate_items(db, items)
            _replace_items(db, layout, items)
    db.commit()
    write_audit("DASHBOARD_LAYOUT_CREATE", user=user, object_type="DashboardLayout", object_id=f"{layout.layout_code}.v{layout.version}", detail=layout.layout_name)
    return layout


def get_layout(db: Session, layout_id: int) -> DashboardLayout:
    l = db.get(DashboardLayout, layout_id)
    if l is None:
        raise HTTPException(404, "Không tìm thấy bố cục")
    return l


def clone_layout(db: Session, user: User, layout_id: int) -> DashboardLayout:
    src = get_layout(db, layout_id)
    if db.query(DashboardLayout).filter(DashboardLayout.layout_code == src.layout_code, DashboardLayout.status == "DRAFT").first():
        raise HTTPException(409, "Bố cục này đã có bản nháp — hãy sửa bản nháp đó")
    rows = db.query(DashboardLayoutItem).filter(DashboardLayoutItem.layout_id == src.id).order_by(DashboardLayoutItem.order_no, DashboardLayoutItem.id).all()
    base = {"layout_code": src.layout_code, "layout_name": src.layout_name, "scope_type": src.scope_type, "scope_value": src.scope_value, "is_default": src.is_default, "description": src.description}
    secs = _sections(db, src.id)
    if secs:
        items = [{**item_view(i), "section_ref": str(i.section_id)} for i in rows]
        return create_layout(db, user, {**base, "sections": [{"ref": str(x.id), "title": x.title, "preset": x.preset, "custom_spans": x.custom_spans, "is_visible": x.is_visible} for x in secs], "items": items})
    return create_layout(db, user, {**base, "items": [item_view(i) for i in rows]})


def update_layout(db: Session, user: User, layout_id: int, d: dict) -> DashboardLayout:
    l = get_layout(db, layout_id)
    if l.status != "DRAFT":
        raise HTTPException(409, f"Bố cục {l.status} là bất biến — hãy Clone thành bản nháp để chỉnh sửa")
    for f in ("layout_name", "description", "is_default"):
        if f in d:
            setattr(l, f, d[f])
    if "scope_type" in d:
        if d["scope_type"] not in LAYOUT_SCOPES:
            raise _bad("scope_type phải là COMPANY hoặc FACTORY")
        l.scope_type = d["scope_type"]
    if "scope_value" in d:
        l.scope_value = d["scope_value"] or ""
    if d.get("sections") is not None:
        _validate_items(db, d.get("items") or [], True)
        _validate_sections(d["sections"], d.get("items") or [])
        _replace_sections_items(db, l, d["sections"], d.get("items") or [])
    elif "items" in d:
        _validate_items(db, d["items"])
        _replace_items(db, l, d["items"])
    db.commit()
    write_audit("DASHBOARD_LAYOUT_UPDATE", user=user, object_type="DashboardLayout", object_id=f"{l.layout_code}.v{l.version}", detail=f"{len(d.get('items') or [])} ô")
    return l


def publish_layout(db: Session, user: User, layout_id: int) -> DashboardLayout:
    l = get_layout(db, layout_id)
    if l.status != "DRAFT":
        raise HTTPException(409, f"Chỉ Publish được bản DRAFT (hiện là {l.status})")
    items = [item_view(i) for i in db.query(DashboardLayoutItem).filter(DashboardLayoutItem.layout_id == l.id)]
    sectioned = bool(_sections(db, l.id))
    _validate_items(db, items, sectioned)
    if not [i for i in items if i["is_visible"]]:
        raise _bad("Bố cục phải có ít nhất một chỉ số hiển thị")
    overlaps = [] if sectioned else find_overlaps(items)
    if overlaps:
        raise _bad("Các ô bị chồng lấn: " + ", ".join(f"{a} ↔ {b}" for a, b in overlaps[:5]))
    q = db.query(DashboardLayout).filter(DashboardLayout.status == "PUBLISHED", DashboardLayout.id != l.id)
    for old in q:
        same_family = old.layout_code == l.layout_code
        same_default = l.is_default and old.is_default and old.scope_type == l.scope_type and old.scope_value == l.scope_value
        if same_family or same_default:
            old.status, old.retired_at = "RETIRED", utcnow()
    l.status, l.published_by, l.published_at = "PUBLISHED", user.username, utcnow()
    db.commit()
    clear_cache()
    write_audit("DASHBOARD_LAYOUT_PUBLISH", user=user, object_type="DashboardLayout", object_id=f"{l.layout_code}.v{l.version}", detail=l.layout_name)
    return l


def retire_layout(db: Session, user: User, layout_id: int) -> DashboardLayout:
    l = get_layout(db, layout_id)
    if l.status != "PUBLISHED":
        raise HTTPException(409, "Chỉ Retire được bố cục đang PUBLISHED")
    others = db.query(DashboardLayout).filter(DashboardLayout.status == "PUBLISHED", DashboardLayout.id != l.id, DashboardLayout.is_default.is_(True),
                                               DashboardLayout.scope_type == l.scope_type).count()
    if l.is_default and others == 0:
        raise HTTPException(409, "Đây là bố cục mặc định duy nhất của phạm vi này — hãy Publish bản thay thế trước khi Retire")
    l.status, l.retired_at = "RETIRED", utcnow()
    db.commit()
    clear_cache()
    write_audit("DASHBOARD_LAYOUT_RETIRE", user=user, object_type="DashboardLayout", object_id=f"{l.layout_code}.v{l.version}", detail=l.layout_name)
    return l


def resolve_layout(db: Session, scope: str) -> DashboardLayout | None:
    """Corporate (TONG) -> bố cục COMPANY. Xí nghiệp -> FACTORY theo mã XN, rồi FACTORY mặc định, rồi COMPANY mặc định."""
    base = db.query(DashboardLayout).filter(DashboardLayout.status == "PUBLISHED", DashboardLayout.is_default.is_(True))
    if scope.upper() == "TONG":
        return base.filter(DashboardLayout.scope_type == "COMPANY").order_by(DashboardLayout.published_at.desc()).first()
    specific = base.filter(DashboardLayout.scope_type == "FACTORY", DashboardLayout.scope_value == scope.upper()).order_by(DashboardLayout.published_at.desc()).first()
    if specific:
        return specific
    generic = base.filter(DashboardLayout.scope_type == "FACTORY", DashboardLayout.scope_value == "").order_by(DashboardLayout.published_at.desc()).first()
    return generic or base.filter(DashboardLayout.scope_type == "COMPANY").order_by(DashboardLayout.published_at.desc()).first()


# ------------------------------------------------------------------ test rule
def test_rule(db: Session, user: User, rule_code: str, scope: str = "TONG", month: str | None = None) -> dict:
    reg = db.query(DashboardRuleRegistry).filter(DashboardRuleRegistry.rule_code == rule_code).first()
    if reg is None or rule_code not in RULES:
        raise HTTPException(404, "Rule chưa được đăng ký")
    ctx = DashboardContext(db=db, scope=scope, month=month, user=user).prepare()
    out = execute_rule(rule_code, ctx)
    reg.last_test = {"at": datetime.now(timezone.utc).isoformat(), "by": user.username, "status": out["status"], "duration_ms": out["meta"].get("duration_ms", 0), "scope": scope}
    db.commit()
    write_audit("DASHBOARD_RULE_TEST", user=user, object_type="DashboardRuleRegistry", object_id=rule_code, result=out["status"], detail=f"scope={scope}")
    return out


# ------------------------------------------------------------------ runtime
def _merge_cfg(base: dict, override: dict) -> dict:
    return {**(base or {}), **(override or {})}


def _run_indicator(db: Session, user: User | None, ind: DashboardIndicator, item: DashboardLayoutItem, scope: str, month: str | None, period: str) -> dict:
    cfg = _merge_cfg(ind.config_json, item.config_override_json)
    ttl = int(cfg.get("cache_seconds", 30 if ind.refresh_mode == "CACHED" else 0) or 0) if ind.refresh_mode == "CACHED" else 0
    key = (ind.indicator_code, RULES[ind.rule_code].version if ind.rule_code in RULES else "", scope, month or "", period, json.dumps(cfg, sort_keys=True, default=str))
    now = time.monotonic()
    if ttl and key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    try:
        hours = float(ind.data_freshness_requirement) if ind.data_freshness_requirement else None
    except ValueError:
        hours = None
    ctx = DashboardContext(db=db, scope=scope, month=month, period=period, user=user, indicator_config=cfg, layout_config_override=item.config_override_json or {}).prepare()
    out = execute_rule(ind.rule_code, ctx, hours)
    if ttl and out["status"] != "ERROR":
        _cache[key] = (now, out)
    return out


def build_runtime(db: Session, user: User | None, scope: str = "TONG", month: str | None = None, period: str = "MONTH", layout_id: int | None = None) -> dict:
    factories, is_total = svc.scope_factories(db, scope)  # 404 nếu XN không tồn tại
    layout = get_layout(db, layout_id) if layout_id else resolve_layout(db, scope)
    today = svc.today_local()
    header = {
        "scope": "TONG" if is_total else factories[0].code, "scope_name": "Tổng công ty" if is_total else factories[0].name, "today": today.isoformat(),
        "sync": {"revenue": svc.sync_brief(svc.last_sync(db, "EGMF_REVENUE")), "plan": svc.sync_brief(svc.last_sync(db, "PLAN_EXCEL"))},
    }
    if layout is None:
        return {"layout": None, "header": header, "items": [], "message": "Chưa có bố cục Dashboard nào được Publish"}
    view = "TONG" if is_total else "FACTORY"
    inds = {i.indicator_code: i for i in db.query(DashboardIndicator)}
    groups = {g.group_code: g for g in db.query(DashboardIndicatorGroup)}
    items_out = []
    rows = db.query(DashboardLayoutItem).filter(DashboardLayoutItem.layout_id == layout.id).order_by(DashboardLayoutItem.order_no, DashboardLayoutItem.id).all()
    for it in rows:
        ind = inds.get(it.indicator_code)
        if ind is None or not it.is_visible or not ind.is_active:
            continue
        g = groups.get(ind.group_code)
        if g is not None and not g.is_active:
            continue
        if (ind.default_scope == "COMPANY" and view != "TONG") or (ind.default_scope == "FACTORY" and view == "TONG"):
            continue
        data = _run_indicator(db, user, ind, it, scope, month, period)
        items_out.append({
            "indicator": {**indicator_view(ind), "group_name": g.group_name if g else ind.group_code, "config_json": _merge_cfg(ind.config_json, it.config_override_json)},
            "position": {"section": it.section, "x": it.grid_x, "y": it.grid_y, "w": it.width, "h": it.height, "order": it.order_no, "collapsed": it.collapsed},
            "item_id": it.id, "section_id": it.section_id, "column_no": it.column_no,
            "data": data,
        })
    first_rev = next((i["data"] for i in items_out if i["indicator"]["rule_code"] == "REVENUE_EXECUTIVE_SUMMARY" and i["data"].get("payload")), None)
    header["month"] = (first_rev or {}).get("payload", {}).get("month") or month or f"{today.year}-{today.month:02d}"
    header["has_demo"] = bool(first_rev and first_rev["payload"].get("has_demo"))
    secs = [section_view(x) for x in _sections(db, layout.id) if x.is_visible]
    return {"layout": {"id": layout.id, "layout_code": layout.layout_code, "version": layout.version, "status": layout.status, "layout_name": layout.layout_name,
                       "grid_columns": GRID_COLUMNS}, "header": header, "items": items_out, "sections": secs}


# ------------------------------------------------------------------ chuyển bố cục lưới cũ sang Section
def _band_split(rows: list[DashboardLayoutItem]) -> list[list[DashboardLayoutItem]]:
    """Tách các ô thành từng 'dải' ngang: ranh giới y mà không ô nào cắt qua."""
    rows = sorted(rows, key=lambda r: (r.grid_y, r.grid_x))
    bands: list[list[DashboardLayoutItem]] = []
    end = None
    for r in rows:
        if not bands or (end is not None and r.grid_y >= end):
            bands.append([])
            end = None
        bands[-1].append(r)
        end = max(end or 0, r.grid_y + r.height)
    return bands


def migrate_layouts_to_sections(db: Session) -> int:
    """Idempotent: bố cục còn ở dạng lưới tự do (chưa có Section) được nhóm thành Section theo dải và cột; dải không khớp preset nào thì mỗi ô một Section 100%."""
    preset_by_spans = {tuple(v): k for k, v in SECTION_PRESETS.items()}
    converted = 0
    for l in db.query(DashboardLayout).all():
        if _sections(db, l.id):
            continue
        rows = db.query(DashboardLayoutItem).filter(DashboardLayoutItem.layout_id == l.id).order_by(DashboardLayoutItem.order_no, DashboardLayoutItem.id).all()
        if not rows:
            continue
        secs, items, n = [], [], 0
        ind_name = {i.indicator_code: i.indicator_name for i in db.query(DashboardIndicator)}
        for band in _band_split(rows):
            cols: dict[tuple[int, int], list[DashboardLayoutItem]] = {}
            for r in band:
                cols.setdefault((r.grid_x, r.width), []).append(r)
            keys = sorted(cols)
            contiguous = all(keys[i][0] + keys[i][1] == keys[i + 1][0] for i in range(len(keys) - 1)) and keys[0][0] == 0 and keys[-1][0] + keys[-1][1] == GRID_COLUMNS
            preset = preset_by_spans.get(tuple(w for _x, w in keys)) if contiguous else None
            lone = {(0, 8): ("66_34", 0), (8, 4): ("66_34", 1), (0, 6): ("50_50", 0), (6, 6): ("50_50", 1), (0, 4): ("34_66", 0), (4, 8): ("34_66", 1)}
            if not preset and len(keys) == 1 and keys[0] in lone:  # một cột lệch (VD cột chính 8/12 của bố cục cũ): giữ đúng vị trí, cột còn lại để trống
                preset, only_col = lone[keys[0]]
                secs.append({"ref": str(n), "title": "", "preset": preset})
                for r in sorted(band, key=lambda r: (r.grid_y, r.order_no)):
                    items.append({"indicator_code": r.indicator_code, "section_ref": str(n), "column_no": only_col, "is_visible": r.is_visible, "collapsed": r.collapsed, "config_override_json": r.config_override_json or {}})
                n += 1
                continue
            if preset:
                secs.append({"ref": str(n), "title": "", "preset": preset})
                for ci, key in enumerate(keys):
                    for r in sorted(cols[key], key=lambda r: (r.grid_y, r.order_no)):
                        items.append({"indicator_code": r.indicator_code, "section_ref": str(n), "column_no": ci, "is_visible": r.is_visible, "collapsed": r.collapsed, "config_override_json": r.config_override_json or {}})
                n += 1
            else:
                for r in sorted(band, key=lambda r: (r.grid_y, r.grid_x)):
                    secs.append({"ref": str(n), "title": ind_name.get(r.indicator_code, ""), "preset": "100"})
                    items.append({"indicator_code": r.indicator_code, "section_ref": str(n), "column_no": 0, "is_visible": r.is_visible, "collapsed": r.collapsed, "config_override_json": r.config_override_json or {}})
                    n += 1
        _replace_sections_items(db, l, secs, items)
        converted += 1
    if converted:
        db.commit()
        clear_cache()
    return converted
