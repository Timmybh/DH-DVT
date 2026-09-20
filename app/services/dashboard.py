"""Tính toán số liệu dashboard từ dữ liệu đã cache trong Postgres.

Góc nhìn Tổng công ty = cộng dồn từ các đơn vị (xí nghiệp); góc nhìn đơn vị = chỉ dữ liệu của xí nghiệp đó.
"""

import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import utcnow
from app.models.core import Factory
from app.models.data import (
    LaborHeadcount,
    PlanImportBatch,
    PlanRow,
    RevenueDaily,
    RevenueMonthly,
    RevenueYearly,
    SyncRun,
)
from app.services.rules import elapsed_pct, month_bounds, safe_pct


def today_local() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def scope_factories(db: Session, scope: str | None) -> tuple[list[Factory], bool]:
    """Trả (danh sách xí nghiệp trong phạm vi, is_total)."""
    factories = db.query(Factory).filter(Factory.is_active.is_(True)).order_by(Factory.display_order).all()
    if not scope or scope.upper() == "TONG":
        return factories, True
    picked = [f for f in factories if f.code.upper() == scope.upper()]
    if not picked:
        raise HTTPException(status_code=404, detail=f"Không có đơn vị '{scope}'")
    return picked, False


def _sum(values) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) if vals else None


def _tile(plan, actual, remaining=None) -> dict:
    if remaining is None and plan is not None and actual is not None:
        remaining = plan - actual
    return {"plan": plan, "actual": actual, "remaining": remaining, "pct": safe_pct(actual, plan)}


def revenue_overview(db: Session, factories: list[Factory], year: int, month: int, today: date) -> dict:
    fids = [f.id for f in factories]
    first, last = month_bounds(year, month)

    daily = (
        db.query(RevenueDaily)
        .filter(RevenueDaily.factory_id.in_(fids), RevenueDaily.report_date >= first, RevenueDaily.report_date <= last)
        .all()
    )
    by_date: dict[date, list[RevenueDaily]] = {}
    for r in daily:
        by_date.setdefault(r.report_date, []).append(r)

    trend = []
    latest_day = None
    for d in range(1, calendar.monthrange(year, month)[1] + 1):
        dt = date(year, month, d)
        rows = by_date.get(dt, [])
        plan = _sum(r.plan for r in rows)
        actual = _sum(r.actual for r in rows)
        trend.append({"date": dt.isoformat(), "plan": plan, "actual": actual})
        if actual and actual > 0 and dt <= today:
            latest_day = {"date": dt.isoformat(), **_tile(plan, actual, _sum(r.remaining for r in rows))}

    monthly = (
        db.query(RevenueMonthly)
        .filter(RevenueMonthly.factory_id.in_(fids), RevenueMonthly.year == year, RevenueMonthly.month == month)
        .all()
    )
    yearly = db.query(RevenueYearly).filter(RevenueYearly.factory_id.in_(fids), RevenueYearly.year == year).all()
    m_by_f = {r.factory_id: r for r in monthly}
    y_by_f = {r.factory_id: r for r in yearly}

    month_tile = _tile(_sum(r.plan for r in monthly), _sum(r.actual for r in monthly), _sum(r.remaining for r in monthly))
    year_tile = _tile(_sum(r.plan for r in yearly), _sum(r.actual for r in yearly), _sum(r.remaining for r in yearly))
    elapsed = elapsed_pct(year, month, today)

    by_factory = []
    for f in factories:
        m, y = m_by_f.get(f.id), y_by_f.get(f.id)
        by_factory.append(
            {
                "code": f.code,
                "name": f.name,
                "month_declared": m is not None,
                "month_plan": m.plan if m else None,
                "month_actual": m.actual if m else None,
                "month_pct": safe_pct(m.actual, m.plan) if m else None,
                "year_plan": y.plan if y else None,
                "year_actual": y.actual if y else None,
                "year_pct": safe_pct(y.actual, y.plan) if y else None,
            }
        )

    all_rows = [*daily, *monthly, *yearly]
    latest_actual_date = (
        db.query(func.max(RevenueDaily.report_date))
        .filter(RevenueDaily.factory_id.in_(fids), RevenueDaily.actual.isnot(None), RevenueDaily.actual > 0)
        .scalar()
    )
    return {
        "unit": settings.revenue_unit,
        "month": f"{year}-{month:02d}",
        "elapsed_pct": elapsed,
        "day": latest_day,
        "month_tile": month_tile,
        "year_tile": year_tile,
        "trend": trend,
        "by_factory": by_factory,
        "has_demo": any(r.source == "DEMO" for r in all_rows),
        "latest_actual_date": latest_actual_date.isoformat() if latest_actual_date else None,
        "undeclared_month": [f.code for f in factories if f.id not in m_by_f],
    }


