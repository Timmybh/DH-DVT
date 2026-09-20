from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.dashboard_rules import RULES, DashboardContext, execute_rule
from app.db.session import get_db
from app.models.core import User
from app.models.dashboard_cfg import DashboardIndicator, DashboardIndicatorGroup, DashboardLayout, DashboardRuleRegistry
from app.services import dashboard_meta as meta

router = APIRouter(prefix="/admin/dashboard", tags=["dashboard-config"])

View = Depends(require_perm("dashboard.config_view"))
Manage = Depends(require_perm("dashboard.config_manage"))
LayoutManage = Depends(require_perm("dashboard.layout_manage"))
RuleTest = Depends(require_perm("dashboard.rule_test"))
Publish = Depends(require_perm("dashboard.publish"))


@router.get("/options")
def options(_: User = View):
    """Danh sách giá trị hợp lệ để UI dựng ô chọn (không hard-code phía frontend)."""
    return {
        "display_types": list(meta.DISPLAY_TYPES), "scopes": list(meta.SCOPES), "drilldowns": list(meta.DRILLDOWNS), "refresh_modes": list(meta.REFRESH_MODES),
        "sections": list(meta.SECTIONS), "layout_modes": list(meta.LAYOUT_MODES), "layout_scopes": list(meta.LAYOUT_SCOPES), "grid_columns": meta.GRID_COLUMNS,
    }


# ------------------------------------------------------------------ nhóm
class GroupBody(BaseModel):
    group_code: str | None = Field(None, max_length=40)
    group_name: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=300)
    default_enabled: bool | None = None
    display_order: int | None = None
    layout_mode: str | None = None
    collapsible: bool | None = None
    is_active: bool | None = None


@router.get("/groups")
def list_groups(db: Session = Depends(get_db), _: User = View):
    return [meta.group_view(g) for g in db.query(DashboardIndicatorGroup).order_by(DashboardIndicatorGroup.display_order, DashboardIndicatorGroup.id)]


@router.post("/groups")
def create_group(body: GroupBody, db: Session = Depends(get_db), user: User = Manage):
    return meta.group_view(meta.save_group(db, user, body.model_dump(exclude_none=True)))


@router.put("/groups/{code}")
def update_group(code: str, body: GroupBody, db: Session = Depends(get_db), user: User = Manage):
    return meta.group_view(meta.save_group(db, user, body.model_dump(exclude_none=True), code))


# ------------------------------------------------------------------ chỉ số
class IndicatorBody(BaseModel):
    indicator_code: str | None = Field(None, max_length=60)
    indicator_name: str | None = Field(None, max_length=120)
    group_code: str | None = None
    description: str | None = Field(None, max_length=300)
    display_type: str | None = None
    rule_code: str | None = None
    data_source: str | None = Field(None, max_length=120)
    default_scope: str | None = None
    drilldown_type: str | None = None
    drilldown_target: str | None = Field(None, max_length=60)
    refresh_mode: str | None = None
    default_enabled: bool | None = None
    is_active: bool | None = None
    display_order: int | None = None
    owner: str | None = Field(None, max_length=100)
    data_freshness_requirement: str | None = Field(None, max_length=40)
    config_json: dict[str, Any] | None = None


def _get_indicator(db: Session, code: str) -> DashboardIndicator:
    row = db.query(DashboardIndicator).filter(DashboardIndicator.indicator_code == code).first()
    if row is None:
        raise HTTPException(404, "Không có chỉ số này")
    return row


@router.get("/indicators")
def list_indicators(db: Session = Depends(get_db), _: User = View):
    return [meta.indicator_view(i) for i in db.query(DashboardIndicator).order_by(DashboardIndicator.group_code, DashboardIndicator.display_order, DashboardIndicator.id)]


@router.post("/indicators")
def create_indicator(body: IndicatorBody, db: Session = Depends(get_db), user: User = Manage):
    d = {"description": "", "display_type": "CUSTOM_COMPONENT", "data_source": "", "default_scope": "BOTH", "drilldown_type": "NONE", "drilldown_target": "",
         "refresh_mode": "ON_LOAD", "default_enabled": True, "is_active": True, "display_order": 0, "owner": "", "data_freshness_requirement": "", "config_json": {},
         **body.model_dump(exclude_none=True)}
    return meta.indicator_view(meta.save_indicator(db, user, d))


@router.get("/indicators/{code}")
def get_indicator(code: str, db: Session = Depends(get_db), _: User = View):
    return meta.indicator_view(_get_indicator(db, code))


@router.put("/indicators/{code}")
def update_indicator(code: str, body: IndicatorBody, db: Session = Depends(get_db), user: User = Manage):
    d = body.model_dump(exclude_none=True)
    d.pop("indicator_code", None)
    return meta.indicator_view(meta.save_indicator(db, user, d, code))


class DuplicateBody(BaseModel):
    new_code: str = Field(..., max_length=60)


@router.post("/indicators/{code}/duplicate")
def duplicate_indicator(code: str, body: DuplicateBody, db: Session = Depends(get_db), user: User = Manage):
    src = meta.indicator_view(_get_indicator(db, code))
    src.pop("id")
    src.update(indicator_code=body.new_code.strip().upper(), indicator_name=src["indicator_name"] + " (bản sao)", is_active=False)
    return meta.indicator_view(meta.save_indicator(db, user, src))


