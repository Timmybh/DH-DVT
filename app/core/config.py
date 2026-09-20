from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    app_name: str = "DVT - Bảng điều hành"
    debug: bool = False

    jwt_secret: str = "change-me-in-env"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8

    postgres_dsn: str = "postgresql+psycopg2://dhdvt:dhdvt@localhost:5432/dhdvt"

    sqlserver_host: str = ""
    sqlserver_port: int = 1433
    sqlserver_db: str = ""
    sqlserver_user: str = ""
    sqlserver_password: str = ""
    sqlserver_timeout: int = 15
    sqlserver_driver: str = "ODBC Driver 18 for SQL Server"

    revenue_unit: str = "USD"
    timezone: str = "Asia/Ho_Chi_Minh"
    scheduler_enabled: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    static_dir: str = ""

    # Planning Core
    planning_session_timeout_seconds: int = 180  # quá thời gian này không heartbeat -> phiên EXPIRED (§2.1/§14)
    planning_max_undo: int = 100
    planning_issue_requires_pass: bool = True  # §19.3: chỉ Issue khi Recheck = PASS

    # Cảnh báo khi file kế hoạch cũ hơn số ngày này / dữ liệu eGMF chưa làm mới sau số giờ này
    plan_stale_days: int = 45
    sync_stale_hours: int = 36


settings = Settings()
