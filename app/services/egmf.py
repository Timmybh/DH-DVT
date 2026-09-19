"""Đồng bộ doanh thu xí nghiệp từ SQL Server eGMF sang Postgres.

Nguồn (màn hình ERP "DOANH THU XÍ NGHIỆP"):
  dbo.LCD_Truc_Quan_XiNghiep_DoanhThu_Ngay   (tab Doanh Thu Ngày)
  dbo.LCD_Truc_Quan_XiNghiep_DoanhThu_Thang  (tab Doanh Thu Tháng)
  dbo.LCD_Truc_Quan_XiNghiep_DoanhThu_Nam    (tab Doanh Thu Năm)
  dbo.GDXN_XiNghiep                          (danh mục xí nghiệp)
Dữ liệu do người dùng khai báo tay trên ERP nên có thể có dòng sai định dạng -> ghi UNMATCHED để sửa tại nguồn.
"""

import logging
import time

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.core import Factory
from app.models.data import RevenueDaily, RevenueMonthly, RevenueYearly, SyncRun
from app.services.sync_core import add_items, fail_run, finish_run, start_run

log = logging.getLogger(__name__)

SRC_DAILY = "LCD_Truc_Quan_XiNghiep_DoanhThu_Ngay"
SRC_MONTHLY = "LCD_Truc_Quan_XiNghiep_DoanhThu_Thang"
SRC_YEARLY = "LCD_Truc_Quan_XiNghiep_DoanhThu_Nam"

_engine: Engine | None = None


def sqlserver_configured() -> bool:
    return bool(settings.sqlserver_host and settings.sqlserver_db and settings.sqlserver_user)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = URL.create(
            "mssql+pyodbc",
            username=settings.sqlserver_user,
            password=settings.sqlserver_password,
            host=settings.sqlserver_host,
            port=settings.sqlserver_port,
            database=settings.sqlserver_db,
            query={"driver": settings.sqlserver_driver, "TrustServerCertificate": "yes"},
        )
        _engine = create_engine(url, pool_pre_ping=True, connect_args={"timeout": settings.sqlserver_timeout})
    return _engine


def _f(value) -> float | None:
    return None if value is None else float(value)


def _int_or_none(value, lo: int, hi: int) -> int | None:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def _chunks(seq, size=500):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _upsert(db: Session, model, constraint: str, rows: list[dict], update_cols: list[str]) -> None:
    for part in _chunks(rows):
        stmt = pg_insert(model).values(part)
        stmt = stmt.on_conflict_do_update(constraint=constraint, set_={c: stmt.excluded[c] for c in update_cols})
        db.execute(stmt)


def _ensure_factories(db: Session, xn_rows) -> dict[int, int]:
    """Cập nhật danh mục xí nghiệp theo GDXN_XiNghiep; trả map MaXiNghiep -> factory.id."""
    existing = {f.sql_xn_id: f for f in db.query(Factory).filter(Factory.sql_xn_id.isnot(None)).all()}
    for r in xn_rows:
        ma = int(r.MaXiNghiep)
        fac = existing.get(ma)
        name = (r.TenXiNghiep or f"Xí nghiệp {ma}").strip()
        if fac is None:
            fac = Factory(code=f"XN{ma}", name=name, sql_xn_id=ma, display_order=ma, is_active=bool(r.IsActive))
            db.add(fac)
            existing[ma] = fac
        else:
            fac.name = name
            fac.is_active = bool(r.IsActive)
    db.flush()
    return {ma: f.id for ma, f in existing.items()}


