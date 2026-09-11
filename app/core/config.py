from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "DH-DVT Dashboard"
    debug: bool = False

    # Auth
    jwt_secret: str = "change-me-in-env"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8

    # Postgres (cache DB for the dashboard) - local PostgreSQL 18 service
    postgres_dsn: str = "postgresql+psycopg2://dhdvt:dhdvt@localhost:5432/dhdvt"

    # SQL Server (source of truth, same server as traceabilityportal)
    sqlserver_host: str = ""
    sqlserver_port: int = 1433
    sqlserver_db: str = ""
    sqlserver_user: str = ""
    sqlserver_password: str = ""

    # Daily ETL schedule (24h HH:MM, Asia/Ho_Chi_Minh)
    etl_daily_time: str = "05:00"
    etl_enabled: bool = False

    class Config:
        env_file = ".env"


settings = Settings()
