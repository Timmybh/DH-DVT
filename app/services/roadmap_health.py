"""Source Data Health + Production Readiness (Task 10 — Issue #21). CHỈ ĐỌC, mô tả (descriptive) — KHÔNG đổi baseline/semantics nào của Task 1–9:
- PARTIAL sync KHÔNG được coi là stale (định nghĩa stale = chưa từng SUCCEEDED/PARTIAL hoặc lần thử gần nhất FAILED — đúng `roadmap_baseline.source_freshness`).
- FACTORY OUTPUT_QTY vẫn `PARTIAL_SOURCE`; thống kê PO→XN chỉ để minh bạch, không đổi kết quả Run.
- YEAR OUTPUT_QTY vẫn theo rule cũ (cần phủ đủ năm dương lịch); ở đây chỉ mô tả coverage.
Không ghi DB, không seed rule/evidence.
"""

from __future__ import annotations

import calendar
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.permissions import ROLE_PERMISSIONS
from app.db.session import utcnow
from app.models.core import User
from app.models.data import PoPackDaily, PoProgress, RevenueDaily, RevenueYearly, SyncRun
from app.models.roadmap import (
    COST_APPROVABLE_SOURCE_KINDS,
    COST_BLOCKED_SOURCE_KINDS,
    EXEC_APPROVABLE_SOURCE_KINDS,
    EXEC_BLOCKED_SOURCE_KINDS,
    MACHINE_PRICE_BASES,
    RoadmapCostEvidence,
    RoadmapExecutableRule,
)
from app.services import roadmap_baseline as rb
from app.services import roadmap_exec_rules as xr

STALE_DEFINITION = "stale_or_last_sync_failed = chưa từng có sync SUCCEEDED/PARTIAL, hoặc lần thử gần nhất FAILED. PARTIAL KHÔNG phải stale (semantics Task 5, không đổi)."


def _iso(v):
    return v.isoformat() if isinstance(v, date) else v


def _month_bounds(y: int, m: int) -> tuple[date, date]:
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _prev_month(y: int, m: int) -> tuple[int, int]:
    return (y - 1, 12) if m == 1 else (y, m - 1)


def _run_row(r: SyncRun) -> dict:
    return {"run_code": r.run_code, "status": r.status, "started_at": _iso(r.started_at) if r.started_at else None,
            "finished_at": _iso(r.finished_at) if r.finished_at else None, "total_records": r.total_records}


# ------------------------------------------------------------------ data quality (dùng lại engine baseline, không tự suy)
def data_quality(db: Session) -> dict:
    invalid = db.query(func.count(RevenueDaily.id)).filter(RevenueDaily.report_date < rb._INVALID_DATE_BEFORE).scalar() or 0
    years = [y for (y,) in db.query(RevenueYearly.year).distinct().order_by(RevenueYearly.year).all()]
    per_year = []
    inconsistent = 0
    for y in years:  # cùng hàm baseline mà Run dùng => cờ giống hệt Roadmap; không ghi gì
        flags: set[str] = set()
        statuses = {}
        for basis in ("PLAN", "ACTUAL"):
            b = rb.revenue_baseline(db, basis, "YEAR", y, None, "TOTAL", "")
            flags.update(b["flags"])
            statuses[basis] = b["status"]
        if "SOURCE_INCONSISTENT_PERIODS" in flags:
            inconsistent += 1
        per_year.append({"year": y, "status": statuses, "flags": sorted(flags)})
    return {"invalid_source_date_rows": int(invalid), "invalid_date_threshold": rb._INVALID_DATE_BEFORE.isoformat(), "years_with_inconsistent_periods": inconsistent, "revenue_yearly": per_year,
            "has_warnings": bool(invalid or inconsistent or any("PARTIAL_SOURCE_COVERAGE" in y["flags"] for y in per_year))}


