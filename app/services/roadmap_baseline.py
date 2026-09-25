"""Đọc baseline THẬT từ Postgres cho Roadmap Simulation (Task 5 — Issue #11). CHỈ ĐỌC — không bao giờ sửa/xóa/clean bảng nguồn.

- REVENUE: `revenue_monthly` / `revenue_yearly`, basis PLAN|ACTUAL, TOTAL = SUM XN1+XN2+XN3 cùng kỳ/basis/unit (USD).
- OUTPUT_QTY: basis PACK_QTY (đóng gói/FG, `po_pack_daily`) — chỉ TOTAL mới CALCULATED khi kỳ được nguồn phủ đủ;
  FACTORY => PARTIAL_SOURCE (mapping PO→XN chưa đủ tin cậy). `factory_output_daily.sewn_qty` KHÔNG dùng làm baseline.
- Không extrapolate run-rate, không copy kỳ gần nhất tự động, không suy revenue từ output, không cộng thô capacity_definitions.
- Trả `data_quality_flags` + metadata độ tươi nguồn (latest success / last attempt / age) để snapshot vào Run.
"""

from __future__ import annotations

import calendar
from datetime import date, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import Factory
from app.models.data import PoPackDaily, PoProgress, RevenueDaily, RevenueMonthly, RevenueYearly, SyncRun
from app.models.resources import LaborStandard, MachineCapacity

SOURCE_SYNC_JOB = "EGMF_REVENUE"  # revenue + po_pack_daily cùng job đồng bộ eGMF
_SUCCESS_STATUSES = ("SUCCEEDED", "PARTIAL")
_INVALID_DATE_BEFORE = date(2000, 1, 1)


def period_label(period_type: str, year: int, month: int | None) -> str:
    return f"{year}-{month:02d}" if period_type == "MONTH" else f"{year}"


def period_bounds(period_type: str, year: int, month: int | None) -> tuple[date, date]:
    if period_type == "MONTH":
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    return date(year, 1, 1), date(year, 12, 31)


def scope_factories(db: Session, scope_type: str, scope_value: str) -> list[Factory]:
    if scope_type == "FACTORY":
        f = db.query(Factory).filter(Factory.code == scope_value).first()
        return [f] if f else []
    return db.query(Factory).filter(Factory.is_active.is_(True)).order_by(Factory.code).all()


