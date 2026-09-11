from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine
from app.models.factory import Factory
from app.models.importjob import ImportJobConfig
from app.models.kpi import KpiConfig
from app.models.user import User

DEFAULT_FACTORIES = [
    ("XN1", "Xí nghiệp 1", 1),
    ("XN2", "Xí nghiệp 2", 2),
    ("XN3", "Xí nghiệp 3", 3),
    ("TONG", "Tổng công ty", 4),
]

DEFAULT_INDICATOR_KPIS = [
    ("SX", "Tiến độ SX", "%", 90.0),
    ("DONGGOI", "Đóng gói", "%", 90.0),
    ("GIAOHANG", "Giao hàng", "%", 90.0),
    ("QA", "QA", "%", 90.0),
    ("VUONGMAC", "Vướng mắc", "%", 90.0),
]


def _seed_factories(db: Session) -> None:
    if db.query(Factory).count() > 0:
        return
    for code, name, order in DEFAULT_FACTORIES:
        db.add(Factory(code=code, name=name, display_order=order))
    db.commit()


def _seed_kpi_configs(db: Session) -> None:
    if db.query(KpiConfig).count() > 0:
        return

    for i, (key, label, unit, threshold) in enumerate(DEFAULT_INDICATOR_KPIS, start=1):
        db.add(
            KpiConfig(
                key=f"indicator_{key.lower()}",
                label=label,
                unit=unit,
                warning_threshold_pct=threshold,
                display_order=i,
            )
        )

    # 10 gauge trống - key gauge_1..gauge_10, gán sẵn gauge_slot, cấu hình chi tiết sau qua "Cấu hình KPI"
    for slot in range(1, 11):
        db.add(
            KpiConfig(
                key=f"gauge_{slot}",
                label=f"Gauge {slot}",
                unit="",
                target_value=100,
                gauge_slot=slot,
                display_order=100 + slot,
                is_active=True,
            )
        )
    db.commit()


def _seed_admin_user(db: Session) -> None:
    if db.query(User).filter(User.username == "admin").first():
        return
    db.add(
        User(
            full_name="Quản trị hệ thống",
            username="admin",
            email="admin@dh-dvt.local",
            password_hash=hash_password("Admin@123"),
            role="ADMIN",
        )
    )
    db.commit()


def _seed_import_job_config(db: Session) -> None:
    if db.query(ImportJobConfig).first():
        return
    db.add(ImportJobConfig(is_enabled=False, scheduled_time="05:00"))
    db.commit()


def run_seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _seed_factories(db)
        _seed_kpi_configs(db)
        _seed_admin_user(db)
        _seed_import_job_config(db)
    finally:
        db.close()