# ------------------------------------------------------------------ OUTPUT coverage + FACTORY mapping (mô tả)
def output_coverage(db: Session) -> dict:
    dmin, dmax = db.query(func.min(PoPackDaily.day), func.max(PoPackDaily.day)).one()
    if dmin is None:
        return {"earliest_source_date": None, "latest_source_date": None, "latest_complete_month": None, "latest_partial_month": None, "year_coverage": [],
                "year_output_rule": "Chưa có dữ liệu po_pack_daily."}
    ly, lm = dmax.year, dmax.month
    ms, me = _month_bounds(ly, lm)
    partial = None
    if dmax < me or dmin > ms:  # tháng chứa ngày cuối chưa đủ ngày
        partial = f"{ly}-{lm:02d}"
        complete_y, complete_m = _prev_month(ly, lm)
    else:
        complete_y, complete_m = ly, lm
    cs, ce = _month_bounds(complete_y, complete_m)
    complete = f"{complete_y}-{complete_m:02d}" if (dmin <= cs and dmax >= ce) else None
    years = []
    for y in range(dmin.year, dmax.year + 1):
        full = dmin <= date(y, 1, 1) and dmax >= date(y, 12, 31)
        years.append({"year": y, "status": "COMPLETE" if full else "PARTIAL", "covered_from": _iso(max(dmin, date(y, 1, 1))), "covered_to": _iso(min(dmax, date(y, 12, 31)))})
    return {"earliest_source_date": _iso(dmin), "latest_source_date": _iso(dmax), "latest_complete_month": complete, "latest_partial_month": partial, "year_coverage": years,
            "year_output_rule": "OUTPUT_QTY theo YEAR chỉ CALCULATED khi po_pack_daily phủ đủ năm dương lịch (rule Task 5 — KHÔNG đổi). Trạng thái ở trên chỉ mô tả coverage."}


def factory_mapping(db: Session, year: int, month: int) -> dict:
    """Thống kê PO→XN cho 1 tháng: 'mapped' = PO có ≥1 dòng po_progress với factory_id (cùng định nghĩa `_po_factory_coverage` của engine). Mô tả — KHÔNG đổi FACTORY OUTPUT_QTY = PARTIAL_SOURCE."""
    start, end = _month_bounds(year, month)
    rows = db.query(PoPackDaily.po, PoPackDaily.qty).filter(PoPackDaily.day >= start, PoPackDaily.day <= end).all()
    pos = sorted({p for p, _ in rows})
    mapped: set[str] = set()
    for i in range(0, len(pos), 400):
        chunk = pos[i:i + 400]
        mapped.update(p for (p,) in db.query(PoProgress.po).filter(PoProgress.po.in_(chunk), PoProgress.factory_id.isnot(None)).distinct().all())
    total_qty = float(sum(q or 0 for _, q in rows))
    mapped_qty = float(sum(q or 0 for p, q in rows if p in mapped))
    mapped_rows = sum(1 for p, _ in rows if p in mapped)

    def pct(a, b):
        return None if not b else round(100.0 * a / b, 1)

    return {"period": f"{year}-{month:02d}", "rows": {"mapped": mapped_rows, "total": len(rows), "pct": pct(mapped_rows, len(rows))},
            "qty": {"mapped": mapped_qty, "total": total_qty, "pct": pct(mapped_qty, total_qty)}, "po": {"mapped": len(mapped), "total": len(pos), "pct": pct(len(mapped), len(pos))},
            "note": "Mô tả để minh bạch. FACTORY OUTPUT_QTY vẫn = PARTIAL_SOURCE trong Roadmap V1; ngưỡng mapping/đổi semantics là quyết định business riêng (Task 10 không thay đổi)."}


def source_health(db: Session, year: int | None = None, month: int | None = None) -> dict:
    fresh = rb.source_freshness(db)
    recent = db.query(SyncRun).filter(SyncRun.source == rb.SOURCE_SYNC_JOB).order_by(SyncRun.started_at.desc()).limit(8).all()
    counts: dict[str, int] = {}
    for r in recent:
        counts[r.status] = counts.get(r.status, 0) + 1
    cov = output_coverage(db)
    sel = None
    if year and month:
        sel = (year, month)
    elif cov["latest_complete_month"]:
        y, m = cov["latest_complete_month"].split("-")
        sel = (int(y), int(m))
    return {
        "generated_at": utcnow().isoformat(), "source_job": rb.SOURCE_SYNC_JOB, "stale_definition": STALE_DEFINITION,
        "latest_attempt": fresh["last_attempt"], "latest_usable": fresh["latest_success"], "source_age_hours": fresh["source_age_hours"],
        "roadmap_stale_flag": fresh["stale_or_last_sync_failed"], "recent_runs": [_run_row(r) for r in recent], "recent_status_counts": counts,
        "data_quality": data_quality(db), "output_coverage": cov, "factory_mapping": factory_mapping(db, *sel) if sel else None,
    }


# ------------------------------------------------------------------ production readiness (checklist)
def _item(key: str, label: str, status: str, count, message: str, detail: dict | None = None) -> dict:
    return {"key": key, "label": label, "status": status, "count": count, "message": message, "detail": detail or {}}


