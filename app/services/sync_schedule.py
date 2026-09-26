"""Bảng đăng ký tần suất đồng bộ theo từng nguồn dữ liệu (snapshot).

- EGMF_FULL: lượt đồng bộ eGMF đầy đủ (doanh thu, tiến độ PO, QA, lao động, ...) — lịch nằm ở sync_config (giữ nguyên), chỉ hiển thị ở đây.
- Các nguồn nhẹ (vd HIPRO_LINE_OUTPUT: sản lượng tổ × mã hàng của ngày hôm nay) đăng ký ở bảng sync_schedules: chạy theo giờ cố định (DAILY)
  hoặc lặp theo chu kỳ phút trong khung giờ (INTERVAL). Kết quả lần chạy gần nhất ghi ngay trên dòng đăng ký (không tạo SyncRun mỗi 15–30 phút).
"""

import logging
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import utcnow
from app.models.data import SyncSchedule

log = logging.getLogger("dvt.sync_schedule")

MODES = ("DAILY", "INTERVAL")
MIN_INTERVAL, MAX_INTERVAL = 5, 1440
_HHMM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")

# Danh sách nguồn nhẹ có thể đăng ký: code → (tên, mô tả, mặc định)
SOURCES: dict[str, dict] = {
    "HIPRO_LINE_OUTPUT": {
        "name": "HiPro — sản lượng tổ × mã hàng (hôm nay)",
        "description": "pro_nscl → line_output_daily, chỉ lấy ngày hôm nay để Trang 2 có số trong ngày; lượt eGMF đầy đủ vẫn đối soát từ đầu tháng.",
        "defaults": {"enabled": True, "mode": "INTERVAL", "daily_time": "05:00", "interval_minutes": 30, "window_start": "06:00", "window_end": "20:00"},
    },
}


def ensure_defaults(db: Session) -> None:
    have = {r.code for r in db.query(SyncSchedule.code)}
    for code, spec in SOURCES.items():
        if code not in have:
            db.add(SyncSchedule(code=code, name=spec["name"], description=spec["description"], **spec["defaults"]))
    db.commit()


def _fmt_check(value: str, label: str) -> None:
    if not _HHMM.fullmatch(value or ""):
        raise HTTPException(422, f"{label} phải có dạng HH:MM (24 giờ)")


def validate_and_apply(row: SyncSchedule, data: dict, username: str) -> SyncSchedule:
    mode = data.get("mode", row.mode)
    if mode not in MODES:
        raise HTTPException(422, f"Chế độ phải là một trong: {', '.join(MODES)}")
    interval = int(data.get("interval_minutes", row.interval_minutes))
    if mode == "INTERVAL" and not MIN_INTERVAL <= interval <= MAX_INTERVAL:
        raise HTTPException(422, f"Chu kỳ phải từ {MIN_INTERVAL} đến {MAX_INTERVAL} phút")
    daily_time, ws, we = data.get("daily_time", row.daily_time), data.get("window_start", row.window_start), data.get("window_end", row.window_end)
    for value, label in ((daily_time, "Giờ chạy"), (ws, "Khung giờ bắt đầu"), (we, "Khung giờ kết thúc")):
        _fmt_check(value, label)
    if mode == "INTERVAL" and ws >= we:
        raise HTTPException(422, "Khung giờ kết thúc phải sau khung giờ bắt đầu")
    row.enabled, row.mode, row.interval_minutes = bool(data.get("enabled", row.enabled)), mode, interval
    row.daily_time, row.window_start, row.window_end = daily_time, ws, we
    row.updated_by, row.updated_at = username, utcnow()
    return row


def is_due(row: SyncSchedule, now: datetime) -> bool:
    """now là giờ địa phương (có tzinfo). Không chạy khi tắt; INTERVAL chỉ chạy trong khung giờ; DAILY mỗi ngày một lần sau giờ đặt."""
    if not row.enabled:
        return False
    hhmm = now.strftime("%H:%M")
    last = row.last_run_at.astimezone(now.tzinfo) if row.last_run_at else None
    if row.mode == "DAILY":
        return hhmm >= row.daily_time and (last is None or last.date() != now.date())
    if not (row.window_start <= hhmm <= row.window_end):
        return False
    return last is None or now - last >= timedelta(minutes=row.interval_minutes)


def _run_hipro_line_output(db: Session) -> dict:
    from app.services import hipro

    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return hipro.sync_line_output(db, today, None)


RUNNERS = {"HIPRO_LINE_OUTPUT": _run_hipro_line_output}


def run_one(db: Session, row: SyncSchedule) -> SyncSchedule:
    t0 = time.perf_counter()
    try:
        st = RUNNERS[row.code](db)
        db.commit()
        row.last_status, row.last_rows, row.last_error = "SUCCEEDED", st["read"], ""
        row.last_changed = st["inserted"] + st["updated"] + st["deleted"]
    except Exception as exc:  # noqa: BLE001 — một nguồn lỗi không được làm hỏng lượt đồng bộ khác
        db.rollback()
        log.exception("Đồng bộ nhẹ %s lỗi", row.code)
        row.last_status, row.last_rows, row.last_error = "FAILED", 0, f"{type(exc).__name__}: {str(exc)[:300]}"
    row.last_run_at, row.last_duration_ms = utcnow(), int((time.perf_counter() - t0) * 1000)
    db.commit()
    return row


def run_due(db: Session, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(ZoneInfo(settings.timezone))
    ran = []
    for row in db.query(SyncSchedule).order_by(SyncSchedule.code):
        if row.code in RUNNERS and is_due(row, now):
            run_one(db, row)
            ran.append(row.code)
    return ran


def view(row: SyncSchedule) -> dict:
    return {
        "code": row.code, "name": row.name, "description": row.description, "enabled": row.enabled, "mode": row.mode, "daily_time": row.daily_time,
        "interval_minutes": row.interval_minutes, "window_start": row.window_start, "window_end": row.window_end,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None, "last_status": row.last_status, "last_rows": row.last_rows, "last_changed": row.last_changed,
        "last_duration_ms": row.last_duration_ms, "last_error": row.last_error, "updated_by": row.updated_by,
    }
