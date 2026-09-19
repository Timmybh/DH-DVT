import logging

from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine
from app.models.core import Factory, SsoConfig, SyncConfig, User
from app.services.sync_core import recover_stale_runs

log = logging.getLogger(__name__)

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "Admin@123"


def run_seed() -> None:
    import app.models  # noqa: F401  (đăng ký metadata)

    Base.metadata.create_all(bind=engine)
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
                )
            )
            log.warning("Đã tạo tài khoản admin mặc định — hãy đổi mật khẩu ngay sau khi đăng nhập")

        if not db.get(SsoConfig, 1):
            db.add(SsoConfig(id=1))
        if not db.get(SyncConfig, 1):
            db.add(SyncConfig(id=1))
        db.commit()
        recover_stale_runs(db)
