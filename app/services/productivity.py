"""Bảng năng suất theo tổ × mã hàng của một ngày (Dashboard Trang 2, theo sheet "23" của báo cáo năng suất).

Công thức (giống Excel):
    Doanh thu KH / TH = (kế hoạch / sản lượng) × đơn giá
    % hoàn thành      = sản lượng ÷ kế hoạch
    NSLĐBQ            = doanh thu TH ÷ SLĐ công nhân may;   NS/LĐ hiện diện = doanh thu TH ÷ SLĐ tính hiệu suất
    Hiệu suất         = SAM (hoặc SOT) × sản lượng ÷ thời gian làm việc (phút) ÷ SLĐ tính hiệu suất
      - khách hàng DECATHLON  → Hiệu suất DCL, dùng SAM TT (thiếu thì SAM KT)
      - khách hàng khác       → Hiệu suất hàng khác, dùng SOT
SLĐ công nhân may = lao động có mặt của chuyền; SLĐ tính hiệu suất = có mặt + lao động ngoài chuyền (QL...). Chuyền chạy nhiều mã hàng trong ngày:
lao động được phân bổ theo tỉ lệ sản lượng của từng mã hàng (chưa có số lao động thực tế theo mã hàng). Thiếu dữ liệu nào thì ô đó để trống, không suy diễn.
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.resources import BrandCustomer, LaborDaily, LineOutputDaily, LinePlanDaily, StyleSam
from app.services import style_price_service as sp

DECATHLON = "DECATHLON"


def _div(a, b, nd=4):
    return round(a / b, nd) if a is not None and b else None


def compute_row(r: dict) -> dict:
    """r: qty, plan_qty, price, basis_minutes, is_dcl (True/False/None), work_minutes, labor_may, labor_hs (đã phân bổ cho mã hàng)."""
    qty, plan, price = r.get("qty") or 0, r.get("plan_qty"), r.get("price")
    rev_actual = round(qty * price, 2) if price is not None else None
    rev_plan = round(plan * price, 2) if plan is not None and price is not None else None
    eff = None
    if r.get("basis_minutes") and qty and r.get("work_minutes") and r.get("labor_hs"):
        eff = round(r["basis_minutes"] * qty / r["work_minutes"] / r["labor_hs"], 4)
    return {
        "pct": _div(qty, plan) if plan else None,
        "revenue_plan": rev_plan, "revenue_actual": rev_actual,
        "nsld_may": _div(rev_actual, r.get("labor_may"), 3), "ns_present": _div(rev_actual, r.get("labor_hs"), 3),
        "efficiency_dcl": eff if r.get("is_dcl") is True else None,
        "efficiency_other": eff if r.get("is_dcl") is False else None,
    }


def rows_for_day(db: Session, day: date, codes: list[str]) -> list[dict]:
    out_q: dict[tuple, int] = {}
    for c, ln, st, q in db.query(LineOutputDaily.factory_code, LineOutputDaily.line, LineOutputDaily.style, func.sum(LineOutputDaily.qty)).filter(LineOutputDaily.day == day, LineOutputDaily.factory_code.in_(codes)).group_by(LineOutputDaily.factory_code, LineOutputDaily.line, LineOutputDaily.style):
        out_q[(c, ln, st.upper())] = int(q or 0)
    plan: dict[tuple, LinePlanDaily] = {(p.factory_code, p.line, p.style.upper()): p for p in db.query(LinePlanDaily).filter(LinePlanDaily.day == day, LinePlanDaily.factory_code.in_(codes))}
    keys = sorted(set(out_q) | set(plan), key=lambda k: (codes.index(k[0]), int(k[1]) if k[1].isdigit() else 10**6, k[1], -out_q.get(k, 0), k[2]))
    labor = {(l.factory_code, l.line): l for l in db.query(LaborDaily).filter(LaborDaily.day == day, LaborDaily.factory_code.in_(codes))}
    info = {s.style_cc.upper(): s for s in db.query(StyleSam)}
    cust = {b.brand.upper(): b.customer for b in db.query(BrandCustomer)}
    line_qty: dict[tuple, int] = defaultdict(int)
    for k, q in out_q.items():
        line_qty[k[:2]] += q

    rows = []
    for k in keys:
        fac, line, style = k
        si, lab, pl = info.get(style), labor.get((fac, line)), plan.get(k)
        brand = (si.brand if si else "") or ""
        customer = cust.get(brand.upper(), "") if brand else ""
        is_dcl = None if not customer else customer.strip().upper() == DECATHLON
        basis = None
        if si is not None and is_dcl is True:
            basis = si.sam_tt if si.sam_tt else si.sam_kt
        elif si is not None and is_dcl is False:
            basis = si.sot_minutes
        qty = out_q.get(k, 0)
        share = (qty / line_qty[k[:2]]) if line_qty.get(k[:2]) else None
        present = lab.present if lab else None
        hs = (present + (lab.outside or 0)) if lab and present is not None else None
        may_alloc = round(present * share, 2) if present is not None and share is not None else None
        hs_alloc = round(hs * share, 2) if hs is not None and share is not None else None
        price = sp.price_on(db, style, day)
        base = {"factory": fac, "line": line, "style": style, "brand": brand, "customer": customer, "price": price, "qty": qty,
                "plan_qty": round(pl.plan_qty) if pl else None, "basis": ("SAM" if is_dcl else "SOT") if basis else None, "basis_minutes": basis,
                "production_days": ((pl.sew_end - pl.in_line_from).days + 1) if pl and pl.in_line_from and pl.sew_end else None,
                "labor_may": may_alloc, "labor_hs": hs_alloc, "work_minutes": lab.work_minutes if lab else None}
        rows.append({**base, **compute_row({**base, "is_dcl": is_dcl})})
    return rows


def _sum(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v), 2) if v else None


def _avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 4) if v else None


def summarize(rows: list[dict], codes: list[str], labor: dict[str, dict]) -> dict:
    """Dòng tổng của từng XN và toàn công ty — cùng cách tính với các dòng tổng của sheet Excel:
       tổng SLĐ / kế hoạch / sản lượng / doanh thu = cộng các dòng; % HT = SL ÷ KH; NSLĐBQ = DT TH ÷ SLĐ may; NS/LĐ hiện diện = DT TH ÷ SLĐ hiệu suất;
       Hiệu suất DCL / hàng khác = TRUNG BÌNH các dòng có giá trị (bỏ ô trống); toàn công ty = trung bình của các XN có giá trị.
       Khối lao động (nguồn ERP + cơ cấu chức danh): danh sách, có mặt, vắng, tỉ lệ vắng, gián tiếp (= tổng lao động chuyền − CN may); DT bình quân = DT TH ÷ LĐ có mặt.
       labor[code] = {total, present, indirect} (đã cộng theo các chuyền của XN)."""
    out = {}
    for code in codes:
        rs = [r for r in rows if r["factory"] == code]
        out[code] = _one(rs, labor.get(code) or {})
    allrs = rows
    tong = _one(allrs, {k: _sum(labor.get(c, {}).get(k) for c in codes) for k in ("total", "present", "indirect")})
    tong["efficiency_dcl"] = _avg(out[c]["efficiency_dcl"] for c in codes)
    tong["efficiency_other"] = _avg(out[c]["efficiency_other"] for c in codes)
    pres, ind = tong["labor_present_erp"], tong["labor_indirect"]
    tong["ns_all_labor"] = _div(tong["revenue_actual"], (pres or 0) + (ind or 0), 3) if pres is not None else None  # DT ÷ (LĐ hiện diện + gián tiếp)
    out["TONG"] = tong
    return out


def _one(rs: list[dict], lab: dict) -> dict:
    plan, qty = _sum(r["plan_qty"] for r in rs), _sum(r["qty"] for r in rs)
    rp, ra = _sum(r["revenue_plan"] for r in rs), _sum(r["revenue_actual"] for r in rs)
    may, hs = _sum(r["labor_may"] for r in rs), _sum(r["labor_hs"] for r in rs)
    total, present = lab.get("total"), lab.get("present")
    return {
        "labor_may": may, "labor_hs": hs, "plan_qty": plan, "qty": qty, "pct": _div(qty, plan) if plan else None, "revenue_plan": rp, "revenue_actual": ra,
        "nsld_may": _div(ra, may, 3), "ns_present": _div(ra, hs, 3),
        "efficiency_dcl": _avg(r["efficiency_dcl"] for r in rs), "efficiency_other": _avg(r["efficiency_other"] for r in rs),
        "labor_list": total, "labor_present_erp": present, "labor_absent": (total - present) if total is not None and present is not None else None,
        "absent_rate": _div((total - present) if total is not None and present is not None else None, total), "labor_indirect": lab.get("indirect"),
        "avg_revenue_per_present": _div(ra, present, 3),
    }