class PreviewBody(BaseModel):
    scope: str = "TONG"
    month: str | None = None
    period: str = "MONTH"


def _preview(db: Session, user: User, ind: DashboardIndicator, body: PreviewBody) -> dict:
    ctx = DashboardContext(db=db, scope=body.scope, month=body.month, period=body.period, user=user, indicator_config=ind.config_json or {}).prepare()
    try:
        hours = float(ind.data_freshness_requirement) if ind.data_freshness_requirement else None
    except ValueError:
        hours = None
    return {"indicator": meta.indicator_view(ind), "data": execute_rule(ind.rule_code, ctx, hours)}


@router.post("/indicators/{code}/preview")
def preview_indicator(code: str, body: PreviewBody, db: Session = Depends(get_db), user: User = View):
    return _preview(db, user, _get_indicator(db, code), body)


@router.post("/indicators/{code}/test")
def test_indicator(code: str, body: PreviewBody, db: Session = Depends(get_db), user: User = RuleTest):
    ind = _get_indicator(db, code)
    out = meta.test_rule(db, user, ind.rule_code, body.scope, body.month)
    return {"indicator_code": code, "rule_code": ind.rule_code, "status": out["status"], "message": out.get("message", ""), "meta": out["meta"]}


# ------------------------------------------------------------------ rule registry (chỉ xem/test/bật-tắt; không thêm code)
@router.get("/rules")
def list_rules(db: Session = Depends(get_db), _: User = View):
    return [meta.rule_view(r) for r in db.query(DashboardRuleRegistry).order_by(DashboardRuleRegistry.rule_code)]


@router.get("/rules/{code}")
def get_rule(code: str, db: Session = Depends(get_db), _: User = View):
    r = db.query(DashboardRuleRegistry).filter(DashboardRuleRegistry.rule_code == code).first()
    if r is None:
        raise HTTPException(404, "Không có rule này")
    return meta.rule_view(r)


@router.post("/rules/{code}/test")
def test_rule(code: str, body: PreviewBody, db: Session = Depends(get_db), user: User = RuleTest):
    out = meta.test_rule(db, user, code, body.scope, body.month)
    return {"rule_code": code, "status": out["status"], "message": out.get("message", ""), "meta": out["meta"], "payload_keys": sorted((out.get("payload") or {}).keys()) if isinstance(out.get("payload"), dict) else []}


class RuleToggle(BaseModel):
    is_active: bool


@router.put("/rules/{code}")
def toggle_rule(code: str, body: RuleToggle, db: Session = Depends(get_db), user: User = Manage):
    r = db.query(DashboardRuleRegistry).filter(DashboardRuleRegistry.rule_code == code).first()
    if r is None or code not in RULES:
        raise HTTPException(404, "Rule chưa được đăng ký")
    r.is_active, r.updated_by = body.is_active, user.username
    db.commit()
    meta.clear_cache()
    return meta.rule_view(r)


# ------------------------------------------------------------------ bố cục
class LayoutItemBody(BaseModel):
    indicator_code: str
    section: str = "MAIN"
    grid_x: int = 0
    grid_y: int = 0
    width: int = 4
    height: int = 3
    order_no: int = 0
    is_visible: bool = True
    collapsed: bool = False
    config_override_json: dict[str, Any] = {}


class LayoutBody(BaseModel):
    layout_code: str | None = Field(None, max_length=60)
    layout_name: str | None = Field(None, max_length=120)
    scope_type: str | None = None
    scope_value: str | None = None
    is_default: bool | None = None
    description: str | None = Field(None, max_length=300)
    items: list[LayoutItemBody] | None = None


def _payload(body: LayoutBody) -> dict:
    d = body.model_dump(exclude_none=True)
    if body.items is not None:
        d["items"] = [i.model_dump() for i in body.items]
    return d


@router.get("/layouts")
def list_layouts(db: Session = Depends(get_db), _: User = View):
    rows = db.query(DashboardLayout).order_by(DashboardLayout.layout_code, DashboardLayout.version.desc()).all()
    return [meta.layout_view(db, l) for l in rows]


@router.post("/layouts")
def create_layout(body: LayoutBody, db: Session = Depends(get_db), user: User = LayoutManage):
    return meta.layout_view(db, meta.create_layout(db, user, _payload(body)), True)


@router.get("/layouts/{layout_id}")
def get_layout(layout_id: int, db: Session = Depends(get_db), _: User = View):
    return meta.layout_view(db, meta.get_layout(db, layout_id), True)


@router.post("/layouts/{layout_id}/clone")
def clone_layout(layout_id: int, db: Session = Depends(get_db), user: User = LayoutManage):
    return meta.layout_view(db, meta.clone_layout(db, user, layout_id), True)


@router.put("/layouts/{layout_id}")
def update_layout(layout_id: int, body: LayoutBody, db: Session = Depends(get_db), user: User = LayoutManage):
    return meta.layout_view(db, meta.update_layout(db, user, layout_id, _payload(body)), True)


@router.post("/layouts/{layout_id}/publish")
def publish_layout(layout_id: int, db: Session = Depends(get_db), user: User = Publish):
    return meta.layout_view(db, meta.publish_layout(db, user, layout_id), True)


@router.post("/layouts/{layout_id}/retire")
def retire_layout(layout_id: int, db: Session = Depends(get_db), user: User = Publish):
    return meta.layout_view(db, meta.retire_layout(db, user, layout_id), True)