def production_readiness(db: Session) -> dict:
    today = utcnow().date()
    rules = db.query(RoadmapExecutableRule).filter(RoadmapExecutableRule.status == "APPROVED").all()
    labor_rules = [r for r in rules if r.proposal_type == "LABOR_RECRUITMENT"]
    machine_rules = [r for r in rules if r.proposal_type == "MACHINE_PURCHASE"]
    ev = db.query(RoadmapCostEvidence).filter(RoadmapCostEvidence.status == "APPROVED").all()
    machine_ev = [e for e in ev if e.cost_family == "MACHINE_UNIT_PRICE"]
    labor_ev = [e for e in ev if e.cost_family == "LABOR_COST_PER_WORKER_PERIOD"]
    approver_roles = [r for r, perms in ROLE_PERMISSIONS.items() if "roadmap.approve" in perms]
    approvers = db.query(User).filter(User.is_active.is_(True), User.role.in_(approver_roles)).count() if approver_roles else 0
    fresh = rb.source_freshness(db)
    dq = data_quality(db)

    def need(count: int, what: str, hint: str) -> tuple[str, str]:
        return ("READY", f"{count} {what} đã APPROVED.") if count else ("ACTION_REQUIRED", f"Chưa có {what} APPROVED — {hint}")

    items = []
    s, m = need(len(labor_rules), "executable rule LABOR", "Roadmap chưa tính được số lượng lao động; business cần khai báo + duyệt productivity (four-eyes).")
    items.append(_item("labor_rules", "Executable rule LABOR (approved)", s, len(labor_rules), m, {"effective_today": sum(1 for r in labor_rules if xr.is_effective(r, today))}))
    s, m = need(len(machine_rules), "executable rule MACHINE", "Roadmap chưa tính được số lượng máy.")
    items.append(_item("machine_rules", "Executable rule MACHINE (approved)", s, len(machine_rules), m, {"effective_today": sum(1 for r in machine_rules if xr.is_effective(r, today))}))
    s, m = need(len(machine_ev), "cost evidence giá máy", "mọi action MACHINE sẽ UNPRICED.")
    items.append(_item("machine_price_evidence", "Cost evidence giá máy (approved)", s, len(machine_ev), m))
    s, m = need(len(labor_ev), "cost evidence chi phí lao động", "mọi action LABOR sẽ UNPRICED.")
    items.append(_item("labor_cost_evidence", "Cost evidence chi phí lao động (approved)", s, len(labor_ev), m))
    if approvers >= 2:
        s, m = "READY", f"{approvers} user active có quyền roadmap.approve."
    elif approvers == 1:
        s, m = "WARNING", "Chỉ 1 user active có quyền roadmap.approve — nên có ≥ 2 (four-eyes + dự phòng)."
    else:
        s, m = "ACTION_REQUIRED", "Chưa có user active nào có roadmap.approve — không thể duyệt rule/evidence/plan/package."
    items.append(_item("approvers", "User có khả năng duyệt (roadmap.approve, active)", s, approvers, m, {"approver_roles": approver_roles}))
    if fresh["latest_success"] is None:
        s, m = "ACTION_REQUIRED", "Chưa từng có sync SUCCEEDED/PARTIAL — Roadmap chưa có nguồn dùng được."
    elif fresh["stale_or_last_sync_failed"]:
        s, m = "WARNING", "Lần thử sync gần nhất FAILED — Roadmap gắn cờ nguồn stale/failed."
    else:
        last = (fresh["last_attempt"] or {}).get("status")
        s, m = "READY", f"Sync gần nhất {last}, {fresh['source_age_hours']} giờ trước (PARTIAL không bị coi là stale)."
    items.append(_item("source_freshness", "Độ tươi nguồn (EGMF_REVENUE)", s, fresh["source_age_hours"], m, {"latest_attempt": fresh["last_attempt"], "latest_usable": fresh["latest_success"]}))
    if dq["has_warnings"]:
        s, m = "WARNING", f"{dq['invalid_source_date_rows']} dòng revenue_daily ngày không hợp lệ; {dq['years_with_inconsistent_periods']} năm có SOURCE_INCONSISTENT_PERIODS; kiểm tra revenue_yearly (mục Source Data Health)."
    else:
        s, m = "READY", "Không có cảnh báo chất lượng dữ liệu nguồn."
    items.append(_item("data_quality", "Cảnh báo chất lượng dữ liệu nguồn", s, dq["invalid_source_date_rows"], m))
    statuses = [i["status"] for i in items]
    overall = "ACTION_REQUIRED" if "ACTION_REQUIRED" in statuses else ("WARNING" if "WARNING" in statuses else "READY")
    return {"generated_at": utcnow().isoformat(), "overall": overall, "items": items, "help": help_text(),
            "note": "Checklist chỉ đọc — không seed rule/evidence thật. READY nghĩa là điều kiện phần mềm/dữ liệu đã đủ, không phải đã go-live."}


