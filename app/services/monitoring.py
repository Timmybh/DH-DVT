"""Giám sát vận hành: tình trạng DB, đồng bộ, lịch chạy nền, độ mới dữ liệu, bảo mật đăng nhập, dung lượng — và danh sách cảnh báo suy ra từ đó."""

import platform
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import utcnow
from app.models.actual import ActualMapping, ActualObservation
from app.models.core import AuditLog, User
from app.models.data import PlanImportBatch, RevenueDaily, SyncRun
from app.models.labor_snapshot import LaborSnapshot
from app.models.lifecycle import YearArchive
from app.models.planning import PlanningEditSession, PlanningVersion, PlanningVersionRow
from app.services import lifecycle

STARTED_AT = time.time()
SOURCES = ("EGMF_REVENUE", "PLAN_EXCEL")


def _age_hours(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((utcnow() - dt).total_seconds() / 3600, 1)


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def snapshot(db: Session) -> dict:
    alerts: list[dict] = []

    def alert(sev: str, code: str, msg: str):
        alerts.append({"severity": sev, "code": code, "message": msg})

    # ---- cơ sở dữ liệu
    t0 = time.perf_counter()
    db.execute(text("select 1"))
    ping_ms = round((time.perf_counter() - t0) * 1000, 1)
    size = None
    try:
        size = db.execute(text("select pg_database_size(current_database())")).scalar()
    except Exception:  # noqa: BLE001 - không phải PostgreSQL
        db.rollback()
    if ping_ms > 500:
        alert("WARNING", "DB_SLOW", f"Truy vấn kiểm tra DB mất {ping_ms} ms (> 500 ms)")

    # ---- đồng bộ
    sync = []
    for src in SOURCES:
        last = db.query(SyncRun).filter(SyncRun.source == src).order_by(SyncRun.started_at.desc()).first()
        ok = db.query(SyncRun).filter(SyncRun.source == src, SyncRun.status.in_(("SUCCEEDED", "PARTIAL"))).order_by(SyncRun.started_at.desc()).first()
        age = _age_hours(ok.started_at) if ok else None
        sync.append({"source": src, "last_status": last.status if last else None, "last_run": last.run_code if last else None, "last_at": last.started_at.isoformat() if last else None,
                     "last_success_age_hours": age, "duration_ms": last.duration_ms if last else None})
        if src == "EGMF_REVENUE":
            if ok is None:
                alert("WARNING", "SYNC_NEVER", "Chưa có lần đồng bộ ERP thành công nào")
            elif age is not None and age > settings.sync_stale_hours:
                alert("ERROR", "SYNC_STALE", f"Lần đồng bộ ERP thành công gần nhất cách đây {age:.0f} giờ (> {settings.sync_stale_hours} giờ)")
            if last is not None and last.status == "FAILED":
                alert("ERROR", "SYNC_FAILED", f"Lần đồng bộ gần nhất {last.run_code} thất bại")
    failed_24h = db.query(func.count(SyncRun.id)).filter(SyncRun.status == "FAILED", SyncRun.started_at >= utcnow() - timedelta(hours=24)).scalar() or 0

    # ---- lịch chạy nền
    from app.services import scheduler

    running = bool(scheduler._scheduler is not None and getattr(scheduler._scheduler, "running", False))
    if settings.scheduler_enabled and not running:
        alert("ERROR", "SCHEDULER_DOWN", "Lịch đồng bộ nền được bật nhưng không chạy")

    # ---- độ mới dữ liệu
    batch = db.query(PlanImportBatch).filter(PlanImportBatch.is_current.is_(True)).order_by(PlanImportBatch.id.desc()).first()
    plan_h = _age_hours(batch.imported_at) if batch else None
    plan_age_days = round(plan_h / 24, 1) if plan_h is not None else None
    if plan_age_days is not None and plan_age_days > settings.plan_stale_days:
        alert("WARNING", "PLAN_STALE", f"File kế hoạch nhập lần cuối cách đây {plan_age_days:.0f} ngày (> {settings.plan_stale_days} ngày)")
    last_obs = db.query(func.max(ActualObservation.observed_at)).scalar()
    latest_rev = db.query(func.max(RevenueDaily.report_date)).scalar()
    snap = db.query(LaborSnapshot).order_by(LaborSnapshot.as_of_date.desc(), LaborSnapshot.id.desc()).first()
    if snap is None:
        alert("INFO", "NO_LABOR_SNAPSHOT", "Chưa có ảnh chụp lao động — Dashboard nhân sự đang dùng số liệu file Excel")
    ref = db.query(PlanningVersion).filter(PlanningVersion.status == "ISSUED").order_by(PlanningVersion.id.desc()).first()
    if ref is None:
        alert("INFO", "NO_ISSUED", "Chưa có phiên bản kế hoạch nào được Issue")
    mappings = dict(db.query(ActualMapping.status, func.count(ActualMapping.id)).group_by(ActualMapping.status).all())
    if mappings.get("REVIEW", 0) > 1000:
        alert("INFO", "MAPPING_BACKLOG", f"{mappings['REVIEW']:,} thực tế đang chờ xác nhận mapping (Kế hoạch → Thực tế & Đối soát)")

    # ---- bảo mật đăng nhập
    since = utcnow() - timedelta(hours=24)
    failed_logins = db.query(func.count(AuditLog.id)).filter(AuditLog.action == "LOGIN_LOCAL", AuditLog.result == "FAILED", AuditLog.at >= since).scalar() or 0
    locked = db.query(func.count(User.id)).filter(User.locked_until.isnot(None), User.locked_until > utcnow()).scalar() or 0
    if failed_logins >= 20:
        alert("WARNING", "LOGIN_FAILURES", f"{failed_logins} lượt đăng nhập sai trong 24 giờ qua — có thể đang bị dò mật khẩu")
    if locked:
        alert("INFO", "ACCOUNTS_LOCKED", f"{locked} tài khoản đang bị khóa tạm do đăng nhập sai")

    # ---- dung lượng / vòng đời
    archive_bytes = _dir_size(lifecycle.archive_root())
    overview = lifecycle.year_overview(db)
    due = [y["year"] for y in overview["years"] if y["past"] and y["due_by_policy"] and not (y["archive"] and y["archive"]["status"] == "ARCHIVED")]
    if due:
        alert("INFO", "ARCHIVE_DUE", f"Năm {', '.join(map(str, due))} đã quá thời hạn giữ online — cần kết chuyển và lưu trữ (Quản trị → Vòng đời năm)")

    tables = {
        "Người dùng": db.query(func.count(User.id)).scalar(), "Phiên bản kế hoạch": db.query(func.count(PlanningVersion.id)).scalar(),
        "Dòng phiên bản": db.query(func.count(PlanningVersionRow.id)).scalar(), "Quan sát thực tế": db.query(func.count(ActualObservation.id)).scalar(),
        "Mapping": db.query(func.count(ActualMapping.id)).scalar(), "Lần đồng bộ": db.query(func.count(SyncRun.id)).scalar(), "Bản lưu trữ": db.query(func.count(YearArchive.id)).scalar(),
    }
    return {
        "generated_at": utcnow().isoformat(),
        "app": {"name": settings.app_name, "python": platform.python_version(), "uptime_hours": round((time.time() - STARTED_AT) / 3600, 2), "timezone": settings.timezone},
        "database": {"ping_ms": ping_ms, "size_bytes": size},
        "sync": sync, "sync_failed_24h": failed_24h, "scheduler": {"enabled": settings.scheduler_enabled, "running": running},
        "data": {"plan_import_age_days": plan_age_days, "last_actual_observation": last_obs.isoformat() if last_obs else None, "issued_version": ref.code if ref else None,
                 "latest_revenue_date": latest_rev.isoformat() if latest_rev else None, "labor_snapshot_as_of": snap.as_of_date.isoformat() if snap else None,
                 "mappings": {k: mappings.get(k, 0) for k in ("MATCHED", "REVIEW", "UNMATCHED", "OUT_OF_PLAN", "IGNORED")}},
        "security": {"failed_logins_24h": failed_logins, "locked_accounts": locked, "active_users": db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar(),
                     "edit_sessions_active": db.query(func.count(PlanningEditSession.id)).filter(PlanningEditSession.status == "ACTIVE").scalar()},
        "storage": {"archive_bytes": archive_bytes, "archive_dir": str(lifecycle.archive_root())},
        "tables": tables, "alerts": alerts, "status": "ERROR" if any(a["severity"] == "ERROR" for a in alerts) else "WARNING" if any(a["severity"] == "WARNING" for a in alerts) else "OK",
    }
