"""Danh mục loại ngày của lịch làm việc + kiểm tra/chuẩn hóa quy tắc.

Công ty định nghĩa TÊN các loại ngày; xí nghiệp / chuyền dùng đúng danh mục này khi tạo quy tắc ghi đè. Hiệu lực (OFF/WORKING/OVERTIME) do loại ngày quyết định.
"""

import re
import unicodedata
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.planning import CalendarDayType, WorkingCalendarRule
from app.services.calendar import OFF, OVERTIME, WORKING, rule_type_for

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
CHOICE = "CHOICE"  # hiệu lực chọn theo TỪNG đăng ký (VD Ngoại lệ: có ngày làm việc, có ngày nghỉ)
EFFECTS = (OFF, WORKING, OVERTIME, CHOICE)
CHOICE_EFFECTS = (WORKING, OFF)
RECURRENCES = ("WEEKLY", "DATE", "ANY")
MAX_RANGE_DAYS = 366

DEFAULT_TYPES = [
    # code, tên, hiệu lực, kiểu lặp, màu
    ("WEEKLY_OFF", "Nghỉ hàng tuần", OFF, "WEEKLY", "#ef4444"),
    ("TET", "Nghỉ Tết", OFF, "DATE", "#b91c1c"),
    ("HOLIDAY", "Nghỉ lễ khác", OFF, "DATE", "#f97316"),
    ("OTHER_OFF", "Nghỉ khác", OFF, "DATE", "#a855f7"),
    ("EXCEPTION", "Ngoại lệ", CHOICE, "ANY", "#0ea5e9"),  # ngoại lệ so với lịch cấp trên: mỗi đăng ký chọn "Làm việc" hoặc "Nghỉ"
    ("OVERTIME", "Tăng ca", OVERTIME, "ANY", "#f59e0b"),
]
LEGACY_TYPE = {"WEEKLY_OFF": "WEEKLY_OFF", "DATE_OFF": "OTHER_OFF", "OVERTIME": "OVERTIME"}


def create_templates(db: Session, username: str) -> int:
    """Tạo (theo yêu cầu của người dùng) các loại ngày mẫu còn thiếu. Đây là loại thường: đổi tên/màu, tắt hoặc xóa được như mọi loại khác."""
    have = {t.code for t in db.query(CalendarDayType)}
    n = 0
    for i, (code, name, effect, rec, color) in enumerate(DEFAULT_TYPES, start=1):
        if code not in have:
            db.add(CalendarDayType(code=code, name=name, effect=effect, recurrence=rec, color=color, sort_order=i, is_system=False, updated_by=username))
            n += 1
    db.commit()
    backfill_rule_day_types(db)
    return n


def backfill_rule_day_types(db: Session) -> int:
    """Quy tắc cũ (chưa có loại ngày) -> loại mẫu tương ứng, CHỈ khi loại đó đã tồn tại: nghỉ hằng tuần => Nghỉ hàng tuần / nghỉ theo ngày => Nghỉ khác / làm thêm => Tăng ca."""
    codes = {t.code for t in db.query(CalendarDayType)}
    n = 0
    for r in db.query(WorkingCalendarRule).filter(WorkingCalendarRule.day_type == ""):
        code = LEGACY_TYPE.get(r.rule_type, "OTHER_OFF")
        if code in codes:
            r.day_type = code
            n += 1
    db.commit()
    return n


