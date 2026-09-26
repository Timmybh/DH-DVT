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
            "ALTER TABLE plan_rows ADD COLUMN IF NOT EXISTS grid JSON",
            "ALTER TABLE planning_versions ADD COLUMN IF NOT EXISTS returned JSON",
            "ALTER TABLE planning_versions ADD COLUMN IF NOT EXISTS formula_set JSON",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0",
            "UPDATE calendar_day_types SET effect='CHOICE' WHERE code='EXCEPTION' AND effect='WORKING'",  # Ngoại lệ: hiệu lực chọn theo từng đăng ký (rule cũ giữ nguyên)
            "ALTER TABLE working_calendar_rules ALTER COLUMN rule_type TYPE VARCHAR(16)",
            "ALTER TABLE working_calendar_rules ADD COLUMN IF NOT EXISTS day_type VARCHAR(20) NOT NULL DEFAULT ''",
            "ALTER TABLE working_calendar_rules ADD COLUMN IF NOT EXISTS rule_end_date DATE",
            "ALTER TABLE working_calendar_rules ADD COLUMN IF NOT EXISTS month INTEGER",
            "ALTER TABLE working_calendar_rules ADD COLUMN IF NOT EXISTS month_day INTEGER",
            "ALTER TABLE working_calendar_rules ADD COLUMN IF NOT EXISTS valid_from DATE",
            "ALTER TABLE working_calendar_rules ADD COLUMN IF NOT EXISTS valid_to DATE",
            "ALTER TABLE working_calendar_rules ADD COLUMN IF NOT EXISTS status VARCHAR(10) NOT NULL DEFAULT 'ACTIVE'",
            "ALTER TABLE working_calendar_rules ADD COLUMN IF NOT EXISTS status_changed_by VARCHAR(100) NOT NULL DEFAULT ''",
            "ALTER TABLE working_calendar_rules ADD COLUMN IF NOT EXISTS status_changed_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE working_calendar_rules ADD COLUMN IF NOT EXISTS status_reason VARCHAR(200) NOT NULL DEFAULT ''",
            "ALTER TABLE plan_rows ADD COLUMN IF NOT EXISTS so_id INTEGER",
            "ALTER TABLE planning_version_rows ADD COLUMN IF NOT EXISTS so_id INTEGER",
            "ALTER TABLE actual_mappings ALTER COLUMN status TYPE VARCHAR(16)",
            "ALTER TABLE dashboard_layout_items ADD COLUMN IF NOT EXISTS section_id INTEGER",
            "ALTER TABLE dashboard_layout_items ADD COLUMN IF NOT EXISTS column_no INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE dashboard_layout_sections ADD COLUMN IF NOT EXISTS custom_spans JSON",
            "ALTER TABLE labor_standards ADD COLUMN IF NOT EXISTS cn_may INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE labor_standards ADD COLUMN IF NOT EXISTS ql INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE labor_standards ADD COLUMN IF NOT EXISTS kh INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE labor_standards ADD COLUMN IF NOT EXISTS dg INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE labor_standards ADD COLUMN IF NOT EXISTS ui INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE labor_standards ADD COLUMN IF NOT EXISTS khac INTEGER NOT NULL DEFAULT 0",
            "UPDATE labor_standards SET ql = LEAST(6, total_labor), cn_may = total_labor - LEAST(6, total_labor) WHERE total_labor > 0 AND cn_may = 0 AND ql = 0 AND kh = 0 AND dg = 0 AND ui = 0 AND khac = 0",
            "ALTER TABLE labor_daily ADD COLUMN IF NOT EXISTS work_minutes INTEGER",
            "ALTER TABLE labor_daily ADD COLUMN IF NOT EXISTS outside INTEGER",
            "ALTER TABLE labor_daily ADD COLUMN IF NOT EXISTS participating INTEGER",
            "ALTER TABLE style_sam ADD COLUMN IF NOT EXISTS sam_kt DOUBLE PRECISION",
            "ALTER TABLE style_sam ADD COLUMN IF NOT EXISTS sam_tt DOUBLE PRECISION",
            "UPDATE style_sam SET sam_kt = sam_minutes WHERE source = 'ERP' AND sam_kt IS NULL",
            "ALTER TABLE style_sam ADD COLUMN IF NOT EXISTS brand VARCHAR(60) NOT NULL DEFAULT ''",
            "ALTER TABLE style_sam ADD COLUMN IF NOT EXISTS sot_minutes DOUBLE PRECISION",
            "ALTER TABLE dashboard_layout_sections ADD COLUMN IF NOT EXISTS zone VARCHAR(14) NOT NULL DEFAULT 'MAIN'",
            "ALTER TABLE machine_style_outputs ADD COLUMN IF NOT EXISTS required_quantity INTEGER",
            "ALTER TABLE machine_style_outputs ADD COLUMN IF NOT EXISTS source VARCHAR(10) NOT NULL DEFAULT 'MANUAL'",
            "ALTER TABLE machine_style_outputs ALTER COLUMN output_per_day DROP NOT NULL",
            "ALTER TABLE machine_types ADD COLUMN IF NOT EXISTS model VARCHAR(60) NOT NULL DEFAULT ''",
            "ALTER TABLE machine_types ADD COLUMN IF NOT EXISTS machine_group VARCHAR(60) NOT NULL DEFAULT ''",
            "ALTER TABLE machine_types ADD COLUMN IF NOT EXISTS process VARCHAR(60) NOT NULL DEFAULT ''",
            "ALTER TABLE machine_types ADD COLUMN IF NOT EXISTS nominal_output_per_day DOUBLE PRECISION",
            "ALTER TABLE machine_types ADD COLUMN IF NOT EXISTS default_efficiency DOUBLE PRECISION",
            "ALTER TABLE machine_types ADD COLUMN IF NOT EXISTS changeover_minutes DOUBLE PRECISION",
            "ALTER TABLE machine_types ADD COLUMN IF NOT EXISTS is_bottleneck_capable BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE machine_types ADD COLUMN IF NOT EXISTS effective_from DATE",
            "ALTER TABLE machine_types ADD COLUMN IF NOT EXISTS effective_to DATE",
            "ALTER TABLE machine_types ADD COLUMN IF NOT EXISTS status VARCHAR(10) NOT NULL DEFAULT 'ACTIVE'",
            "ALTER TABLE machine_types ADD COLUMN IF NOT EXISTS note VARCHAR(300) NOT NULL DEFAULT ''",
            "ALTER TABLE machine_types ADD COLUMN IF NOT EXISTS updated_by VARCHAR(100) NOT NULL DEFAULT ''",
            "ALTER TABLE machine_types ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE machine_capacities ADD COLUMN IF NOT EXISTS maintenance_quantity INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE machine_capacities ADD COLUMN IF NOT EXISTS down_quantity INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE actual_mappings ADD COLUMN IF NOT EXISTS mapped_so_id INTEGER",
            "ALTER TABLE actual_mappings ALTER COLUMN method TYPE VARCHAR(24)",
            "ALTER TABLE technology_process_operations ALTER COLUMN operator_count DROP NOT NULL",  # Task 2: 0 != "không biết" (ERP import)
            "ALTER TABLE technology_process_operations ADD COLUMN IF NOT EXISTS change_type VARCHAR(30)",  # Task 3
            "ALTER TABLE technology_process_versions ADD COLUMN IF NOT EXISTS generation_fingerprint VARCHAR(120) NOT NULL DEFAULT ''",  # Task 3
            "CREATE INDEX IF NOT EXISTS ix_tpv_generation_fingerprint ON technology_process_versions (generation_fingerprint)",
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

        # Lịch làm việc và danh mục loại ngày do NGƯỜI DÙNG định nghĩa — hệ thống không nạp sẵn dữ liệu nào vào DB.

        from app.services import labor_snapshot

        labor_snapshot.backfill_from_labor_daily(db)  # lần đầu: dựng ảnh chụp lao động từ dữ liệu eGMF đã lưu

        if not db.get(SsoConfig, 1):
            db.add(SsoConfig(id=1))
        if not db.get(SyncConfig, 1):
            db.add(SyncConfig(id=1))
        db.commit()
        from app.services import sync_schedule

        sync_schedule.ensure_defaults(db)
        from app.services import formula_service  # tránh vòng import khi nạp module

        formula_service.seed_columns_and_formulas(db)
        from app.services import dashboard_meta

        dashboard_meta.seed_dashboard_meta(db)
        dashboard_meta.migrate_layouts_to_sections(db)
        from app.services import signal_rules

        signal_rules.seed_signal_rules(db)  # quy tắc Tin tốt/xấu mẫu, chỉ khi bảng còn trống
        formula_service.refresh_active(db)
        from app.services import planning_service

        planning_service.load_resolver(db)  # nạp Lịch làm việc cho công thức OFF_DAYS
        from app.services import labor_grade_service

        labor_grade_service.seed_grades(db)  # PG01..PG10 mặc định (spec §4), chỉ khi bảng trống
        from app.services import so_service

        so_service.bulk_issue_current(db, "system")  # cấp SO TẠM cho dữ liệu hiện có chưa có SO (UAT); chạy lại an toàn
        from app.services import erp_qtcn_sync

        erp_qtcn_sync.seed_machine_crosswalk(db)  # 6 crosswalk EXACT đã duyệt (Issue #5 review vòng 2 mục 4), chỉ khi chưa có
        recover_stale_runs(db)
