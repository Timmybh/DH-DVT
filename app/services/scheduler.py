"""Job nền: mỗi phút kiểm tra tới giờ thì chạy đồng bộ eGMF (1 lần/ngày)."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import or_, update

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.core import SyncConfig
from app.services.egmf import run_revenue_sync
from app.services.sync_core import SyncBusy

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _tick_light() -> None:
    """Các nguồn nhẹ đăng ký ở sync_schedules (vd HiPro sản lượng hôm nay) — độc lập với lượt eGMF đầy đủ."""
    try:
        from app.services import sync_schedule

        with SessionLocal() as db:
            sync_schedule.run_due(db)
    except Exception:  # noqa: BLE001
        log.exception("Lỗi job đồng bộ nhẹ")


def _tick() -> None:
    _tick_light()
    try:
        with SessionLocal() as db:
            cfg = db.get(SyncConfig, 1)
            if cfg is None or not cfg.enabled:
                return
            now = datetime.now(ZoneInfo(settings.timezone))
            if now.strftime("%H:%M") < cfg.scheduled_time:
                return
            claimed = db.execute(
                update(SyncConfig)
                .where(SyncConfig.id == 1, or_(SyncConfig.last_scheduled_date.is_(None), SyncConfig.last_scheduled_date != now.date()))
                .values(last_scheduled_date=now.date())
            )
            db.commit()
            if claimed.rowcount == 0:
                return
            log.info("Đến giờ đồng bộ eGMF theo lịch (%s)", cfg.scheduled_time)
            run_revenue_sync(db, trigger="SCHEDULED", username="")
    except SyncBusy:
        log.info("Bỏ qua lượt đồng bộ theo lịch vì đang có phiên khác chạy")
    except Exception:  # noqa: BLE001
        log.exception("Lỗi job đồng bộ theo lịch")


def start_scheduler() -> None:
    global _scheduler
    if not settings.scheduler_enabled or _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone=settings.timezone)
    # next_run_time: chạy 1 lượt ngay khi tiến trình khởi động để bắt kịp lịch đã lỡ (IIS có thể recycle/idle-stop tiến trình)
    _scheduler.add_job(
        _tick,
        "interval",
        seconds=60,
        id="daily-egmf-sync",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(ZoneInfo(settings.timezone)) + timedelta(seconds=20),
    )
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
