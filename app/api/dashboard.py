from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import Factory, User
from app.core.permissions import permissions_for
from app.services import dashboard as svc
from app.services import dashboard_meta
from app.services import dashboard_page2
from app.services.rules import parse_month
from app.services.signals import build_signals

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

Viewer = Depends(require_perm("dashboard.view"))


@router.get("/meta")
def meta(db: Session = Depends(get_db), _: User = Viewer):
    fs = db.query(Factory).filter(Factory.is_active.is_(True)).order_by(Factory.display_order).all()
    return {
        "today": svc.today_local().isoformat(),
        "factories": [{"code": f.code, "name": f.name} for f in fs],
    }


def _revenue_summary_payload(db: Session, factories, is_total: bool, year: int, mon: int, today) -> dict:
    """Dashboard chính chỉ nhận bản tóm tắt điều hành; số liệu theo ngày nằm ở drill-down."""
    all_factories, _ = svc.scope_factories(db, "TONG")
    full = svc.revenue_overview(db, factories, year, mon, today)
    summary = svc.revenue_summary(db, all_factories, factories, is_total, year, mon)
    summary_ytd = svc.revenue_summary(db, all_factories, factories, is_total, year, mon, "ytd")
    return {
        "unit": full["unit"],
        "month": full["month"],
        "elapsed_pct": full["elapsed_pct"],
        "latest_actual_date": full["latest_actual_date"],
        "has_demo": summary["has_demo"] or summary_ytd["has_demo"] or full["has_demo"],
        "year": year,
        "summary": summary["rows"],
        "summary_ytd": summary_ytd["rows"],
    }


@router.get("/runtime")
def runtime(
    scope: str = "TONG",
    month: str | None = None,
    period: str = Query("MONTH", pattern="^(MONTH|YTD)$"),
    layout_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Viewer,
):
    """Dựng Dashboard từ metadata: chọn bố cục Published theo phạm vi, chạy các rule đã đăng ký, trả vị trí + dữ liệu.

    `layout_id` (xem trước bản nháp) chỉ dành cho người có quyền xem cấu hình; người dùng thường luôn nhận bố cục Published.
    """
    if layout_id is not None and "dashboard.config_view" not in permissions_for(user.role):
        raise HTTPException(403, "Không có quyền xem trước bố cục nháp")
    return dashboard_meta.build_runtime(db, user, scope, month, period, layout_id)


@router.get("/page2")
def page2(day: str | None = Query(None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"), db: Session = Depends(get_db), _: User = Viewer):
    """Trang 2: số liệu của ngày chọn (mặc định hôm nay) + chuỗi ngày trong tháng đến ngày đó."""
    from datetime import date as _date
    try:
        d = _date.fromisoformat(day) if day else svc.today_local()
    except ValueError:
        raise HTTPException(422, "Ngày không hợp lệ")
    return dashboard_page2.build(db, d)


@router.get("/overview")
def overview(scope: str = "TONG", month: str | None = None, db: Session = Depends(get_db), _: User = Viewer):
    today = svc.today_local()
    year, mon = parse_month(month, today)
    factories, is_total = svc.scope_factories(db, scope)
    return {
        "scope": "TONG" if is_total else factories[0].code,
        "scope_name": "Tổng công ty" if is_total else factories[0].name,
        "month": f"{year}-{mon:02d}",
        "today": today.isoformat(),
        "revenue": _revenue_summary_payload(db, factories, is_total, year, mon, today),
        "progress": svc.progress_overview(db, factories, is_total),
        "hr": svc.hr_overview(db, factories, is_total),
        "order_kpi": svc.order_kpi(db, factories, year, mon, today),
        "qa": svc.qa_summary(db, svc.scope_factories(db, "TONG")[0], factories, is_total, year, mon),
        "sync": {
            "revenue": svc.sync_brief(svc.last_sync(db, "EGMF_REVENUE")),
            "plan": svc.sync_brief(svc.last_sync(db, "PLAN_EXCEL")),
        },
    }


@router.get("/signals")
def signals(scope: str = "TONG", month: str | None = None, db: Session = Depends(get_db), _: User = Viewer):
    factories, is_total = svc.scope_factories(db, scope)
    items = build_signals(db, factories, is_total, month)
    return {
        "good": [s for s in items if s["zone"] == "GOOD"],
        "warn": [s for s in items if s["zone"] == "WARN"],
    }


@router.get("/drill/po")
def drill_po(
    scope: str = "TONG",
    risk: str = Query("ALL", pattern="^(ALL|OK|ADVANCE|LATE|MATERIAL|UNPLANNED|UNASSIGNED|MAPPING)$"),
    db: Session = Depends(get_db),
    _: User = Viewer,
):
    factories, is_total = svc.scope_factories(db, scope)
    return svc.drill_po(db, factories, is_total, risk)


@router.get("/drill/revenue")
def drill_revenue(scope: str = "TONG", month: str | None = None, db: Session = Depends(get_db), _: User = Viewer):
    today = svc.today_local()
    year, mon = parse_month(month, today)
    factories, _is_total = svc.scope_factories(db, scope)
    return svc.drill_revenue(db, factories, year, mon)


@router.get("/drill/order")
def drill_order(
    scope: str = "TONG",
    kind: str = Query("SEWING", pattern="^(SEWING|FG)$"),
    status: str = Query("LATE", pattern="^(ON_TIME|LATE|NO_DUE|OVERDUE)$"),
    month: str | None = None,
    db: Session = Depends(get_db),
    _: User = Viewer,
):
    today = svc.today_local()
    year, mon = parse_month(month, today)
    factories, _is_total = svc.scope_factories(db, scope)
    return svc.drill_order(db, factories, kind, status, year, mon, today)


@router.get("/drill/qa")
def drill_qa(category: str = Query("ALL", pattern="^(ALL|INLINE|ENDLINE|PREFINAL)$"), month: str | None = None, db: Session = Depends(get_db), _: User = Viewer):
    year, mon = parse_month(month, svc.today_local())
    return svc.drill_qa(db, svc.scope_factories(db, "TONG")[0], category, year, mon)


@router.get("/drill/hr")
def drill_hr(scope: str = "TONG", db: Session = Depends(get_db), _: User = Viewer):
    factories, is_total = svc.scope_factories(db, scope)
    return svc.drill_hr(db, factories, is_total)