def revenue_summary(
    db: Session, all_factories: list[Factory], selected: list[Factory], is_total: bool, year: int, month: int, period: str = "month"
) -> dict:
    """Tóm tắt điều hành cho dashboard chính. period="month": tháng đang chọn; period="ytd": lũy kế cả năm (bảng DoanhThu_Nam).

    Góc nhìn Tổng công ty: XN1, XN2, XN3 + Tổng công ty. Góc nhìn Xí nghiệp: chỉ XN đang chọn + Tổng công ty.
    Dòng "Tổng công ty" luôn cộng dồn từ TẤT CẢ đơn vị, không phụ thuộc XN đang xem.
    """
    fids = [f.id for f in all_factories]
    if period == "ytd":
        q = db.query(RevenueYearly).filter(RevenueYearly.factory_id.in_(fids), RevenueYearly.year == year)
    else:
        q = db.query(RevenueMonthly).filter(RevenueMonthly.factory_id.in_(fids), RevenueMonthly.year == year, RevenueMonthly.month == month)
    monthly = {r.factory_id: r for r in q}

    def row(f: Factory) -> dict:
        m = monthly.get(f.id)
        return {
            "code": f.code, "label": f.name, "kind": "FACTORY", "declared": m is not None,
            "plan": m.plan if m else None, "actual": m.actual if m else None,
            "pct": safe_pct(m.actual, m.plan) if m else None, "selected": (not is_total) and f.id == selected[0].id,
        }

    rows = [row(f) for f in (all_factories if is_total else selected)]
    declared = [monthly[f.id] for f in all_factories if f.id in monthly]
    plan, actual = _sum(r.plan for r in declared), _sum(r.actual for r in declared)
    rows.append(
        {
            "code": "TONG", "label": "Tổng công ty", "kind": "TOTAL", "declared": bool(declared),
            "plan": plan, "actual": actual, "pct": safe_pct(actual, plan), "selected": False,
            "missing": [f.code for f in all_factories if f.id not in monthly],
        }
    )
    used = [monthly[f.id] for f in all_factories if f.id in monthly and (is_total or f.id == selected[0].id)]
    return {"rows": rows, "has_demo": any(r.source == "DEMO" for r in (declared if is_total else used + declared))}


def current_batch(db: Session) -> PlanImportBatch | None:
    return db.query(PlanImportBatch).filter(PlanImportBatch.is_current.is_(True)).order_by(PlanImportBatch.id.desc()).first()


