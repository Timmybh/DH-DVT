from datetime import date

from pydantic import BaseModel


class IndicatorOut(BaseModel):
    indicator_key: str
    label: str
    status: str
    value: float | None
    threshold: float | None
    note: str


class FactoryPlanSeries(BaseModel):
    factory_code: str
    factory_name: str
    dates: list[date]
    plan: list[float]
    actual: list[float]
    completion_pct: list[float]


class GaugeOut(BaseModel):
    gauge_slot: int
    label: str
    unit: str
    value: float
    target: float | None


class IssueOut(BaseModel):
    id: int
    factory_name: str | None
    report_date: date
    title: str
    description: str
    severity: str
    status: str


class KpiConfigOut(BaseModel):
    id: int
    key: str
    label: str
    unit: str
    target_value: float | None
    warning_threshold_pct: float
    gauge_slot: int | None
    display_order: int
    is_active: bool


class KpiConfigUpdate(BaseModel):
    label: str
    unit: str
    target_value: float | None
    warning_threshold_pct: float
    gauge_slot: int | None
    display_order: int
    is_active: bool
