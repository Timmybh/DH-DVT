from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.factory import Factory
from app.models.importjob import ImportJob
from app.models.indicator import IndicatorStatus, IssueItem
from app.models.kpi import GaugeMetric, KpiConfig
from app.models.plan import PlanProgress
from app.schemas.dashboard import (
    FactoryPlanSeries,
    GaugeOut,
    IndicatorOut,
    IssueOut,
    KpiConfigOut,
    KpiConfigUpdate,
)
from app.schemas.importjob import ImportJobOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)])

INDICATOR_LABELS = {
    "SX": "Tiến độ SX",
    "DONGGOI": "Đóng gói",
    "GIAOHANG": "Giao hàng",
    "QA": "QA",
    "VUONGMAC": "Vướng mắc",
}


@router.get("/last-sync", response_model=ImportJobOut | None)
def get_last_sync(db: Session = Depends(get_db)):
    return db.query(ImportJob).order_by(ImportJob.started_at.desc()).first()


@router.get("/indicators", response_model=list[IndicatorOut])
def get_indicators(report_date: date = Query(default_factory=date.today), db: Session = Depends(get_db)):
    rows = (
        db.query(IndicatorStatus)
        .filter(IndicatorStatus.report_date == report_date, IndicatorStatus.factory_id.is_(None))
        .all()
    )
    by_key = {r.indicator_key: r for r in rows}

    result = []
    for key, label in INDICATOR_LABELS.items():
        row = by_key.get(key)
        result.append(
            IndicatorOut(
                indicator_key=key,
                label=label,
                status=row.status if row else "RED",
                value=row.value if row else None,
                threshold=row.threshold if row else None,
                note=row.note if row else "Chưa có dữ liệu",
            )
        )
    return result


@router.get("/plan-chart", response_model=list[FactoryPlanSeries])
def get_plan_chart(
    days: int = Query(default=14, ge=1, le=90),
    end_date: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
):
    start_date = end_date - timedelta(days=days - 1)
    factories = db.query(Factory).order_by(Factory.display_order).all()

    series: list[FactoryPlanSeries] = []
    for factory in factories:
        rows = (
            db.query(PlanProgress)
            .filter(
                PlanProgress.factory_id == factory.id,
                PlanProgress.report_date >= start_date,
                PlanProgress.report_date <= end_date,
            )
            .order_by(PlanProgress.report_date)
            .all()
        )
        by_date = {r.report_date: r for r in rows}

        dates, plan, actual, pct = [], [], [], []
        d = start_date
        while d <= end_date:
            row = by_date.get(d)
            dates.append(d)
            plan.append(row.plan_qty if row else 0)
            actual.append(row.actual_qty if row else 0)
            pct.append(row.completion_pct if row else 0)
            d += timedelta(days=1)

        series.append(
            FactoryPlanSeries(
                factory_code=factory.code,
                factory_name=factory.name,
                dates=dates,
                plan=plan,
                actual=actual,
                completion_pct=pct,
            )
        )
    return series


@router.get("/gauges", response_model=list[GaugeOut])
def get_gauges(report_date: date = Query(default_factory=date.today), db: Session = Depends(get_db)):
    configs = (
        db.query(KpiConfig)
        .filter(KpiConfig.gauge_slot.isnot(None))
        .order_by(KpiConfig.gauge_slot)
        .all()
    )
    config_by_slot = {c.gauge_slot: c for c in configs}

    result = []
    for slot in range(1, 11):
        cfg = config_by_slot.get(slot)
        if cfg is None:
            result.append(GaugeOut(gauge_slot=slot, label=f"Gauge {slot}", unit="", value=0, target=None))
            continue

        metric = (
            db.query(GaugeMetric)
            .filter(GaugeMetric.kpi_config_id == cfg.id, GaugeMetric.report_date == report_date)
            .first()
        )
        result.append(
            GaugeOut(
                gauge_slot=slot,
                label=cfg.label,
                unit=cfg.unit,
                value=metric.value if metric else 0,
                target=metric.target if metric else cfg.target_value,
            )
        )
    return result


@router.get("/issues", response_model=list[IssueOut])
def get_issues(
    report_date: date = Query(default_factory=date.today),
    factory_code: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(IssueItem).filter(IssueItem.report_date == report_date)
    if factory_code:
        factory = db.query(Factory).filter(Factory.code == factory_code).first()
        if factory:
            query = query.filter(IssueItem.factory_id == factory.id)

    items = query.order_by(IssueItem.severity.desc(), IssueItem.created_at.desc()).all()
    return [
        IssueOut(
            id=i.id,
            factory_name=i.factory.name if i.factory_id and i.factory else None,
            report_date=i.report_date,
            title=i.title,
            description=i.description,
            severity=i.severity,
            status=i.status,
        )
        for i in items
    ]


@router.get("/kpi-config", response_model=list[KpiConfigOut])
def list_kpi_config(db: Session = Depends(get_db)):
    return db.query(KpiConfig).order_by(KpiConfig.display_order).all()


@router.put("/kpi-config/{kpi_id}", response_model=KpiConfigOut, dependencies=[Depends(require_admin)])
def update_kpi_config(kpi_id: int, payload: KpiConfigUpdate, db: Session = Depends(get_db)):
    from fastapi import HTTPException

    cfg = db.get(KpiConfig, kpi_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy KPI")

    cfg.label = payload.label
    cfg.unit = payload.unit
    cfg.target_value = payload.target_value
    cfg.warning_threshold_pct = payload.warning_threshold_pct
    cfg.gauge_slot = payload.gauge_slot
    cfg.display_order = payload.display_order
    cfg.is_active = payload.is_active
    db.commit()
    db.refresh(cfg)
    return cfg
