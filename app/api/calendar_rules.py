from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import User
from app.models.planning import CalendarDayType, WorkingCalendarRule
from app.services import calendar_types as ct
from app.services import planning_service as svc
from app.services.audit import write_audit
from app.services.calendar import CalendarResolver

router = APIRouter(prefix="/planning/calendar", tags=["calendar"])
View = Depends(require_perm("calendar.view"))
Manage = Depends(require_perm("calendar.manage"))


# ------------------------------------------------------------------ danh mục loại ngày (công ty định nghĩa; XN/chuyền dùng lại)
class TypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    effect: str = Field(pattern="^(OFF|WORKING|OVERTIME|CHOICE)$")
    recurrence: str = Field("ANY", pattern="^(WEEKLY|DATE|ANY)$")
    color: str = "#94a3b8"


class TypeUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    color: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


@router.get("/types")
def list_types(include_inactive: bool = True, db: Session = Depends(get_db), _: User = View):
    return [ct.type_view(t) for t in ct.list_types(db, only_active=not include_inactive)]


@router.post("/types/templates")
def create_templates(db: Session = Depends(get_db), user: User = Manage):
    """Người dùng chủ động tạo bộ loại ngày mẫu (Nghỉ hàng tuần, Nghỉ Tết, Nghỉ lễ khác, Nghỉ khác, Ngoại lệ, Tăng ca) — không tự nạp sẵn."""
    n = ct.create_templates(db, user.username)
    write_audit("CALENDAR_TYPE", user=user, object_type="CalendarDayType", object_id="templates", detail=f"tạo {n} loại mẫu")
    return {"created": n, "types": [ct.type_view(t) for t in ct.list_types(db)]}


@router.post("/types")
def create_type(body: TypeCreate, db: Session = Depends(get_db), user: User = Manage):
    t = ct.create_type(db, body.name, body.effect, body.recurrence, body.color, user.username)
    write_audit("CALENDAR_TYPE", user=user, object_type="CalendarDayType", object_id=t.code, detail=f"create {t.name} ({t.effect}/{t.recurrence})")
    return ct.type_view(t)


@router.put("/types/{code}")
def update_type(code: str, body: TypeUpdate, db: Session = Depends(get_db), user: User = Manage):
    t = ct.update_type(db, code, body.model_dump(exclude_none=True), user.username)
    write_audit("CALENDAR_TYPE", user=user, object_type="CalendarDayType", object_id=code, detail=f"update {body.model_dump(exclude_none=True)}")
    return ct.type_view(t)


@router.delete("/types/{code}")
def delete_type(code: str, db: Session = Depends(get_db), user: User = Manage):
    ct.delete_type(db, code)
    write_audit("CALENDAR_TYPE", user=user, object_type="CalendarDayType", object_id=code, detail="delete")
    return {"deleted": True}


# ------------------------------------------------------------------ quy tắc
class RuleBody(BaseModel):
    scope_type: str = Field(pattern="^(COMPANY|XN|LINE)$")
    scope_key: str = ""
    day_type: str = Field(min_length=1, max_length=20)
    effect: str | None = Field(None, pattern="^(OFF|WORKING|OVERTIME)$")  # chỉ dùng cho loại "chọn theo từng đăng ký" (Ngoại lệ)
    repeat: str | None = Field(None, pattern="^(NONE|WEEKLY|MONTHLY|YEARLY)$")  # NONE = ngày / khoảng ngày; bỏ trống thì suy ra (có weekday -> WEEKLY)
    weekday: int | None = Field(None, ge=0, le=6)
    month: int | None = Field(None, ge=1, le=12)
    month_day: int | None = Field(None, ge=1, le=31)
    rule_date: date | None = None
    rule_end_date: date | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    note: str = Field("", max_length=200)


def _rule_out(r: WorkingCalendarRule) -> dict:
    from app.services.calendar import RULE_TYPES, kind_of

    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {"id": r.id, "scope_type": r.scope_type, "scope_key": r.scope_key, "rule_type": r.rule_type, "repeat": "NONE" if kind_of(r.rule_type) == "DATE" else kind_of(r.rule_type), "effect": RULE_TYPES[r.rule_type][0],
            "day_type": r.day_type, "weekday": r.weekday, "month": r.month, "month_day": r.month_day, "rule_date": iso(r.rule_date), "rule_end_date": iso(r.rule_end_date),
            "valid_from": iso(r.valid_from), "valid_to": iso(r.valid_to), "note": r.note, "created_by": r.created_by}


@router.get("")
def list_rules(db: Session = Depends(get_db), _: User = View):
    rules = db.query(WorkingCalendarRule).order_by(WorkingCalendarRule.scope_type, WorkingCalendarRule.scope_key, WorkingCalendarRule.rule_date, WorkingCalendarRule.id).all()
    return [_rule_out(r) for r in rules]


@router.post("")
def add_rule(body: RuleBody, db: Session = Depends(get_db), user: User = Manage):
    t = db.query(CalendarDayType).filter(CalendarDayType.code == body.day_type).first()
    if t is None:
        raise HTTPException(400, "Loại ngày không tồn tại trong danh mục")
    repeat = body.repeat or ("WEEKLY" if body.weekday is not None else "NONE")
    fields = ct.normalize_rule(t, repeat, body.weekday, body.month, body.month_day, body.rule_date, body.rule_end_date, body.valid_from, body.valid_to, body.effect)
    scope_key = body.scope_key
    if body.scope_type == "COMPANY":
        scope_key = ""
    elif body.scope_type == "XN" and scope_key not in svc.factory_codes(db):
        raise HTTPException(400, "Xí nghiệp không hợp lệ")
    elif body.scope_type == "LINE" and ":" not in scope_key:
        raise HTTPException(400, "Scope LINE có dạng 'XN1:07'")
    rule = WorkingCalendarRule(scope_type=body.scope_type, scope_key=scope_key, day_type=t.code, note=body.note, created_by=user.username, **fields)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    write_audit("CALENDAR_CHANGE", user=user, object_type="CalendarRule", object_id=str(rule.id),
                detail=f"add {rule.scope_type}:{rule.scope_key} {t.name} {repeat} {rule.rule_date or rule.weekday or rule.month_day}{('→' + str(rule.rule_end_date)) if rule.rule_end_date else ''}")
    return _rule_out(rule)


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Manage):
    rule = db.get(WorkingCalendarRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Không tìm thấy quy tắc")
    db.delete(rule)
    db.commit()
    write_audit("CALENDAR_CHANGE", user=user, object_type="CalendarRule", object_id=str(rule_id), detail="delete")
    return {"deleted": True}


@router.get("/resolve")
def resolve(date_from: date, days: int = Query(31, ge=1, le=366), xn: str | None = None, line: str | None = None, db: Session = Depends(get_db), _: User = View):
    """Từng ngày: trạng thái hiệu lực + loại ngày (tên/màu) + nguồn (công ty / XN / chuyền) + kế thừa hay ghi đè."""
    cal: CalendarResolver = svc.load_resolver(db)
    types = {t.code: t for t in ct.list_types(db)}
    out = []
    for i in range(days):
        d = date_from + timedelta(days=i)
        e = cal.explain(d, xn, line)
        t = types.get(e["day_type"])
        out.append({"date": d.isoformat(), **e, "day_type_name": t.name if t else "", "color": t.color if t else ""})
    return out
