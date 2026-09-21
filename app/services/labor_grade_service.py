"""Bậc năng suất lao động (Productivity Grade) và Cơ cấu lao động theo XN/chuyền (spec §4–5).

Cấp 1: danh mục bậc 1..10 với hệ số năng suất theo hiệu lực ngày (không hard-code trong engine, không xóa).
Cấp 2: số lao động theo từng XN/chuyền và từng bậc: Standard Labor = Σ headcount; Effective Equivalent = Σ headcount × factor; Weighted Factor = Equivalent / Standard.
Không ghi đè Standard Labor: sửa = tạo phiên bản mới, bản cũ RETIRED và khép hiệu lực.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.core import User
from app.models.resources import LaborStandard, LaborStandardGradeDetail, ProductivityGrade
from app.services.audit import write_audit

DEFAULT_FACTORS = {1: 0.50, 2: 0.55, 3: 0.60, 4: 0.65, 5: 0.70, 6: 0.75, 7: 0.80, 8: 0.85, 9: 0.90, 10: 1.00}


def seed_grades(db: Session) -> int:
    """Gieo mặc định PG01..PG10 (spec §4) khi bảng còn trống; không đụng dữ liệu người dùng đã có."""
    if db.query(func.count(ProductivityGrade.id)).scalar():
        return 0
    for g, f in DEFAULT_FACTORS.items():
        db.add(ProductivityGrade(grade=g, code=f"PG{g:02d}", name=f"Bậc {g}", productivity_factor=f, created_by="system"))
    db.commit()
    return len(DEFAULT_FACTORS)


def grade_view(g: ProductivityGrade) -> dict:
    return {"id": g.id, "grade": g.grade, "code": g.code, "name": g.name, "productivity_factor": g.productivity_factor, "effective_from": g.effective_from.isoformat() if g.effective_from else None,
            "effective_to": g.effective_to.isoformat() if g.effective_to else None, "status": g.status, "note": g.note, "created_by": g.created_by}


def factor_at(db_or_rows, grade: int, day: date) -> float | None:
    """Hệ số của bậc tại `day`: bản ACTIVE có hiệu lực, ưu tiên effective_from muộn nhất. `db_or_rows` là Session hoặc danh sách ProductivityGrade đã nạp."""
    rows = db_or_rows.query(ProductivityGrade).filter(ProductivityGrade.grade == grade, ProductivityGrade.status == "ACTIVE").all() if hasattr(db_or_rows, "query") else [r for r in db_or_rows if r.grade == grade and r.status == "ACTIVE"]
    ok = [r for r in rows if (r.effective_from is None or r.effective_from <= day) and (r.effective_to is None or r.effective_to >= day)]
    if not ok:
        return None
    return max(ok, key=lambda r: (r.effective_from or date.min, r.id)).productivity_factor


def _check_monotonic(db: Session, grade: int, factor: float, day: date) -> None:
    for other in range(1, 11):
        if other == grade:
            continue
        f = factor_at(db, other, day)
        if f is None:
            continue
        if (other < grade and f > factor) or (other > grade and f < factor):
            raise HTTPException(422, f"Bậc cao không được có hệ số thấp hơn bậc thấp (xung đột với bậc {other}: {f:.0%})")


def revise_grade(db: Session, user: User, grade: int, factor: float, effective_from: date, name: str | None = None, note: str | None = None) -> ProductivityGrade:
    """Đổi hệ số = tạo bản mới có hiệu lực từ ngày chỉ định; bản đang hiệu lực được khép lại (giữ lịch sử)."""
    if not 1 <= grade <= 10:
        raise HTTPException(422, "Bậc phải từ 1 đến 10")
    if not factor > 0:
        raise HTTPException(422, "Hệ số phải > 0")
    _check_monotonic(db, grade, factor, effective_from)
    cur = [r for r in db.query(ProductivityGrade).filter(ProductivityGrade.grade == grade, ProductivityGrade.status == "ACTIVE")]
    for r in cur:
        if r.effective_to is None or r.effective_to >= effective_from:
            if r.effective_from is not None and r.effective_from >= effective_from:
                raise HTTPException(409, "Đã có phiên bản hệ số từ ngày này trở đi — chọn ngày hiệu lực muộn hơn")
            r.effective_to = effective_from - timedelta(days=1)
    base = cur[-1] if cur else None
    new = ProductivityGrade(grade=grade, code=f"PG{grade:02d}", name=name or (base.name if base else f"Bậc {grade}"), productivity_factor=factor, effective_from=effective_from,
                            note=note if note is not None else (base.note if base else ""), created_by=user.username)
    db.add(new)
    db.commit()
    write_audit("PRODUCTIVITY_GRADE_REVISE", user=user, object_type="ProductivityGrade", object_id=str(new.id), detail=f"bậc {grade} = {factor:.0%} từ {effective_from}")
    return new


def set_grade_status(db: Session, user: User, gid: int, active: bool) -> ProductivityGrade:
    g = db.get(ProductivityGrade, gid)
    if g is None:
        raise HTTPException(404, "Không tìm thấy bậc")
    g.status = "ACTIVE" if active else "INACTIVE"
    db.commit()
    write_audit("PRODUCTIVITY_GRADE_STATUS", user=user, object_type="ProductivityGrade", object_id=str(gid), detail=g.status)
    return g


# ------------------------------------------------------------------ cơ cấu lao động theo XN/chuyền
def composition(db: Session, std: LaborStandard, day: date | None = None, grades: list[ProductivityGrade] | None = None) -> dict:
    """Bảng cơ cấu: từng bậc → hệ số, số người, tương đương; kèm tổng và hệ số bình quân gia quyền."""
    day = day or std.effective_from or date.today()
    src = grades if grades is not None else db
    lines, eq_total, head_total = [], 0.0, 0
    for d in sorted(std.details, key=lambda x: -x.grade):
        f = factor_at(src, d.grade, day)
        eq = round(d.headcount * (f or 0.0), 4)
        lines.append({"grade": d.grade, "factor": f, "headcount": d.headcount, "equivalent": eq})
        eq_total += eq
        head_total += d.headcount
    return {"lines": lines, "standard_labor": std.total_labor, "headcount": head_total, "effective_equivalent": round(eq_total, 4),
            "weighted_factor": round(eq_total / std.total_labor, 6) if std.total_labor else None}


def standard_view(db: Session, std: LaborStandard, day: date | None = None) -> dict:
    return {"id": std.id, "factory_code": std.factory_code, "line": std.line, "total_labor": std.total_labor, "effective_from": std.effective_from.isoformat() if std.effective_from else None,
            "effective_to": std.effective_to.isoformat() if std.effective_to else None, "status": std.status, "version": std.version, "note": std.note, "created_by": std.created_by,
            "composition": composition(db, std, day)}


def _validate_standard(db: Session, d: dict, exclude_id: int | None = None) -> list[tuple[int, int]]:
    if not d.get("factory_code"):
        raise HTTPException(422, "Cần xí nghiệp")
    if not d.get("effective_from"):
        raise HTTPException(422, "Cần ngày hiệu lực từ")
    if d.get("effective_to") and d["effective_to"] < d["effective_from"]:
        raise HTTPException(422, "Hiệu lực đến phải sau hoặc bằng hiệu lực từ")
    details = [(int(x["grade"]), int(x["headcount"])) for x in d.get("details") or []]
    if not details:
        raise HTTPException(422, "Cần ít nhất một bậc")
    if len({g for g, _ in details}) != len(details):
        raise HTTPException(422, "Một bậc chỉ được xuất hiện một lần")
    for g, h in details:
        if not 1 <= g <= 10:
            raise HTTPException(422, "Bậc phải từ 1 đến 10")
        if h < 0:
            raise HTTPException(422, "Số người không được âm")
        if factor_at(db, g, d["effective_from"]) is None:
            raise HTTPException(422, f"Bậc {g} chưa có hệ số hiệu lực tại ngày {d['effective_from']}")
    total = sum(h for _, h in details)
    if int(d.get("total_labor") or 0) != total:
        raise HTTPException(422, f"Tổng lao động ({d.get('total_labor')}) phải bằng tổng số người các bậc ({total})")
    return details


def _overlaps(db: Session, d: dict, exclude_id: int | None) -> bool:
    q = db.query(LaborStandard).filter(LaborStandard.status == "ACTIVE", LaborStandard.factory_code == d["factory_code"], LaborStandard.line == (d.get("line") or ""))
    if exclude_id:
        q = q.filter(LaborStandard.id != exclude_id)
    a0, a1 = d["effective_from"], d.get("effective_to") or date.max
    return any(r.effective_from <= a1 and (r.effective_to or date.max) >= a0 for r in q)


def create_standard(db: Session, user: User, d: dict) -> LaborStandard:
    details = _validate_standard(db, d)
    d = {**d, "line": d.get("line") or ""}
    if _overlaps(db, d, None):
        raise HTTPException(409, "Đã có cơ cấu lao động hiệu lực trong khoảng này cho XN/chuyền — dùng 'Sửa' để tạo phiên bản mới")
    std = LaborStandard(factory_code=d["factory_code"], line=d["line"], total_labor=int(d["total_labor"]), effective_from=d["effective_from"], effective_to=d.get("effective_to"),
                        note=d.get("note") or "", created_by=user.username)
    std.details = [LaborStandardGradeDetail(grade=g, headcount=h) for g, h in details]
    db.add(std)
    db.commit()
    write_audit("LABOR_STANDARD_CREATE", user=user, object_type="LaborStandard", object_id=str(std.id), detail=f"{std.factory_code}/{std.line or '*'} {std.total_labor} người")
    return std


def revise_standard(db: Session, user: User, sid: int, d: dict) -> LaborStandard:
    """Sửa = phiên bản mới; bản cũ RETIRED, hiệu lực đóng vào ngày trước `effective_from` của bản mới."""
    old = db.get(LaborStandard, sid)
    if old is None or old.status != "ACTIVE":
        raise HTTPException(404, "Không tìm thấy cơ cấu lao động đang áp dụng")
    d = {"factory_code": old.factory_code, "line": old.line, **d}
    details = _validate_standard(db, d)
    if d["effective_from"] < (old.effective_from or date.min):
        raise HTTPException(409, "Ngày hiệu lực của phiên bản mới không được trước ngày hiệu lực của bản hiện tại")
    # cùng ngày: bản cũ bị thay hoàn toàn (effective_to < effective_from nên không còn được tính) nhưng vẫn lưu để xem lịch sử
    old.effective_to = d["effective_from"] - timedelta(days=1)
    old.status = "RETIRED"
    new = LaborStandard(factory_code=old.factory_code, line=old.line, total_labor=int(d["total_labor"]), effective_from=d["effective_from"], effective_to=d.get("effective_to"),
                        version=old.version + 1, note=d.get("note") or old.note, created_by=user.username)
    new.details = [LaborStandardGradeDetail(grade=g, headcount=h) for g, h in details]
    db.add(new)
    db.commit()
    write_audit("LABOR_STANDARD_REVISE", user=user, object_type="LaborStandard", object_id=str(new.id), detail=f"v{new.version} thay v{old.version}")
    return new


def set_standard_status(db: Session, user: User, sid: int, active: bool) -> LaborStandard:
    s = db.get(LaborStandard, sid)
    if s is None:
        raise HTTPException(404, "Không tìm thấy cơ cấu lao động")
    if active and s.status != "ACTIVE" and _overlaps(db, {"factory_code": s.factory_code, "line": s.line, "effective_from": s.effective_from, "effective_to": s.effective_to}, s.id):
        raise HTTPException(409, "Áp dụng lại sẽ chồng hiệu lực với cơ cấu đang áp dụng")
    s.status = "ACTIVE" if active else "INACTIVE"
    db.commit()
    write_audit("LABOR_STANDARD_STATUS", user=user, object_type="LaborStandard", object_id=str(sid), detail=s.status)
    return s


def equivalent_for(db: Session, factory_code: str, line: str, day: date) -> dict | None:
    """Cho Resource engine: cơ cấu lao động đang hiệu lực của chuyền tại `day` (chuyền cụ thể ưu tiên hơn cấp XN); None nếu chưa khai báo."""
    best = None
    for s in db.query(LaborStandard).filter(LaborStandard.status.in_(["ACTIVE", "RETIRED"]), LaborStandard.factory_code == factory_code, LaborStandard.line.in_([line, ""])):  # RETIRED vẫn dùng để giải thích ngày trong quá khứ
        if s.effective_from <= day and (s.effective_to is None or s.effective_to >= day):
            if best is None or (s.line and not best.line):
                best = s
    return composition(db, best, day) if best else None
