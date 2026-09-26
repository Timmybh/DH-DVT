"""Bảng giá (đơn giá công ty) theo mã hàng, USD/sản phẩm. Nền cho doanh thu theo tổ = sản lượng × đơn giá (Dashboard Trang 2).

Không ghi đè: đổi giá = thêm dòng mới với ngày hiệu lực mới; giá áp dụng cho ngày D là dòng ACTIVE có effective_from lớn nhất ≤ D.
"""

from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.resources import StylePrice, StyleSam
from app.services.audit import write_audit

CURRENCY = "USD"


def view(r: StylePrice, brand: str = "", effective_to: date | None = None) -> dict:
    return {"effective_to": effective_to.isoformat() if effective_to else None, "id": r.id, "style_cc": r.style_cc, "brand": brand, "unit_price": r.unit_price, "currency": r.currency, "effective_from": r.effective_from.isoformat(),
            "status": r.status, "source": r.source, "note": r.note, "updated_by": r.updated_by, "updated_at": r.updated_at.isoformat() if r.updated_at else None}


def price_on(db: Session, style: str, day: date) -> float | None:
    r = (db.query(StylePrice).filter(StylePrice.style_cc == style.strip().upper(), StylePrice.status == "ACTIVE", StylePrice.effective_from <= day)
         .order_by(StylePrice.effective_from.desc(), StylePrice.id.desc()).first())
    return r.unit_price if r else None


def create_price(db: Session, user, d: dict) -> StylePrice:
    style = str(d.get("style_cc") or "").strip().upper()
    if not style:
        raise HTTPException(422, "Cần mã hàng")
    price = d.get("unit_price")
    if price is None or not float(price) > 0:
        raise HTTPException(422, "Đơn giá phải > 0 (USD/sản phẩm)")
    if not d.get("effective_from"):
        raise HTTPException(422, "Cần ngày hiệu lực từ")
    dup = db.query(StylePrice).filter(StylePrice.style_cc == style, StylePrice.effective_from == d["effective_from"], StylePrice.status == "ACTIVE").first()
    if dup:
        raise HTTPException(409, f"Mã hàng {style} đã có giá hiệu lực từ {d['effective_from']} — chọn ngày hiệu lực khác hoặc Ngưng dòng cũ")
    row = StylePrice(style_cc=style, unit_price=round(float(price), 6), currency=CURRENCY, effective_from=d["effective_from"], source=d.get("source") or "MANUAL",
                     note=(d.get("note") or "")[:300], updated_by=user.username, updated_at=utcnow())
    db.add(row)
    db.commit()
    write_audit("STYLE_PRICE_CREATE", user=user, object_type="StylePrice", object_id=str(row.id), detail=f"{style} {row.unit_price} {CURRENCY} từ {row.effective_from}")
    return row


def set_status(db: Session, user, pid: int, active: bool) -> StylePrice:
    row = db.get(StylePrice, pid)
    if row is None:
        raise HTTPException(404, "Không tìm thấy dòng giá")
    if active and db.query(StylePrice).filter(StylePrice.style_cc == row.style_cc, StylePrice.effective_from == row.effective_from, StylePrice.status == "ACTIVE", StylePrice.id != row.id).first():
        raise HTTPException(409, "Đã có dòng giá áp dụng cùng ngày hiệu lực cho mã hàng này")
    row.status, row.updated_by, row.updated_at = ("ACTIVE" if active else "INACTIVE"), user.username, utcnow()
    db.commit()
    write_audit("STYLE_PRICE_STATUS", user=user, object_type="StylePrice", object_id=str(pid), detail=f"{row.style_cc} {row.status}")
    return row


def list_prices(db: Session, q: str | None, include_history: bool, limit: int = 3000) -> dict:
    brands = {s: b for s, b in db.query(StyleSam.style_cc, StyleSam.brand)}
    query = db.query(StylePrice)
    if q:
        like = f"%{q.strip()}%"
        matching = [s for s, b in brands.items() if q.strip().upper() in (b or "").upper()]
        query = query.filter(StylePrice.style_cc.ilike(like) | StylePrice.style_cc.in_(matching or [""]))
    rows = query.order_by(StylePrice.style_cc, StylePrice.effective_from.desc(), StylePrice.id.desc()).all()
    # Hiệu lực đến = ngày trước ngày hiệu lực của dòng ACTIVE kế tiếp cùng mã hàng (không có ⇒ đang áp dụng, chưa có ngày kết thúc)
    ends: dict[int, date] = {}
    by_style: dict[str, list[StylePrice]] = {}
    for r in db.query(StylePrice).filter(StylePrice.status == "ACTIVE"):
        by_style.setdefault(r.style_cc, []).append(r)
    for lst in by_style.values():
        lst.sort(key=lambda x: x.effective_from)
        for a, b in zip(lst, lst[1:]):
            if b.effective_from > a.effective_from:
                ends[a.id] = b.effective_from - timedelta(days=1)
    if not include_history:  # chỉ giá đang áp dụng hôm nay: mỗi mã hàng một dòng ACTIVE mới nhất có hiệu lực ≤ hôm nay
        today, seen, keep = date.today(), set(), []
        for r in rows:
            if r.status == "ACTIVE" and r.effective_from <= today and r.style_cc not in seen:
                seen.add(r.style_cc)
                keep.append(r)
        upcoming = [r for r in rows if r.status == "ACTIVE" and r.effective_from > today]
        rows = keep + upcoming
    return {"total": len(rows), "rows": [view(r, brands.get(r.style_cc, ""), ends.get(r.id)) for r in rows[:limit]]}