def help_text() -> dict:
    """Template/ví dụ dạng help text (KHÔNG insert DB)."""
    return {
        "executable_rule_fields": [
            "rule_code (duy nhất), adapter_code ∈ {LABOR_GAP_REQUIREMENT_V1, MACHINE_GAP_REQUIREMENT_V1}",
            "scope_type/scope_value (TOTAL hoặc FACTORY exact), period_type (MONTH|YEAR — phải khớp kỳ target, không quy đổi)",
            "productivity_value + productivity_unit (sp/worker/<PERIOD> hoặc sp/machine/<PERIOD>) — do business khai báo, KHÔNG suy từ bảng nguồn",
            "machine_type_code (bắt buộc với MACHINE; 1 rule = 1 loại máy), owner, source_kind, source_ref, effective_from(/to), assumptions",
            "sample_input + sample_expected: adapter chạy lại và phải khớp exact trước khi duyệt",
        ],
        "executable_rule_source_kinds": {"approvable": list(EXEC_APPROVABLE_SOURCE_KINDS), "blocked_at_approve": list(EXEC_BLOCKED_SOURCE_KINDS)},
        "cost_evidence_source_kinds": {"approvable": {k: list(v) for k, v in COST_APPROVABLE_SOURCE_KINDS.items()}, "blocked_at_approve": list(COST_BLOCKED_SOURCE_KINDS)},
        "price_basis_meaning": {
            "EX_WORKS_MACHINE_ONLY": "Giá máy tại xưởng nhà sản xuất — chưa gồm vận chuyển/thuế/lắp đặt.",
            "DELIVERED_MACHINE_ONLY": "Giá máy đã giao đến địa điểm — chỉ máy, không lắp đặt/đào tạo.",
            "CONTRACT_UNIT_PRICE_AS_QUOTED": "Đơn giá theo hợp đồng đúng như văn bản hợp đồng.",
            "BUDGET_STANDARD_UNIT_PRICE": "Đơn giá chuẩn theo ngân sách được duyệt.",
            "PURCHASE_HISTORY_UNIT_PRICE": "Đơn giá từ lịch sử mua có kiểm soát.",
            "note": "price_basis chỉ MÔ TẢ phạm vi thương mại; hệ thống chỉ tính số lượng × đơn giá, không cộng thuế/vận chuyển/lắp đặt.",
        },
        "labor_cost_evidence": "Chi phí mỗi người mỗi kỳ (MONTH|YEAR) theo scope TOTAL/FACTORY exact, nguồn HR_APPROVED_COST_STANDARD hoặc APPROVED_BUDGET_STANDARD; kỳ phải khớp kỳ action.",
        "four_eyes": "Người đưa vào review (reviewer) KHÔNG được là người duyệt (approver). Cần ≥ 2 tài khoản khác nhau; approver cần quyền roadmap.approve.",
        "workflow": "DRAFT → UNDER_REVIEW → APPROVED → RETIRED/ARCHIVED; APPROVED bất biến (sửa = version mới).",
    }


# ------------------------------------------------------------------ integrity check (snapshot/fingerprint) — chỉ đọc, dùng sau restore / định kỳ
def integrity_check(db: Session) -> dict:
    """Kiểm snapshot đã đóng băng: (1) Decision Package UNDER_REVIEW/APPROVED/ARCHIVED — fingerprint + tái định giá từ binding snapshot;
    (2) Action Plan version không còn DRAFT — coverage đóng băng khớp tính lại từ item snapshot + run immutable. Không ghi DB."""
    from app.models.roadmap import RoadmapActionPlanVersion, RoadmapDecisionPackage
    from app.services import roadmap_action_plan as ap
    from app.services import roadmap_decision_package as dp

    failures: list[dict] = []
    pkgs = db.query(RoadmapDecisionPackage).filter(RoadmapDecisionPackage.status != "DRAFT").order_by(RoadmapDecisionPackage.id).all()
    for p in pkgs:
        errs = dp.verify(db, p)
        if errs:
            failures.append({"object": "DecisionPackage", "id": p.id, "code": p.package_code, "errors": errs})
    vers = db.query(RoadmapActionPlanVersion).filter(RoadmapActionPlanVersion.status != "DRAFT").order_by(RoadmapActionPlanVersion.id).all()
    for v in vers:
        if not ap._same_json(ap.compute_coverage(db, v), v.coverage_json):
            failures.append({"object": "ActionPlanVersion", "id": v.id, "code": f"plan#{v.plan_id} v{v.version_no}", "errors": ["coverage đóng băng không khớp tính lại từ snapshot"]})
    return {"packages_checked": len(pkgs), "action_plan_versions_checked": len(vers), "failures": failures, "ok": not failures}
