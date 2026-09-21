"""Rule Registry của Dashboard — WHITELIST cố định trong code.

Admin chỉ chọn `rule_code` đã đăng ký ở đây. Không nhập đường dẫn file, không upload Python, không import động theo chuỗi.
Mỗi rule là hàm ``fn(ctx: DashboardContext) -> dict`` trả về `payload` (dữ liệu cho renderer); executor bọc lại thành output
contract chuẩn ``{status, payload, items, value, label, drilldown, meta}`` và cô lập lỗi từng rule (không làm sập Dashboard).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import utcnow
from app.models.core import Factory, User
from app.services import dashboard as svc
from app.services.rules import parse_month
from app.services.signals import build_signals

STATUSES = ("OK", "EMPTY", "WARNING", "ERROR", "STALE")


@dataclass
class DashboardContext:
    db: Session
    scope: str  # TONG | XN1..
    month: str | None = None
    period: str = "MONTH"  # MONTH | YTD (renderer có thể đổi kỳ ở client)
    user: User | None = None
    filters: dict = field(default_factory=dict)
    indicator_config: dict = field(default_factory=dict)
    layout_config_override: dict = field(default_factory=dict)
    current_date: date = field(default_factory=svc.today_local)
    # Được điền sẵn để mọi rule dùng chung, tránh truy vấn lặp
    factories: list[Factory] = field(default_factory=list)
    all_factories: list[Factory] = field(default_factory=list)
    is_total: bool = True
    year: int = 0
    mon: int = 0

    def prepare(self) -> "DashboardContext":
        self.factories, self.is_total = svc.scope_factories(self.db, self.scope)
        self.all_factories = svc.scope_factories(self.db, "TONG")[0]
        self.year, self.mon = parse_month(self.month, self.current_date)
        return self


# ------------------------------------------------------------------ rule bọc logic nghiệp vụ hiện có (không viết lại tính toán)
def build_revenue_summary(ctx: DashboardContext) -> dict:
    full = svc.revenue_overview(ctx.db, ctx.factories, ctx.year, ctx.mon, ctx.current_date)
    summary = svc.revenue_summary(ctx.db, ctx.all_factories, ctx.factories, ctx.is_total, ctx.year, ctx.mon)
    summary_ytd = svc.revenue_summary(ctx.db, ctx.all_factories, ctx.factories, ctx.is_total, ctx.year, ctx.mon, "ytd")
    return {
        "unit": full["unit"], "month": full["month"], "elapsed_pct": full["elapsed_pct"], "latest_actual_date": full["latest_actual_date"],
        "has_demo": summary["has_demo"] or summary_ytd["has_demo"] or full["has_demo"], "year": ctx.year,
        "summary": summary["rows"], "summary_ytd": summary_ytd["rows"],
    }


def build_order_progress_matrix(ctx: DashboardContext) -> dict:
    return svc.order_kpi(ctx.db, ctx.factories, ctx.year, ctx.mon, ctx.current_date)


def build_po_risk_pipeline(ctx: DashboardContext) -> dict:
    return svc.progress_overview(ctx.db, ctx.factories, ctx.is_total)


def build_qa_summary(ctx: DashboardContext) -> dict:
    return svc.qa_summary(ctx.db, ctx.all_factories, ctx.factories, ctx.is_total, ctx.year, ctx.mon)


def build_hr_headcount(ctx: DashboardContext) -> dict:
    return svc.hr_overview(ctx.db, ctx.factories, ctx.is_total)


def _signals(ctx: DashboardContext, zone: str) -> dict:
    items = [s for s in build_signals(ctx.db, ctx.factories, ctx.is_total, ctx.month) if s["zone"] == zone]
    return {"zone": zone, "items": items, "count": len(items), "critical": sum(1 for s in items if s["severity"] == "CRITICAL")}


def build_good_news(ctx: DashboardContext) -> dict:
    return _signals(ctx, "GOOD")


def build_warnings(ctx: DashboardContext) -> dict:
    return _signals(ctx, "WARN")


def build_output_today(ctx: DashboardContext) -> dict:
    return svc.output_today(ctx.db, ctx.factories, ctx.current_date)


def build_rft_today(ctx: DashboardContext) -> dict:
    return svc.rft_today(ctx.factories)


def build_efficiency_today(ctx: DashboardContext) -> dict:
    return svc.efficiency_today(ctx.factories)


def build_static_text(ctx: DashboardContext) -> dict:
    """Widget Văn bản / Tiêu đề (Layout Designer): nội dung do người thiết kế nhập ở cấu hình widget, không truy vấn dữ liệu."""
    return {"text": str(ctx.indicator_config.get("text", "")), "heading": bool(ctx.indicator_config.get("heading", False))}


@dataclass(frozen=True)
class RuleInfo:
    code: str
    name: str
    fn: Callable[[DashboardContext], dict]
    module: str
    function: str
    description: str
    input_contract: str = "DashboardContext: scope (TONG|XNn), month (YYYY-MM), period, user, filters, indicator_config, layout_config_override"
    output_contract: str = "{status: OK|EMPTY|WARNING|ERROR|STALE, payload: object, meta: {last_calculated_at, data_freshness, rule_version}}"
    version: str = "1"
    source: str = "eGMF"  # eGMF | Excel  (dùng để tính độ tươi dữ liệu)


_INFOS = [
    RuleInfo("REVENUE_EXECUTIVE_SUMMARY", "Doanh thu — tóm tắt điều hành", build_revenue_summary, "app.dashboard_rules", "build_revenue_summary",
             "XN1/XN2/XN3 + Tổng công ty (Tổng công ty luôn cộng dồn); xem khung XN: XN đang chọn + Tổng. Tháng và Lũy kế."),
    RuleInfo("ORDER_PROGRESS_MATRIX", "Tiến độ đơn hàng — ma trận Đúng hạn/Trễ", build_order_progress_matrix, "app.dashboard_rules", "build_order_progress_matrix",
             "PO hoàn thành trong tháng: May xong / Nhập kho TP × Đúng hạn / Trễ."),
    RuleInfo("PO_RISK_PIPELINE", "Tiến độ kế hoạch — rủi ro giao hàng", build_po_risk_pipeline, "app.dashboard_rules", "build_po_risk_pipeline",
             "Số PO trong kế hoạch theo rủi ro giao hàng (từ file Excel kế hoạch SX).", source="Excel"),
    RuleInfo("QA_COMPARISON", "QA — Total Defect Count", build_qa_summary, "app.dashboard_rules", "build_qa_summary",
             "Tổng số lỗi theo nhóm kiểm tra (Đầu chuyền, QC, Inline, Endline, Prefinal) và xí nghiệp."),
    RuleInfo("HR_HEADCOUNT", "Nhân sự — lao động theo XN/tổ", build_hr_headcount, "app.dashboard_rules", "build_hr_headcount",
             "Lao động có mặt theo xí nghiệp/tổ (từ file Excel kế hoạch SX).", source="Excel"),
    RuleInfo("GOOD_NEWS", "Tin tốt", build_good_news, "app.dashboard_rules", "build_good_news", "Các tín hiệu tích cực (khu 'Tin tốt')."),
    RuleInfo("OUTPUT_TODAY", "Sản lượng hôm nay", build_output_today, "app.dashboard_rules", "build_output_today",
             "Sản lượng may ra hôm nay theo xí nghiệp so với kế hoạch hôm nay (Gauge)."),
    RuleInfo("RFT_TODAY", "RFT hôm nay", build_rft_today, "app.dashboard_rules", "build_rft_today",
             "RFT hôm nay theo xí nghiệp (tạm số cố định, sẽ lấy từ DB hiPro)."),
    RuleInfo("EFFICIENCY_TODAY", "Hiệu suất hôm nay", build_efficiency_today, "app.dashboard_rules", "build_efficiency_today",
             "Hiệu suất hôm nay theo xí nghiệp (tạm số cố định, sẽ tính từ sản lượng × SAM)."),
    RuleInfo("STATIC_TEXT", "Văn bản / Tiêu đề", build_static_text, "app.dashboard_rules", "build_static_text", "Đoạn văn bản hoặc tiêu đề tĩnh do người thiết kế bố cục nhập.", source="Manual"),
    RuleInfo("WARNING_SIGNALS", "Cảnh báo / cần chú ý", build_warnings, "app.dashboard_rules", "build_warnings", "Các tín hiệu cảnh báo và mức nghiêm trọng."),
]

RULES: dict[str, RuleInfo] = {i.code: i for i in _INFOS}


def register_for_tests(info: RuleInfo) -> None:  # chỉ dùng trong test để thêm rule giả; không có đường dẫn nào cho Admin gọi
    RULES[info.code] = info


def _freshness(ctx: DashboardContext, info: RuleInfo, requirement_hours: float | None) -> dict:
    source = "PLAN_EXCEL" if info.source == "Excel" else "EGMF_REVENUE"
    run = svc.last_sync(ctx.db, source)
    if run is None:
        return {"data_freshness": "UNKNOWN", "source_last_sync_at": None}
    started = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=timezone.utc)
    if requirement_hours is None:
        return {"data_freshness": "FRESH", "source_last_sync_at": started.isoformat()}
    stale = utcnow() - started > timedelta(hours=requirement_hours)
    return {"data_freshness": "STALE" if stale else "FRESH", "source_last_sync_at": started.isoformat()}


def execute_rule(rule_code: str, ctx: DashboardContext, freshness_hours: float | None = None) -> dict:
    """Chạy một rule đã đăng ký và trả về output contract chuẩn. Mọi lỗi được cô lập thành status=ERROR."""
    info = RULES.get(rule_code)
    started = time.perf_counter()
    if info is None:
        return {"status": "ERROR", "message": f"Rule '{rule_code}' chưa được đăng ký trong code", "payload": None, "items": [], "drilldown": {},
                "meta": {"rule_version": "", "last_calculated_at": datetime.now(timezone.utc).isoformat(), "data_freshness": "UNKNOWN", "duration_ms": 0}}
    try:
        payload = info.fn(ctx)
        empty = isinstance(payload, dict) and (payload.get("has_data") is False or payload.get("available") is False)
        fresh = _freshness(ctx, info, freshness_hours)
        status = "EMPTY" if empty else ("STALE" if fresh["data_freshness"] == "STALE" else "OK")
        items = payload.get("items", []) if isinstance(payload, dict) else []
        return {
            "status": status, "payload": payload, "items": items, "value": None, "label": "", "drilldown": {},
            "meta": {"rule_version": info.version, "last_calculated_at": datetime.now(timezone.utc).isoformat(), "duration_ms": int((time.perf_counter() - started) * 1000), **fresh},
        }
    except Exception as exc:  # noqa: BLE001 - cô lập lỗi: một widget hỏng không làm hỏng cả Dashboard
        ctx.db.rollback()
        return {"status": "ERROR", "message": str(exc)[:200], "payload": None, "items": [], "drilldown": {},
                "meta": {"rule_version": info.version, "last_calculated_at": datetime.now(timezone.utc).isoformat(), "data_freshness": "UNKNOWN",
                         "duration_ms": int((time.perf_counter() - started) * 1000)}}


__all__ = ["DashboardContext", "RULES", "RuleInfo", "execute_rule", "STATUSES", "settings"]