def progress_overview(db: Session, factories: list[Factory], is_total: bool) -> dict:
    batch = current_batch(db)
    if batch is None:
        return {"available": False}
    fids = [f.id for f in factories]

    def scoped(q):
        return q if is_total else q.filter(PlanRow.factory_id.in_(fids))

    # --- Planning status x Factory assignment (hai chiều độc lập)
    counts = {"UNPLANNED": {"KNOWN": 0, "UNASSIGNED": 0}, "PLANNED": {"KNOWN": 0, "UNASSIGNED": 0}}
    q = scoped(db.query(PlanRow.planning_status, PlanRow.factory_assignment, func.count(PlanRow.id)).filter(PlanRow.batch_id == batch.id))
    for ps, fa, cnt in q.group_by(PlanRow.planning_status, PlanRow.factory_assignment).all():
        counts[ps][fa] = cnt
    unplanned = sum(counts["UNPLANNED"].values())
    planned = sum(counts["PLANNED"].values())

    # --- Rủi ro giao hàng (chiều thứ ba của dữ liệu vận hành, không liên quan mapping)
    risks = {"OK": 0, "ADVANCE": 0, "LATE": 0, "MATERIAL": 0}
    risk_qty = {"OK": 0.0, "ADVANCE": 0.0, "LATE": 0.0, "MATERIAL": 0.0}
    planned_qty = 0.0
    q = scoped(
        db.query(PlanRow.planning_status, PlanRow.risk, func.count(PlanRow.id), func.coalesce(func.sum(PlanRow.quantity), 0.0)).filter(
            PlanRow.batch_id == batch.id
        )
    )
    for ps, risk, cnt, qty in q.group_by(PlanRow.planning_status, PlanRow.risk).all():
        risks[risk] = risks.get(risk, 0) + cnt
        risk_qty[risk] = risk_qty.get(risk, 0.0) + float(qty)
        if ps == "PLANNED":
            planned_qty += float(qty)

    # --- Mapping status (cảnh báo dữ liệu nguồn)
    mapping_warnings = scoped(
        db.query(func.count(PlanRow.id)).filter(PlanRow.batch_id == batch.id, PlanRow.mapping_status == "WARNING")
    ).scalar() or 0

    per_factory = []
    for f in factories:
        rows = (
            db.query(PlanRow.risk, func.count(PlanRow.id), func.coalesce(func.sum(PlanRow.quantity), 0.0))
            .filter(PlanRow.batch_id == batch.id, PlanRow.factory_id == f.id, PlanRow.planning_status == "PLANNED")
            .group_by(PlanRow.risk)
            .all()
        )
        d = {"OK": 0, "ADVANCE": 0, "LATE": 0, "MATERIAL": 0}
        qty = 0.0
        for risk, cnt, q_ in rows:
            d[risk] = cnt
            qty += float(q_)
        per_factory.append({"code": f.code, "name": f.name, "po": sum(d.values()), "qty": qty, **{k.lower(): v for k, v in d.items()}})

    total_po = planned + unplanned
    s = batch.summary or {}
    return {
        "available": True,
        "batch": {"filename": batch.filename, "imported_at": batch.imported_at.isoformat(), "labor_as_of": s.get("labor_as_of", "")},
        "pipeline": {
            "new": unplanned,
            "new_known": counts["UNPLANNED"]["KNOWN"],
            "new_unassigned": counts["UNPLANNED"]["UNASSIGNED"],
            "planned": planned,
            "sewn": s.get("sewn_count") if is_total else None,
            "shipped": s.get("shipped_count") if is_total else None,
        },
        "total_po": total_po,
        "planned_qty": planned_qty,
        "risks": risks,
        "risk_qty": risk_qty,
        "late_pct": (risks["LATE"] / total_po * 100.0) if total_po else 0.0,
        "mapping_warnings": mapping_warnings,
        "by_factory": per_factory,
    }


def hr_overview(db: Session, factories: list[Factory], is_total: bool) -> dict:
    batch = current_batch(db)
    if batch is None:
        return {"available": False}
    fids = [f.id for f in factories]
    q = db.query(LaborHeadcount).filter(LaborHeadcount.batch_id == batch.id)
    if not is_total:
        q = q.filter(LaborHeadcount.factory_id.in_(fids))
    rows = q.all()
    by_fid: dict[int | None, int] = {}
    for r in rows:
        by_fid[r.factory_id] = by_fid.get(r.factory_id, 0) + r.headcount
    return {
        "available": True,
        "total": sum(by_fid.values()),
        "as_of_text": (rows[0].as_of_text if rows else "") or "",
        "by_factory": [{"code": f.code, "name": f.name, "total": by_fid.get(f.id, 0)} for f in factories],
        "teams": len(rows),
    }


def last_sync(db: Session, source: str | None = None) -> SyncRun | None:
    q = db.query(SyncRun)
    if source:
        q = q.filter(SyncRun.source == source)
    return q.order_by(SyncRun.started_at.desc()).first()


def sync_brief(run: SyncRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "run_code": run.run_code,
        "source": run.source,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "matched": run.matched,
        "unmatched": run.unmatched,
        "total_records": run.total_records,
    }