def _sync(db: Session, run: SyncRun) -> None:
    with get_engine().connect() as conn:
        xn_rows = conn.execute(text("SELECT Id, MaXiNghiep, TenXiNghiep, IsActive FROM dbo.GDXN_XiNghiep")).fetchall()
        daily = conn.execute(
            text(
                f"SELECT Id, XiNghiep, Ngay, DoanhThuKeHoach, DoanhThuThucHien, DoanhThuConLai FROM dbo.{SRC_DAILY}"
            )
        ).fetchall()
        monthly = conn.execute(
            text(
                "SELECT Id, XiNghiep, Thang, Nam, DoanhThuKeHoach, DoanhThuThucHien, DoanhThuConLai, NguoiTao, ThoiGianTao "
                f"FROM dbo.{SRC_MONTHLY}"
            )
        ).fetchall()
        yearly = conn.execute(
            text(
                "SELECT Id, XiNghiep, Nam, DoanhThuKeHoach, DoanhThuThucHien, DoanhThuConLai, NguoiTao, ThoiGianTao "
                f"FROM dbo.{SRC_YEARLY}"
            )
        ).fetchall()

    fmap = _ensure_factories(db, xn_rows)
    objects = []
    unmatched_total = 0
    matched_total = 0
    updated = 0

    # ---- Daily
    best: dict = {}
    bad = []
    superseded = 0
    for r in daily:
        fid = fmap.get(int(r.XiNghiep)) if r.XiNghiep is not None else None
        if fid is None or r.Ngay is None:
            bad.append((f"Id={r.Id}", f"Xí nghiệp/Ngày không hợp lệ (XiNghiep={r.XiNghiep}, Ngay={r.Ngay})", {"Id": r.Id}))
            continue
        key = (fid, r.Ngay)
        if key in best:
            superseded += 1
            if best[key].Id > r.Id:
                continue
        best[key] = r
    rows = [
        dict(
            factory_id=k[0],
            report_date=k[1],
            plan=_f(v.DoanhThuKeHoach),
            actual=_f(v.DoanhThuThucHien),
            remaining=_f(v.DoanhThuConLai),
            source="EGMF",
            sync_run_id=run.id,
        )
        for k, v in best.items()
    ]
    _upsert(db, RevenueDaily, "uq_revenue_daily", rows, ["plan", "actual", "remaining", "source", "sync_run_id"])
    add_items(db, run.id, "UNMATCHED", SRC_DAILY, bad)
    objects.append({"name": SRC_DAILY, "read": len(daily), "matched": len(rows), "unmatched": len(bad), "superseded": superseded})
    matched_total += len(rows)
    unmatched_total += len(bad)
    updated += len(rows)

    # ---- Monthly
    best, bad, superseded = {}, [], 0
    for r in monthly:
        fid = fmap.get(int(r.XiNghiep)) if r.XiNghiep is not None else None
        month = _int_or_none(r.Thang, 1, 12)
        year = _int_or_none(r.Nam, 2000, 2100)
        if fid is None or month is None or year is None:
            bad.append(
                (
                    f"Id={r.Id}",
                    f"Tháng/Năm/Xí nghiệp không hợp lệ (XiNghiep={r.XiNghiep}, Thang='{r.Thang}', Nam='{r.Nam}') — người tạo: {r.NguoiTao}",
                    {"Id": r.Id, "XiNghiep": r.XiNghiep, "Thang": r.Thang, "Nam": r.Nam, "NguoiTao": r.NguoiTao},
                )
            )
            continue
        key = (fid, year, month)
        if key in best:
            superseded += 1
            if best[key].Id > r.Id:
                continue
        best[key] = r
    rows = [
        dict(
            factory_id=k[0],
            year=k[1],
            month=k[2],
            plan=_f(v.DoanhThuKeHoach),
            actual=_f(v.DoanhThuThucHien),
            remaining=_f(v.DoanhThuConLai),
            declared_by=v.NguoiTao or "",
            declared_at=v.ThoiGianTao,
            source="EGMF",
            sync_run_id=run.id,
        )
        for k, v in best.items()
    ]
    _upsert(
        db,
        RevenueMonthly,
        "uq_revenue_monthly",
        rows,
        ["plan", "actual", "remaining", "declared_by", "declared_at", "source", "sync_run_id"],
    )
    add_items(db, run.id, "UNMATCHED", SRC_MONTHLY, bad)
    objects.append({"name": SRC_MONTHLY, "read": len(monthly), "matched": len(rows), "unmatched": len(bad), "superseded": superseded})
    matched_total += len(rows)
    unmatched_total += len(bad)
    updated += len(rows)

    # ---- Yearly
    best, bad, superseded = {}, [], 0
    for r in yearly:
        fid = fmap.get(int(r.XiNghiep)) if r.XiNghiep is not None else None
        year = _int_or_none(r.Nam, 2000, 2100)
        if fid is None or year is None:
            bad.append(
                (
                    f"Id={r.Id}",
                    f"Năm/Xí nghiệp không hợp lệ (XiNghiep={r.XiNghiep}, Nam='{r.Nam}') — người tạo: {r.NguoiTao}",
                    {"Id": r.Id, "XiNghiep": r.XiNghiep, "Nam": r.Nam, "NguoiTao": r.NguoiTao},
                )
            )
            continue
        key = (fid, year)
        if key in best:
            superseded += 1
            if best[key].Id > r.Id:
                continue
        best[key] = r
    rows = [
        dict(
            factory_id=k[0],
            year=k[1],
            plan=_f(v.DoanhThuKeHoach),
            actual=_f(v.DoanhThuThucHien),
            remaining=_f(v.DoanhThuConLai),
            declared_by=v.NguoiTao or "",
            declared_at=v.ThoiGianTao,
            source="EGMF",
            sync_run_id=run.id,
        )
        for k, v in best.items()
    ]
    _upsert(
        db,
        RevenueYearly,
        "uq_revenue_yearly",
        rows,
        ["plan", "actual", "remaining", "declared_by", "declared_at", "source", "sync_run_id"],
    )
    add_items(db, run.id, "UNMATCHED", SRC_YEARLY, bad)
    objects.append({"name": SRC_YEARLY, "read": len(yearly), "matched": len(rows), "unmatched": len(bad), "superseded": superseded})
    matched_total += len(rows)
    unmatched_total += len(bad)
    updated += len(rows)

    if matched_total > 0:
        for model in (RevenueDaily, RevenueMonthly, RevenueYearly):
            db.query(model).filter(model.source == "DEMO").delete()

    run.total_records = len(daily) + len(monthly) + len(yearly)
    run.matched = matched_total
    run.unmatched = unmatched_total
    run.ambiguous = 0
    run.updated_rows = updated
    run.summary = {"objects": objects, "factories": len(fmap), "target": settings.sqlserver_host + "/" + settings.sqlserver_db}
    db.commit()


