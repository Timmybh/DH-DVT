from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import Factory, User
from app.services import dashboard as svc
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
        "revenue": svc.revenue_overview(db, factories, year, mon, today),
        "progress": svc.progress_overview(db, factories, is_total),
        "hr": svc.hr_overview(db, factories, is_total),
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
    risk: str = Query("ALL", pattern="^(ALL|OK|ADVANCE|LATE|MATERIAL)$"),
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


@router.get("/drill/hr")
def drill_hr(scope: str = "TONG", db: Session = Depends(get_db), _: User = Viewer):
    factories, is_total = svc.scope_factories(db, scope)
    return svc.drill_hr(db, factories, is_total)