def slug_code(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", re.sub(r"[đĐ]", "d", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode())).strip("_").upper()
    return (s or "CUSTOM")[:20]


def type_view(t: CalendarDayType) -> dict:
    return {"code": t.code, "name": t.name, "effect": t.effect, "recurrence": t.recurrence, "color": t.color, "sort_order": t.sort_order, "is_system": t.is_system, "is_active": t.is_active}


def list_types(db: Session, only_active: bool = False) -> list[CalendarDayType]:
    q = db.query(CalendarDayType)
    if only_active:
        q = q.filter(CalendarDayType.is_active.is_(True))
    return q.order_by(CalendarDayType.sort_order, CalendarDayType.id).all()


def create_type(db: Session, name: str, effect: str, recurrence: str, color: str, username: str) -> CalendarDayType:
    name = name.strip()
    if not name or len(name) > 80:
        raise HTTPException(422, "Tên loại ngày 1–80 ký tự")
    if effect not in EFFECTS or recurrence not in RECURRENCES:
        raise HTTPException(422, "Hiệu lực hoặc kiểu lặp không hợp lệ")
    if not HEX.match(color):
        raise HTTPException(422, "Màu phải có dạng #RRGGBB")
    if any(t.name.strip().lower() == name.lower() for t in list_types(db)):
        raise HTTPException(409, "Đã có loại ngày cùng tên")
    base = slug_code(name)
    code, n = base, 2
    existing = {t.code for t in list_types(db)}
    while code in existing:
        code = f"{base[:17]}_{n}"
        n += 1
    order = max((t.sort_order for t in list_types(db)), default=0) + 1
    t = CalendarDayType(code=code, name=name, effect=effect, recurrence=recurrence, color=color.lower(), sort_order=order, is_system=False, updated_by=username)
    db.add(t)
    db.commit()
    return t


def update_type(db: Session, code: str, data: dict, username: str) -> CalendarDayType:
    t = db.query(CalendarDayType).filter(CalendarDayType.code == code).first()
    if t is None:
        raise HTTPException(404, "Không tìm thấy loại ngày")
    if "name" in data:
        name = str(data["name"]).strip()
        if not name or len(name) > 80:
            raise HTTPException(422, "Tên loại ngày 1–80 ký tự")
        if any(o.code != code and o.name.strip().lower() == name.lower() for o in list_types(db)):
            raise HTTPException(409, "Đã có loại ngày cùng tên")
        t.name = name
    if "color" in data:
        if not HEX.match(str(data["color"])):
            raise HTTPException(422, "Màu phải có dạng #RRGGBB")
        t.color = str(data["color"]).lower()
    if "sort_order" in data:
        t.sort_order = int(data["sort_order"])
    if "is_active" in data:
        t.is_active = bool(data["is_active"])
    t.updated_by, t.updated_at = username, utcnow()
    db.commit()
    return t


def delete_type(db: Session, code: str) -> None:
    t = db.query(CalendarDayType).filter(CalendarDayType.code == code).first()
    if t is None:
        raise HTTPException(404, "Không tìm thấy loại ngày")
    used = db.query(WorkingCalendarRule).filter(WorkingCalendarRule.day_type == code).count()
    if used:
        raise HTTPException(409, f"Loại ngày đang được dùng bởi {used} quy tắc — xóa các quy tắc đó trước")
    db.delete(t)
    db.commit()


def normalize_rule(t: CalendarDayType, repeat: str, weekday: int | None = None, month: int | None = None, month_day: int | None = None, rule_date: date | None = None,
                   end_date: date | None = None, valid_from: date | None = None, valid_to: date | None = None, effect: str | None = None) -> dict:
    """Kiểm tra một đăng ký theo loại ngày + kiểu (NONE = ngày/khoảng ngày, WEEKLY, MONTHLY, YEARLY) và trả các trường lưu DB.
    Mọi loại ngày đều đăng ký được theo ngày chi tiết lẫn kiểu lặp; `recurrence` của loại chỉ là gợi ý kiểu mặc định trên giao diện."""
    if not t.is_active:
        raise HTTPException(409, f"Loại ngày '{t.name}' đang tắt")
    if repeat not in ("NONE", "WEEKLY", "MONTHLY", "YEARLY"):
        raise HTTPException(422, "Kiểu đăng ký không hợp lệ")
    if t.effect == CHOICE:  # loại "chọn theo từng đăng ký": bắt buộc nêu Làm việc hay Nghỉ
        if effect not in CHOICE_EFFECTS:
            raise HTTPException(422, f"'{t.name}': chọn hiệu lực của đăng ký — Làm việc (WORKING) hoặc Nghỉ (OFF)")
        eff = effect
    else:
        if effect not in (None, t.effect):
            raise HTTPException(422, f"'{t.name}' có hiệu lực cố định {t.effect}")
        eff = t.effect
    out = {"weekday": None, "month": None, "month_day": None, "rule_date": None, "rule_end_date": None, "valid_from": None, "valid_to": None}
    if repeat == "NONE":
        if rule_date is None:
            raise HTTPException(422, "Cần chọn ngày (hoặc khoảng ngày)")
        if end_date is not None:
            if end_date < rule_date:
                raise HTTPException(422, "Ngày kết thúc phải sau hoặc bằng ngày bắt đầu")
            if (end_date - rule_date).days + 1 > MAX_RANGE_DAYS:
                raise HTTPException(422, f"Khoảng ngày tối đa {MAX_RANGE_DAYS} ngày")
        out.update(rule_date=rule_date, rule_end_date=end_date if end_date and end_date != rule_date else None)
        return {"rule_type": rule_type_for(eff, "DATE"), **out}
    if rule_date is not None or end_date is not None:
        raise HTTPException(422, "Quy tắc lặp không có ngày cụ thể — dùng giới hạn hiệu lực (từ ngày / đến ngày)")
    if repeat == "WEEKLY":
        if weekday is None or not 0 <= weekday <= 6:
            raise HTTPException(422, "Lặp hằng tuần cần chọn thứ (0=Thứ hai … 6=Chủ nhật)")
        out["weekday"] = weekday
    elif repeat == "MONTHLY":
        if month_day is None or not 1 <= month_day <= 31:
            raise HTTPException(422, "Lặp hằng tháng cần chọn ngày trong tháng (1–31)")
        out["month_day"] = month_day
    else:
        if month is None or not 1 <= month <= 12 or month_day is None or not 1 <= month_day <= 31:
            raise HTTPException(422, "Lặp hằng năm cần chọn tháng (1–12) và ngày (1–31)")
        if month_day > [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]:
            raise HTTPException(422, f"Tháng {month} không có ngày {month_day}")
        out.update(month=month, month_day=month_day)
    if valid_from and valid_to and valid_to < valid_from:
        raise HTTPException(422, "Giới hạn hiệu lực: đến ngày phải sau hoặc bằng từ ngày")
    out.update(valid_from=valid_from, valid_to=valid_to)
    return {"rule_type": rule_type_for(eff, repeat), **out}


def expand_range(start: date, end: date | None) -> list[date]:
    end = end or start
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
