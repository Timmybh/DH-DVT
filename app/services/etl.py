"""Đồng bộ dữ liệu từ SQL Server (nguồn, giống traceabilityportal) sang Postgres (cache).

Khi SQLSERVER_HOST chưa được cấu hình trong .env, service sẽ sinh dữ liệu mẫu
(mock) để dashboard chạy được ngay. Khi đã có schema SQL Server thật, thay nội
dung hàm `_fetch_plan_from_sqlserver` / `_fetch_indicators_from_sqlserver` bằng
câu query thật (dùng `_sqlserver_engine()` bên dưới).
"""

import io
import random
from datetime import date, datetime

from openpyxl import load_workbook
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.factory import Factory
from app.models.importjob import ImportJob
from app.models.indicator import IndicatorStatus
from app.models.kpi import GaugeMetric, KpiConfig
from app.models.plan import PlanProgress

FACTORY_COL_ALIASES = {"xí nghiệp", "xi nghiep", "mã xí nghiệp", "ma xi nghiep", "factory", "factory_code"}
DATE_COL_ALIASES = {"ngày", "ngay", "date", "report_date"}
PLAN_COL_ALIASES = {"kế hoạch", "ke hoach", "plan", "plan_qty"}
ACTUAL_COL_ALIASES = {"thực hiện", "thuc hien", "actual", "actual_qty"}

INDICATOR_KEYS = ["SX", "DONGGOI", "GIAOHANG", "QA", "VUONGMAC"]


def _sqlserver_configured() -> bool:
    return bool(settings.sqlserver_host and settings.sqlserver_db)


def _sqlserver_engine():
    dsn = (
        f"mssql+pyodbc://{settings.sqlserver_user}:{settings.sqlserver_password}"
        f"@{settings.sqlserver_host}:{settings.sqlserver_port}/{settings.sqlserver_db}"
        "?driver=ODBC+Driver+17+for+SQL+Server"
    )
    return create_engine(dsn, pool_pre_ping=True)


def _test_sqlserver_connection() -> None:
    engine = _sqlserver_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def _mock_plan_rows(factories: list[Factory], report_date: date) -> list[dict]:
    rows = []
    total_plan = 0.0
    total_actual = 0.0
    for f in factories:
        if f.code == "TONG":
            continue
        plan_qty = round(random.uniform(800, 1200), 1)
        actual_qty = round(plan_qty * random.uniform(0.75, 1.05), 1)
        total_plan += plan_qty
        total_actual += actual_qty
        rows.append({"factory": f, "plan_qty": plan_qty, "actual_qty": actual_qty})

    tong = next((f for f in factories if f.code == "TONG"), None)
    if tong:
        rows.append({"factory": tong, "plan_qty": total_plan, "actual_qty": total_actual})

    for row in rows:
        plan = row["plan_qty"]
        actual = row["actual_qty"]
        row["completion_pct"] = round((actual / plan * 100) if plan else 0, 1)
        row["report_date"] = report_date
    return rows


def _mock_indicator_rows(report_date: date) -> list[dict]:
    labels = {
        "SX": "Tiến độ SX",
        "DONGGOI": "Đóng gói",
        "GIAOHANG": "Giao hàng",
        "QA": "QA",
        "VUONGMAC": "Vướng mắc",
    }
    rows = []
    for key in INDICATOR_KEYS:
        value = round(random.uniform(70, 100), 1)
        threshold = 90.0
        status = "GREEN" if value >= threshold else "RED"
        rows.append(
            {
                "indicator_key": key,
                "report_date": report_date,
                "status": status,
                "value": value,
                "threshold": threshold,
                "note": f"{labels[key]}: {value}% (mock)",
            }
        )
    return rows