def _run_view(r: SyncRun | None) -> dict | None:
    if r is None:
        return None
    return {"run_id": r.id, "run_code": r.run_code, "status": r.status, "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None, "total_records": r.total_records}


def source_freshness(db: Session, source: str = SOURCE_SYNC_JOB) -> dict:
    """Độ tươi nguồn: latest successful + last attempt + age. Không hard-code ngưỡng N ngày (không có SLA đáng tin cậy) — chỉ hiển thị
    age + last status và cờ khi lần thử gần nhất FAILED hoặc chưa từng thành công (GPT Issue #11 mục 5)."""
    ok = db.query(SyncRun).filter(SyncRun.source == source, SyncRun.status.in_(_SUCCESS_STATUSES)).order_by(SyncRun.started_at.desc()).first()
    last = db.query(SyncRun).filter(SyncRun.source == source).order_by(SyncRun.started_at.desc()).first()
    age_hours = None
    if ok is not None and ok.started_at is not None:
        started = ok.started_at if ok.started_at.tzinfo is not None else ok.started_at.replace(tzinfo=timezone.utc)  # SQLite trả naive, Postgres trả aware
        age_hours = round((utcnow() - started).total_seconds() / 3600, 1)
    flagged = ok is None or (last is not None and last.status == "FAILED")
    return {"source_job": source, "latest_success": _run_view(ok), "last_attempt": _run_view(last), "source_age_hours": age_hours, "stale_or_last_sync_failed": flagged}


def _ok(value: float, identity: dict, flags: list[str], diagnostics: dict | None = None) -> dict:
    return {"status": "OK", "value": value, "unit": identity["unit"], "identity": identity, "flags": flags, "missing_inputs": [], "diagnostics": diagnostics or {}}


def _bad(status: str, identity: dict, flags: list[str], missing: list[str], diagnostics: dict | None = None) -> dict:
    return {"status": status, "value": None, "unit": identity["unit"], "identity": identity, "flags": flags, "missing_inputs": missing, "diagnostics": diagnostics or {}}


# ------------------------------------------------------------------ REVENUE
def revenue_baseline(db: Session, basis: str, period_type: str, year: int, month: int | None, scope_type: str, scope_value: str) -> dict:
    facs = scope_factories(db, scope_type, scope_value)
    plabel = period_label(period_type, year, month)
    table = "revenue_monthly" if period_type == "MONTH" else "revenue_yearly"
    identity = {"metric": "REVENUE", "basis": basis, "period": plabel, "period_type": period_type, "scope_type": scope_type, "scope_value": scope_value,
                "unit": "USD", "table": table, "factory_values": {}}
    flags: list[str] = []
    if not facs:
        return _bad("MISSING_BASELINE", identity, ["MISSING_BASELINE"], [f"scope {scope_type}/{scope_value} không có factory hợp lệ"])
    ids = {f.id: f.code for f in facs}

    # source-quality: dòng ngày không hợp lệ (vd 0001-01-01) bị loại khỏi baseline, chỉ cảnh báo — không sửa nguồn
    invalid = db.query(func.count(RevenueDaily.id)).filter(RevenueDaily.factory_id.in_(ids), RevenueDaily.report_date < _INVALID_DATE_BEFORE).scalar() or 0
    if invalid:
        flags.append("INVALID_SOURCE_DATE")

    if period_type == "MONTH":
        rows = db.query(RevenueMonthly).filter(RevenueMonthly.factory_id.in_(ids), RevenueMonthly.year == year, RevenueMonthly.month == month).all()
    else:
        rows = db.query(RevenueYearly).filter(RevenueYearly.factory_id.in_(ids), RevenueYearly.year == year).all()
    by_f = {r.factory_id: r for r in rows}
    values: dict[str, float] = {}
    missing_codes: list[str] = []
    for fid, code in ids.items():
        r = by_f.get(fid)
        v = getattr(r, basis.lower()) if r is not None else None
        if v is None:
            missing_codes.append(code)
        else:
            values[code] = float(v)
    identity["factory_values"] = dict(sorted(values.items()))
    diagnostics = {"invalid_date_rows_excluded": int(invalid), "declared_by": sorted({r.declared_by for r in rows if r.declared_by})}

    if period_type == "YEAR":  # tính nhất quán yearly vs Σ monthly cùng basis — bất thường thì cảnh báo, không tự kết luận là test
        for fid, code in ids.items():
            yr = by_f.get(fid)
            mrows = db.query(RevenueMonthly).filter(RevenueMonthly.factory_id == fid, RevenueMonthly.year == year).all()
            if yr is not None and mrows:
                yv = getattr(yr, basis.lower())
                mv = [getattr(m, basis.lower()) for m in mrows if getattr(m, basis.lower()) is not None]
                if yv is not None and mv and abs(sum(mv) - yv) > max(1.0, 0.001 * abs(yv)):
                    flags.append("SOURCE_INCONSISTENT_PERIODS")
                    diagnostics.setdefault("inconsistent_factories", []).append(code)
    flags = list(dict.fromkeys(flags))

    if not values:
        return _bad("MISSING_BASELINE", identity, [*flags, "MISSING_BASELINE"], [f"Không có {basis} revenue {plabel} trong {table} cho scope {scope_type}/{scope_value or 'TOTAL'}"], diagnostics)
    if missing_codes:  # TOTAL mà thiếu XN => không lấy tổng thiếu làm baseline
        return _bad("PARTIAL_SOURCE", identity, [*flags, "PARTIAL_SOURCE_COVERAGE"], [f"Thiếu {basis} revenue {plabel} của {', '.join(missing_codes)}"], diagnostics)
    return _ok(round(sum(values.values()), 6), identity, flags, diagnostics)


# ------------------------------------------------------------------ OUTPUT_QTY (PACK_QTY)
def _po_factory_coverage(db: Session, start: date, end: date) -> dict:
    pos = {p for (p,) in db.query(PoPackDaily.po).filter(PoPackDaily.day >= start, PoPackDaily.day <= end).distinct().all()}
    if not pos:
        return {"packed_pos": 0, "mapped_to_factory": 0, "coverage_pct": None}
    mapped = db.query(func.count(func.distinct(PoProgress.po))).filter(PoProgress.po.in_(pos), PoProgress.factory_id.isnot(None)).scalar() or 0
    return {"packed_pos": len(pos), "mapped_to_factory": int(mapped), "coverage_pct": round(100.0 * mapped / len(pos), 1)}


def output_baseline(db: Session, basis: str, period_type: str, year: int, month: int | None, scope_type: str, scope_value: str) -> dict:
    plabel = period_label(period_type, year, month)
    start, end = period_bounds(period_type, year, month)
    identity = {"metric": "OUTPUT_QTY", "output_definition": "PACK_QTY", "basis": basis, "period": plabel, "period_type": period_type,
                "scope_type": scope_type, "scope_value": scope_value, "unit": "sp", "table": "po_pack_daily", "value": None}
    dmin, dmax = db.query(func.min(PoPackDaily.day), func.max(PoPackDaily.day)).one()
    coverage = _po_factory_coverage(db, start, end)
    diagnostics = {"source_day_range": [dmin.isoformat() if dmin else None, dmax.isoformat() if dmax else None], "po_factory_mapping": coverage}
    if scope_type != "TOTAL":
        return _bad("PARTIAL_SOURCE", identity, ["PARTIAL_SOURCE_COVERAGE"],
                    ["Output PACK_QTY theo XN cần mapping PO→XN đủ tin cậy (chưa có) — Task 5 chỉ tính TOTAL"], diagnostics)
    if dmin is None:
        return _bad("MISSING_BASELINE", identity, ["MISSING_BASELINE"], ["po_pack_daily không có dữ liệu"], diagnostics)
    total = db.query(func.coalesce(func.sum(PoPackDaily.qty), 0)).filter(PoPackDaily.day >= start, PoPackDaily.day <= end).scalar() or 0
    if not (dmin <= start and dmax >= end):
        identity["value"] = float(total)
        return _bad("PARTIAL_SOURCE", identity, ["PARTIAL_SOURCE_COVERAGE"],
                    [f"Nguồn po_pack_daily chỉ phủ {dmin.isoformat()}→{dmax.isoformat()}, chưa phủ đủ kỳ {plabel} ({start.isoformat()}→{end.isoformat()})"], diagnostics)
    identity["value"] = float(total)
    return _ok(float(total), identity, [], diagnostics)


def baseline_for(db: Session, metric: str, basis: str, period_type: str, year: int, month: int | None, scope_type: str, scope_value: str) -> dict:
    fn = revenue_baseline if metric == "REVENUE" else output_baseline
    res = fn(db, basis, period_type, year, month, scope_type, scope_value)
    res["source_meta"] = source_freshness(db)
    if res["source_meta"]["stale_or_last_sync_failed"] and "SOURCE_STALE_OR_LAST_SYNC_FAILED" not in res["flags"]:
        res["flags"] = [*res["flags"], "SOURCE_STALE_OR_LAST_SYNC_FAILED"]
    return res


# ------------------------------------------------------------------ Resource baselines (input cho proposal; chỉ tham chiếu — không cộng thô capacity)
def labor_baseline(db: Session, scope_type: str, scope_value: str) -> dict | None:
    codes = [f.code for f in scope_factories(db, scope_type, scope_value)]
    if not codes:
        return None
    rows = db.query(LaborStandard).filter(LaborStandard.factory_code.in_(codes), LaborStandard.status == "ACTIVE").all()
    if not rows:
        return None
    by_f: dict[str, int] = {}
    for r in rows:
        by_f[r.factory_code] = by_f.get(r.factory_code, 0) + int(r.total_labor or 0)
    return {"source": "labor_standards", "status_filter": "ACTIVE", "rows": len(rows), "total_labor": sum(by_f.values()), "by_factory": dict(sorted(by_f.items()))}


def machine_baseline(db: Session, scope_type: str, scope_value: str) -> dict | None:
    codes = [f.code for f in scope_factories(db, scope_type, scope_value)]
    if not codes:
        return None
    rows = db.query(MachineCapacity).filter(MachineCapacity.factory_code.in_(codes), MachineCapacity.status == "ACTIVE").all()
    if not rows:
        return None
    by_t: dict[str, int] = {}
    for r in rows:
        by_t[r.machine_type] = by_t.get(r.machine_type, 0) + int(r.quantity or 0)
    return {"source": "machine_capacities", "status_filter": "ACTIVE", "rows": len(rows), "by_machine_type": dict(sorted(by_t.items()))}
