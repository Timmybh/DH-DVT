"""Quản lý vòng đời SyncRun (dùng chung cho mọi nguồn đồng bộ)."""

import logging
import time
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import utcnow
from app.models.data import SyncRun, SyncRunItem
from app.services.audit import new_trace_id, write_audit

log = logging.getLogger(__name__)

MAX_ITEMS_PER_KIND = 300
RUNNING_TIMEOUT_MINUTES = 15


class SyncBusy(Exception):
    def __init__(self, run_code: str):
        super().__init__(f"Đang có phiên đồng bộ chạy: {run_code}")
        self.run_code = run_code


def _next_run_code(db: Session) -> str:
    ymd = utcnow().astimezone(ZoneInfo(settings.timezone)).strftime("%Y%m%d")
    count = db.query(func.count(SyncRun.id)).filter(SyncRun.run_code.like(f"SYNC-{ymd}-%")).scalar() or 0
    return f"SYNC-{ymd}-{count + 1:04d}"


def start_run(db: Session, source: str, trigger: str, username: str, retry_of: int | None = None) -> SyncRun:
    busy = (
        db.query(SyncRun)
        .filter(SyncRun.status == "RUNNING", SyncRun.started_at > utcnow() - timedelta(minutes=RUNNING_TIMEOUT_MINUTES))
        .first()
    )
    if busy:
        raise SyncBusy(busy.run_code)

    for _ in range(3):
        run = SyncRun(
            run_code=_next_run_code(db),
            source=source,
            trigger_type=trigger,
            status="RUNNING",
            triggered_by=username,
            trace_id=new_trace_id(),
            retry_of=retry_of,
        )
        db.add(run)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        db.refresh(run)
        write_audit(
            "SYNC_RETRY" if trigger == "RETRY" else "SYNC_RUN",
            username=username or "scheduler",
            object_type="SyncRun",
            object_id=run.run_code,
            detail=f"source={source} trigger={trigger}",
            trace_id=run.trace_id,
        )
        return run
    raise RuntimeError("Không tạo được mã phiên đồng bộ")


def add_items(db: Session, run_id: int, kind: str, source_object: str, entries: list[tuple[str, str, dict]]) -> None:
    """entries: (source_key, message, payload). Giới hạn số dòng lưu để tránh phình DB."""
    for key, message, payload in entries[:MAX_ITEMS_PER_KIND]:
        db.add(SyncRunItem(run_id=run_id, kind=kind, source_object=source_object, source_key=key, message=message, payload=payload))
    if len(entries) > MAX_ITEMS_PER_KIND:
        db.add(
            SyncRunItem(
                run_id=run_id,
                kind="INFO",
                source_object=source_object,
                message=f"... và {len(entries) - MAX_ITEMS_PER_KIND} dòng {kind} khác không hiển thị chi tiết",
            )
        )


def finish_run(db: Session, run: SyncRun, started_perf: float, status: str | None = None) -> SyncRun:
    if status is None:
        status = "SUCCEEDED" if run.unmatched == 0 and run.ambiguous == 0 else "PARTIAL"
    run.status = status
    run.finished_at = utcnow()
    run.duration_ms = int((time.perf_counter() - started_perf) * 1000)
    db.commit()
    db.refresh(run)
    return run


def fail_run(db: Session, run_id: int, started_perf: float, exc: Exception, friendly: str | None = None) -> SyncRun:
    db.rollback()
    log.exception("Sync %s thất bại", run_id)
    run = db.get(SyncRun, run_id)
    technical = f"{type(exc).__name__}: {str(exc)}"
    message = friendly or technical
    run.error_message = message[:1800]
    db.add(SyncRunItem(run_id=run.id, kind="ERROR", source_object=run.source, message=technical[:1800]))
    write_audit(
        "SYNC_FAILED",
        username=run.triggered_by or "scheduler",
        object_type="SyncRun",
        object_id=run.run_code,
        result="FAILED",
        detail=message[:500],
        trace_id=run.trace_id,
    )
    return finish_run(db, run, started_perf, status="FAILED")


def recover_stale_runs(db: Session) -> None:
    """Đánh dấu FAILED các run RUNNING bị bỏ dở (server restart)."""
    stale = db.query(SyncRun).filter(SyncRun.status == "RUNNING").all()
    for run in stale:
        run.status = "FAILED"
        run.finished_at = utcnow()
        run.error_message = "Phiên bị gián đoạn do dịch vụ khởi động lại"
    if stale:
        db.commit()
