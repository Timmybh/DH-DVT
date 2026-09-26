"""Dashboard Trang 2 (báo cáo năng suất theo ngày, theo sheet "23" của báo cáo năng suất tháng).

Dữ liệu: doanh thu ngày theo XN (revenue_daily), lao động chuyền/ngày (labor_daily), sản lượng tổ × mã hàng (line_output_daily, từ HiPro).
Ngày không có dữ liệu → has_data = False (không suy diễn, không lấy ngày khác).
"""

import calendar
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.core import Factory
from app.models.data import RevenueDaily
from app.models.resources import LaborDaily
from app.services import productivity


def _ratio(a: float | None, b: float | None) -> float | None:
    return round(a / b, 4) if a is not None and b else None


def _cell(plan: float | None, actual: float | None, total: int | None, present: int | None) -> dict:
    return {
        "plan": plan,
        "actual": actual,
        "pct": _ratio(actual, plan),
        "labor_total": total,
        "labor_present": present,
        "labor_absent": (total - present) if total is not None and present is not None else None,
        "absent_rate": _ratio((total - present) if total is not None and present is not None else None, total),
        "dtbq_present": round(actual / present, 3) if actual is not None and present else None,  # doanh thu bình quân / LĐ có mặt
    }


def _sum(values) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) if vals else None


def line_labor_map(db: Session, day: date, codes: list[str]) -> dict[tuple[str, str], tuple[int, int]]:
    return {(c, ln): (int(t or 0), int(p or 0)) for c, ln, t, p in db.query(LaborDaily.factory_code, LaborDaily.line, LaborDaily.total, LaborDaily.present).filter(LaborDaily.day == day, LaborDaily.factory_code.in_(codes))}


def build(db: Session, day: date) -> dict:
    factories = db.query(Factory).filter(Factory.is_active.is_(True)).order_by(Factory.display_order, Factory.code).all()
    codes = [f.code for f in factories]
    id_code = {f.id: f.code for f in factories}
    first, last = date(day.year, day.month, 1), day
    rev: dict[tuple[date, str], RevenueDaily] = {
        (r.report_date, id_code[r.factory_id]): r
        for r in db.query(RevenueDaily).filter(RevenueDaily.report_date >= first, RevenueDaily.report_date <= last, RevenueDaily.factory_id.in_(id_code)).all()
    }
    lab: dict[tuple[date, str], tuple[int, int]] = {
        (d, c): (int(t or 0), int(p or 0))
        for c, d, t, p in db.query(LaborDaily.factory_code, LaborDaily.day, func.sum(LaborDaily.total), func.sum(LaborDaily.present))
        .filter(LaborDaily.day >= first, LaborDaily.day <= last, LaborDaily.factory_code.in_(codes)).group_by(LaborDaily.factory_code, LaborDaily.day).all()
    }

    def day_cells(d: date) -> dict[str, dict] | None:
        out: dict[str, dict] = {}
        for c in codes:
            r, l = rev.get((d, c)), lab.get((d, c))
            out[c] = _cell(r.plan if r else None, r.actual if r else None, l[0] if l else None, l[1] if l else None)
        if all(v["actual"] is None and v["labor_total"] is None for v in out.values()):
            return None
        vals = list(out.values())
        total_l, pres_l = _sum(v["labor_total"] for v in vals), _sum(v["labor_present"] for v in vals)
        out["TONG"] = _cell(_sum(v["plan"] for v in vals), _sum(v["actual"] for v in vals), int(total_l) if total_l is not None else None, int(pres_l) if pres_l is not None else None)
        return out

    series = []
    for n in range(1, calendar.monthrange(day.year, day.month)[1] + 1):
        d = date(day.year, day.month, n)
        if d > day:
            break
        cells = day_cells(d)
        if cells:
            series.append({"date": d.isoformat(), "cells": cells})
    selected = day_cells(day)

    # Bảng năng suất theo tổ × mã hàng của đúng ngày chọn (kế hoạch OMM_KeHoachThang + sản lượng HiPro + giá + SAM/SOT + lao động ERP)
    lines = productivity.rows_for_day(db, day, codes)
    from app.models.resources import LaborStandard

    lab_x: dict[str, dict] = {}
    for c in codes:
        rows_l = [v for (fc, _ln), v in line_labor_map(db, day, codes).items() if fc == c]
        if rows_l:
            lab_x[c] = {"total": sum(t for t, _p in rows_l), "present": sum(p for _t, p in rows_l)}
    for s_ in db.query(LaborStandard).filter(LaborStandard.status == "ACTIVE", LaborStandard.line != "", LaborStandard.factory_code.in_(codes), LaborStandard.effective_from <= day):
        if s_.effective_to is None or s_.effective_to >= day:
            d_ = lab_x.setdefault(s_.factory_code, {})
            d_["indirect"] = d_.get("indirect", 0) + (s_.total_labor - (s_.cn_may or 0))  # gián tiếp = tổng lao động chuyền − CN may
    summaries = productivity.summarize(lines, codes, lab_x) if lines else None
    # DTBQ LĐ may của công ty ở tối đa 5 ngày gần nhất (đến ngày chọn) có dữ liệu
    days = []
    for back in range(0, 14):
        d0 = day - timedelta(days=back)
        rows0 = lines if back == 0 else productivity.rows_for_day(db, d0, codes)
        if rows0:
            days.append({"date": d0.isoformat(), "nsld_may": productivity.summarize(rows0, codes, {})["TONG"]["nsld_may"]})
        if len(days) == 5:
            break
    days.reverse()
    charts = productivity.dtbq_charts(productivity.get_targets(db), codes, summaries, days)
    eff_daily = productivity.efficiency_daily(db, day, codes)
    return {
        "date": day.isoformat(),
        "has_data": selected is not None or bool(lines),
        "unit": settings.revenue_unit,
        "factories": codes,
        "day": selected,
        "series": series,
        "lines": lines,
        "line_summaries": summaries,
        "dtbq_charts": charts,
        "efficiency_daily": eff_daily,
        "efficiency_month": productivity.efficiency_month(eff_daily, codes),
        "nsbq": productivity.nsbq_monthly(db, day, codes),
    }
