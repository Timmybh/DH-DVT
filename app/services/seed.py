import logging

from app.core.security import hash_password, verify_password
from app.db.session import Base, SessionLocal, engine
from app.models.core import Factory, SsoConfig, SyncConfig, User
from app.models.planning import WorkingCalendarRule
from app.services.sync_core import recover_stale_runs

log = logging.getLogger(__name__)

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "Admin@123"


def _upgrade_schema() -> None:
    """Nâng cấp schema đã tồn tại (create_all không ALTER). Idempotent."""
    from sqlalchemy import text

    with engine.begin() as conn:
        has_stage = conn.execute(
            text("select 1 from information_schema.columns where table_name='plan_rows' and column_name='stage'")
        ).first()
        if has_stage:
            conn.execute(text("ALTER TABLE plan_rows RENAME COLUMN stage TO planning_status"))
            conn.execute(text("UPDATE plan_rows SET planning_status='UNPLANNED' WHERE planning_status='NEW'"))
        for ddl in (
            "ALTER TABLE plan_rows ADD COLUMN IF NOT EXISTS factory_assignment VARCHAR(12) NOT NULL DEFAULT 'KNOWN'",
            "ALTER TABLE plan_rows ADD COLUMN IF NOT EXISTS mapping_status VARCHAR(8) NOT NULL DEFAULT 'OK'",
            "ALTER TABLE plan_rows ADD COLUMN IF NOT EXISTS mapping_note VARCHAR(200) NOT NULL DEFAULT ''",
            "ALTER TABLE plan_rows ADD COLUMN IF NOT EXISTS fac_raw VARCHAR(20) NOT NULL DEFAULT ''",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE",
        ):
            try:
                conn.execute(text(ddl))
            except Exception:  # noqa: BLE001 - bảng chưa tồn tại lần chạy đầu: create_all sẽ tạo
                pass


def run_seed() -> None:
    import app.models  # noqa: F401  (đăng ký metadata)

    Base.metadata.create_all(bind=engine)
    _upgrade_schema()
    with SessionLocal() as db:
        for n in (1, 2, 3):
            if not db.query(Factory).filter(Factory.sql_xn_id == n).first():
                db.add(Factory(code=f"XN{n}", name=f"Xí nghiệp {n}", sql_xn_id=n, display_order=n))

        if not db.query(User).filter(User.username == DEFAULT_ADMIN_USERNAME).first():
            db.add(
                User(
                    full_name="Quản trị hệ thống",
                    username=DEFAULT_ADMIN_USERNAME,
                    email="admin@dvt.local",
                    password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
                    role="ADMIN",
                    must_change_password=True,
                )
            )
            log.warning("Đã tạo tài khoản admin mặc định — bắt buộc đổi mật khẩu ở lần đăng nhập đầu")
        else:
            admin = db.query(User).filter(User.username == DEFAULT_ADMIN_USERNAME).first()
            if not admin.must_change_password and verify_password(DEFAULT_ADMIN_PASSWORD, admin.password_hash):
                admin.must_change_password = True  # vẫn dùng mật khẩu mặc định -> buộc đổi
                log.warning("Tài khoản admin vẫn dùng mật khẩu mặc định — đã bật bắt buộc đổi mật khẩu")

        if db.query(WorkingCalendarRule).count() == 0:  # mặc định Company: Chủ nhật nghỉ (admin chỉnh trong lịch làm việc)
            db.add(WorkingCalendarRule(scope_type="COMPANY", scope_key="", rule_type="WEEKLY_OFF", weekday=6, note="Chủ nhật nghỉ", created_by="system"))

        if not db.get(SsoConfig, 1):
            db.add(SsoConfig(id=1))
        if not db.get(SyncConfig, 1):
            db.add(SyncConfig(id=1))
        db.commit()
        recover_stale_runs(db)
