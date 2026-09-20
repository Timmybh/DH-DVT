"""Tín hiệu cho sidebar phải của Dashboard (handoff mục 28).

Vùng trên  : Tin tốt / tín hiệu tích cực (GOOD)
Vùng dưới  : Cảnh báo / cần chú ý (WARN) — WARNING (cam) và CRITICAL (đỏ)
Mỗi tín hiệu có `drill` để bấm xem chi tiết. Dashboard chỉ là bề mặt tín hiệu; bằng chứng chi tiết nằm ở Sync Log.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import utcnow
from app.models.core import Factory
from app.services.dashboard import (
    current_batch,
    last_sync,
    progress_overview,
    revenue_overview,
    today_local,
)
from app.services.rules import parse_month

SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


def _fmt_dt(dt) -> str:
    from zoneinfo import ZoneInfo

    return dt.astimezone(ZoneInfo(settings.timezone)).strftime("%H:%M %d/%m")


def build_signals(db: Session, factories: list[Factory], is_total: bool, month: str | None) -> list[dict]:
    today = today_local()
    year, mon = parse_month(month, today)
    signals: list[dict] = []

    def add(sid, zone, severity, title, detail="", drill=None):
        signals.append({"id": sid, "zone": zone, "severity": severity, "title": title, "detail": detail, "drill": drill})

    # ---- Đồng bộ eGMF
    rev_run = last_sync(db, "EGMF_REVENUE")
    ok_run = None
    if rev_run is not None:
        from app.models.data import SyncRun

        ok_run = (
            db.query(SyncRun)
            .filter(SyncRun.source == "EGMF_REVENUE", SyncRun.status.in_(["SUCCEEDED", "PARTIAL"]))
            .order_by(SyncRun.started_at.desc())
            .first()
        )
    if rev_run is None:
        add("sync.never", "WARN", "WARNING", "Chưa từng đồng bộ dữ liệu eGMF", "Chạy đồng bộ trong màn hình Sync Log", {"kind": "sync_log"})
    else:
        drill = {"kind": "sync_run", "id": rev_run.id}
        if rev_run.status == "FAILED":
            add("sync.failed", "WARN", "CRITICAL", "Đồng bộ eGMF thất bại", (rev_run.error_message or "")[:160], drill)
        elif rev_run.status == "PARTIAL" or rev_run.unmatched or rev_run.ambiguous:
            add(
                "sync.unmatched",
                "WARN",
                "WARNING",
                f"{rev_run.unmatched + rev_run.ambiguous} bản ghi eGMF chưa khớp",
                f"{rev_run.run_code} · {rev_run.status}",
                drill,
            )
        if ok_run is not None:
            add(
                "sync.ok",
                "GOOD",
                "INFO",
                "Đồng bộ eGMF hoàn tất" if ok_run.status == "SUCCEEDED" else "Đồng bộ eGMF hoàn tất (một phần)",
                f"{ok_run.matched:,} bản ghi khớp · cập nhật {_fmt_dt(ok_run.finished_at or ok_run.started_at)}",
                {"kind": "sync_run", "id": ok_run.id},
            )
            age = utcnow() - (ok_run.finished_at or ok_run.started_at)
            if age > timedelta(hours=settings.sync_stale_hours):
                add(
                    "sync.stale",
                    "WARN",
                    "WARNING",
                    "Dữ liệu eGMF chưa được làm mới",
                    f"Lần đồng bộ thành công gần nhất: {_fmt_dt(ok_run.finished_at or ok_run.started_at)}",
                    {"kind": "sync_log"},
                )

    # ---- Doanh thu
    rev = revenue_overview(db, factories, year, mon, today)
    elapsed = rev["elapsed_pct"]
    period = f"{mon:02d}/{year}"
    has_revenue_data = rev["latest_actual_date"] is not None or any(r["month_declared"] for r in rev["by_factory"])
    for row in rev["by_factory"] if has_revenue_data else []:
        code = row["code"]
        if not row["month_declared"]:
            add(
                f"rev.undeclared.{code}",
                "WARN",
                "WARNING",
                f"{code} chưa khai báo doanh thu tháng {period}",
                "Cần khai báo trên ERP (Khai báo tháng)",
                {"kind": "revenue", "month": rev["month"]},
            )
            continue
        pct = row["month_pct"]
        if pct is None:
            continue
        gap = pct - elapsed
        if gap >= 0 and elapsed >= 10:
            add(
                f"rev.ahead.{code}",
                "GOOD",
                "INFO",
                f"{code} doanh thu vượt tiến độ tháng",
                f"Thực hiện {pct:.0f}% kế hoạch · thời gian đã qua {elapsed:.0f}%",
                {"kind": "revenue", "month": rev["month"]},
            )
        elif gap < -10:
            add(
                f"rev.gap.{code}",
                "WARN",
                "CRITICAL" if gap < -25 else "WARNING",
                f"{code} doanh thu thấp hơn tiến độ tháng",
                f"Thực hiện {pct:.0f}% kế hoạch · thời gian đã qua {elapsed:.0f}%",
                {"kind": "revenue", "month": rev["month"]},
            )

    latest = rev["latest_actual_date"]
    if (year, mon) == (today.year, today.month) and latest:
        from datetime import date

        lag = (today - date.fromisoformat(latest)).days
        if lag > 3:
            add(
                "rev.lag",
                "WARN",
                "WARNING",
                f"Doanh thu thực hiện chưa cập nhật {lag} ngày",
                f"Ngày có số liệu gần nhất: {date.fromisoformat(latest):%d/%m/%Y}",
                {"kind": "revenue", "month": rev["month"]},
            )

    # ---- Tiến độ / PO
    prog = progress_overview(db, factories, is_total)
    if prog.get("available"):
        risks = prog["risks"]
        planned = prog["pipeline"]["planned"]
        if risks["LATE"]:
            add(
                "po.late",
                "WARN",
                "CRITICAL" if prog["late_pct"] >= 15 else "WARNING",
                f"{risks['LATE']} PO có nguy cơ trễ hạn giao",
                f"EHD/CHD âm · chiếm {prog['late_pct']:.0f}% tổng PO",
                {"kind": "po", "risk": "LATE"},
            )
        if risks["MATERIAL"]:
            add(
                "po.material",
                "WARN",
                "WARNING",
                f"{risks['MATERIAL']} PO chưa sẵn sàng nguyên phụ liệu",
                "Ghi chú: chưa có vải / phụ liệu",
                {"kind": "po", "risk": "MATERIAL"},
            )
        if risks["ADVANCE"]:
            add(
                "po.advance",
                "GOOD",
                "INFO",
                f"{risks['ADVANCE']} PO hoàn thành sớm hơn kế hoạch",
                f"Trong {planned:,} PO đã xếp kế hoạch",
                {"kind": "po", "risk": "ADVANCE"},
            )
        if prog["mapping_warnings"]:
            add(
                "plan.mapping",
                "WARN",
                "WARNING",
                f"{prog['mapping_warnings']} dòng kế hoạch có cảnh báo mapping XN",
                "Dữ liệu nguồn (FAC/XN) cần rà soát — không ảnh hưởng trạng thái lên KH",
                {"kind": "po", "risk": "MAPPING"},
            )
        imported = current_batch(db).imported_at
        age_days = (utcnow() - imported).days
        if age_days > settings.plan_stale_days:
            add(
                "plan.stale",
                "WARN",
                "WARNING",
                f"File kế hoạch SX nhập lần cuối {age_days} ngày trước",
                f"{prog['batch']['filename']} · nhập {_fmt_dt(imported)}",
                {"kind": "sync_log"},
            )
    else:
        add("plan.missing", "WARN", "WARNING", "Chưa nhập file kế hoạch SX", "Nhập file Excel tại màn hình Sync Log", {"kind": "sync_log"})

    signals.sort(key=lambda s: SEVERITY_ORDER[s["severity"]])
    return signals