def run_sync(db: Session, triggered_by: str, job_type: str = "MANUAL") -> ImportJob:
    job = ImportJob(job_type=job_type, status="RUNNING", triggered_by=triggered_by)
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        report_date = date.today()
        imported = 0
        skipped = 0

        if _sqlserver_configured():
            _test_sqlserver_connection()
            # TODO: thay bằng query thật khi có schema SQL Server (bảng kế
            # hoạch/sản xuất/đóng gói/giao hàng/QA/vướng mắc của từng xí
            # nghiệp). Hiện tại vẫn dùng dữ liệu mẫu để không chặn dashboard.

        factories = db.query(Factory).order_by(Factory.display_order).all()

        plan_rows = _mock_plan_rows(factories, report_date)
        for row in plan_rows:
            existing = (
                db.query(PlanProgress)
                .filter(PlanProgress.factory_id == row["factory"].id, PlanProgress.report_date == report_date)
                .first()
            )
            if existing is None:
                existing = PlanProgress(factory_id=row["factory"].id, report_date=report_date)
                db.add(existing)
            existing.plan_qty = row["plan_qty"]
            existing.actual_qty = row["actual_qty"]
            existing.completion_pct = row["completion_pct"]
            existing.synced_at = datetime.utcnow()
            imported += 1

        indicator_rows = _mock_indicator_rows(report_date)
        for row in indicator_rows:
            existing = (
                db.query(IndicatorStatus)
                .filter(
                    IndicatorStatus.indicator_key == row["indicator_key"],
                    IndicatorStatus.factory_id.is_(None),
                    IndicatorStatus.report_date == report_date,
                )
                .first()
            )
            if existing is None:
                existing = IndicatorStatus(
                    indicator_key=row["indicator_key"], factory_id=None, report_date=report_date
                )
                db.add(existing)
            existing.status = row["status"]
            existing.value = row["value"]
            existing.threshold = row["threshold"]
            existing.note = row["note"]
            imported += 1

        gauge_configs = (
            db.query(KpiConfig).filter(KpiConfig.gauge_slot.isnot(None), KpiConfig.is_active.is_(True)).all()
        )
        for cfg in gauge_configs:
            existing = (
                db.query(GaugeMetric)
                .filter(GaugeMetric.kpi_config_id == cfg.id, GaugeMetric.report_date == report_date)
                .first()
            )
            if existing is None:
                existing = GaugeMetric(kpi_config_id=cfg.id, report_date=report_date)
                db.add(existing)
            target = cfg.target_value or 100
            existing.value = round(target * random.uniform(0.6, 1.1), 1)
            existing.target = target
            imported += 1

        job.status = "SUCCESS"
        job.rows_imported = imported
        job.rows_skipped = skipped
        job.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        return job
    except Exception as exc:  # noqa: BLE001 - ghi log lỗi vào job, không raise ra API
        db.rollback()
        job.status = "FAILED"
        job.error_message = str(exc)
        job.finished_at = datetime.utcnow()
        db.add(job)
        db.commit()
        db.refresh(job)
        return job


def _normalize_header(value) -> str:
    return str(value).strip().lower() if value is not None else ""


def import_excel_plan(db: Session, file_bytes: bytes, triggered_by: str) -> ImportJob:
    """Đồng bộ file Excel kế hoạch (thủ công) vào PlanProgress.

    Yêu cầu cột: Xí nghiệp (mã: XN1/XN2/XN3/TONG), Ngày, Kế hoạch.
    Cột Thực hiện là tùy chọn - nếu có sẽ cập nhật, không có thì giữ nguyên.
    """
    job = ImportJob(job_type="EXCEL", status="RUNNING", triggered_by=triggered_by)
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        header = next(rows)

        col_index: dict[str, int] = {}
        for idx, cell in enumerate(header):
            name = _normalize_header(cell)
            if name in FACTORY_COL_ALIASES:
                col_index["factory"] = idx
            elif name in DATE_COL_ALIASES:
                col_index["date"] = idx
            elif name in PLAN_COL_ALIASES:
                col_index["plan"] = idx
            elif name in ACTUAL_COL_ALIASES:
                col_index["actual"] = idx

        if not {"factory", "date", "plan"} <= col_index.keys():
            raise ValueError("File Excel cần có cột: Xí nghiệp, Ngày, Kế hoạch (Thực hiện không bắt buộc)")

        factories = {f.code: f for f in db.query(Factory).all()}
        imported = 0
        skipped = 0

        for row in rows:
            if row is None or all(v is None for v in row):
                continue

            factory_code = str(row[col_index["factory"]] or "").strip().upper()
            factory = factories.get(factory_code)
            raw_date = row[col_index["date"]]
            plan_val = row[col_index["plan"]]

            if factory is None or raw_date is None or plan_val is None:
                skipped += 1
                continue

            if isinstance(raw_date, datetime):
                report_date = raw_date.date()
            elif isinstance(raw_date, date):
                report_date = raw_date
            else:
                try:
                    report_date = datetime.strptime(str(raw_date), "%d/%m/%Y").date()
                except ValueError:
                    skipped += 1
                    continue

            existing = (
                db.query(PlanProgress)
                .filter(PlanProgress.factory_id == factory.id, PlanProgress.report_date == report_date)
                .first()
            )
            if existing is None:
                existing = PlanProgress(factory_id=factory.id, report_date=report_date)
                db.add(existing)

            existing.plan_qty = float(plan_val)
            if "actual" in col_index and row[col_index["actual"]] is not None:
                existing.actual_qty = float(row[col_index["actual"]])
            existing.completion_pct = round(
                (existing.actual_qty / existing.plan_qty * 100) if existing.plan_qty else 0, 1
            )
            existing.synced_at = datetime.utcnow()
            imported += 1

        job.status = "SUCCESS"
        job.rows_imported = imported
        job.rows_skipped = skipped
        job.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        return job
    except Exception as exc:  # noqa: BLE001 - ghi log lỗi vào job, không raise ra API
        db.rollback()
        job.status = "FAILED"
        job.error_message = str(exc)
        job.finished_at = datetime.utcnow()
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