# ------------------------------------------------------------------ drill-down
def drill_po(db: Session, factories: list[Factory], is_total: bool, risk: str, limit: int = 300) -> dict:
    """risk: ALL | OK | ADVANCE | LATE | MATERIAL (rủi ro giao hàng) | UNPLANNED | UNASSIGNED | MAPPING (ba chiều còn lại)."""
    batch = current_batch(db)
    if batch is None:
        return {"rows": [], "total": 0}
    fmap = {f.id: f.code for f in db.query(Factory).all()}
    q = db.query(PlanRow).filter(PlanRow.batch_id == batch.id)
    if not is_total:
        q = q.filter(PlanRow.factory_id.in_([f.id for f in factories]))
    if risk == "UNPLANNED":
        q = q.filter(PlanRow.planning_status == "UNPLANNED")
    elif risk == "UNASSIGNED":
        q = q.filter(PlanRow.factory_assignment == "UNASSIGNED")
    elif risk == "MAPPING":
        q = q.filter(PlanRow.mapping_status == "WARNING")
    elif risk != "ALL":
        q = q.filter(PlanRow.risk == risk)
    total = q.count()
    order = PlanRow.gap_days.asc().nullslast() if risk in ("LATE", "ALL") else PlanRow.chd.asc().nullslast()
    rows = q.order_by(order).limit(limit).all()
    return {
        "total": total,
        "rows": [
            {
                "factory": fmap.get(r.factory_id) or "Chưa xác định XN",
                "planning_status": r.planning_status,
                "mapping_status": r.mapping_status,
                "line": r.line_raw,
                "po_number": r.po_number,
                "customer": r.customer,
                "sport": r.sport,
                "description": r.description,
                "quantity": r.quantity,
                "chd": r.chd.isoformat() if r.chd else None,
                "end_prod_date": r.end_prod_date.isoformat() if r.end_prod_date else None,
                "gap_days": r.gap_days,
                "status": r.status_text,
                "risk": r.risk,
                "reason": r.mapping_note or r.risk_reason or r.note,
            }
            for r in rows
        ],
    }


def drill_revenue(db: Session, factories: list[Factory], year: int, month: int) -> dict:
    first, last = month_bounds(year, month)
    fids = [f.id for f in factories]
    rows = (
        db.query(RevenueDaily)
        .filter(RevenueDaily.factory_id.in_(fids), RevenueDaily.report_date >= first, RevenueDaily.report_date <= last)
        .order_by(RevenueDaily.report_date)
        .all()
    )
    code = {f.id: f.code for f in factories}
    by_date: dict[date, dict] = {}
    for r in rows:
        d = by_date.setdefault(r.report_date, {"date": r.report_date.isoformat(), "plan": None, "actual": None, "factories": {}})
        d["plan"] = (d["plan"] or 0) + (r.plan or 0) if r.plan is not None or d["plan"] is not None else None
        d["actual"] = (d["actual"] or 0) + (r.actual or 0) if r.actual is not None or d["actual"] is not None else None
        d["factories"][code[r.factory_id]] = {"plan": r.plan, "actual": r.actual}
    today = today_local()
    return {
        "unit": settings.revenue_unit,
        "codes": [f.code for f in factories],
        "rows": list(by_date.values()),
        "today": today.isoformat(),
        # chi tiết chỉ hiện trong drill-down: 3 gauge Ngày/Tháng/Năm, biểu đồ theo ngày, bảng theo đơn vị
        "detail": revenue_overview(db, factories, year, month, today),
    }


def drill_hr(db: Session, factories: list[Factory], is_total: bool) -> dict:
    batch = current_batch(db)
    if batch is None:
        return {"rows": []}
    fmap = {f.id: f.code for f in db.query(Factory).all()}
    q = db.query(LaborHeadcount).filter(LaborHeadcount.batch_id == batch.id)
    if not is_total:
        q = q.filter(LaborHeadcount.factory_id.in_([f.id for f in factories]))
    rows = q.order_by(LaborHeadcount.factory_id, LaborHeadcount.team).all()
    return {"rows": [{"factory": fmap.get(r.factory_id, "—"), "team": r.team, "headcount": r.headcount, "as_of": r.as_of_text} for r in rows]}