def _friendly_error(exc: Exception) -> str | None:
    text_ = str(exc)
    if isinstance(exc, OperationalError) and any(k in text_ for k in ("08001", "Login timeout", "timed out", "Server is not found")):
        return f"Không kết nối được SQL Server {settings.sqlserver_host}:{settings.sqlserver_port} — kiểm tra mạng/VPN/tường lửa. Chi tiết kỹ thuật xem trong danh sách bản ghi lỗi của phiên này."
    if isinstance(exc, (OperationalError, InterfaceError)) and "Login failed" in text_:
        return "SQL Server từ chối đăng nhập — kiểm tra SQLSERVER_USER / SQLSERVER_PASSWORD trong .env."
    return None


def run_revenue_sync(db: Session, *, trigger: str = "MANUAL", username: str = "", retry_of: int | None = None) -> SyncRun:
    run = start_run(db, "EGMF_REVENUE", trigger, username, retry_of)
    t0 = time.perf_counter()
    try:
        if not sqlserver_configured():
            raise RuntimeError("Chưa cấu hình kết nối SQL Server (biến SQLSERVER_* trong .env)")
        _sync(db, run)
        return finish_run(db, run, t0)
    except Exception as exc:  # noqa: BLE001
        return fail_run(db, run.id, t0, exc, _friendly_error(exc))
