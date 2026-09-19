"""Application configuration loaded from environment / .env file."""
from pathlib import Path
from urllib.parse import quote_plus
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Kalika Enterprises ERP"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api"

    # ---- Database ----
    # Cloud Run + Cloud SQL: DATABASE_URL is set via env var (Cloud SQL Auth Proxy socket).
    # Local dev: falls back to local PostgreSQL via .env or local default.
    DATABASE_URL: str = ""

    # ---- Cloud SQL (populated by Cloud Run env or .env for local dev) ----
    CLOUD_SQL_CONNECTION_NAME: str = ""
    CLOUD_SQL_DB_NAME: str = "kalika_erp"
    CLOUD_SQL_DB_USER: str = "kalika_app"
    CLOUD_SQL_DB_PASS: str = ""

    # ---- JWT ----
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480
    ACCESS_TOKEN_NAME: str = "kalika_access"

    # ---- GCS ----
    GCS_BUCKET: str = "kalisoftai-datahub"
    GCS_EXCEL_FILE: str = "Kalika_inventory/Daily Report Aug-26.xlsx"
    GOOGLE_APPLICATION_CREDENTIALS: str | None = None
    REPORT_DIR: Path = BASE_DIR / "reports"

    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # ---- Email (Gmail SMTP) ----
    MAIL_ENABLED: bool = False
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USE_TLS: bool = True
    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""
    MAIL_FROM: str = "kalikaenterprises@gmail.com"
    MAIL_FROM_NAME: str = "Kalika Enterprises"

    @property
    def database_url(self) -> str:
        """Resolve DATABASE_URL with Cloud SQL socket support."""
        # 1. Explicit DATABASE_URL env var takes full precedence (local dev or direct connection)
        if self.DATABASE_URL:
            return self.DATABASE_URL

        # 2. Cloud SQL Auth Proxy socket (Cloud Run / gcloud proxy)
        #    Format: postgresql+psycopg2://user:pass@localhost/dbname?host=/cloudsql/INSTANCE_CONNECTION_NAME
        if self.CLOUD_SQL_CONNECTION_NAME and self.CLOUD_SQL_DB_PASS:
            return (
                f"postgresql+psycopg2://{quote_plus(self.CLOUD_SQL_DB_USER)}:{quote_plus(self.CLOUD_SQL_DB_PASS)}"
                f"@localhost/{self.CLOUD_SQL_DB_NAME}"
                f"?host=/cloudsql/{self.CLOUD_SQL_CONNECTION_NAME}"
            )

        # 3. Nothing configured — fail fast rather than silently try a local
        #    dev database with baked-in credentials (never ship those).
        raise RuntimeError(
            "No database configuration. Set DATABASE_URL (local dev), or "
            "CLOUD_SQL_CONNECTION_NAME with CLOUD_SQL_DB_NAME, CLOUD_SQL_DB_USER "
            "and CLOUD_SQL_DB_PASS (Cloud Run)."
        )

    @property
    def report_dir(self) -> Path:
        """Resolve REPORT_DIR, falling back to a writable dir if the configured
        path cannot be created (e.g. Cloud Run non-root user hitting root paths)."""
        try:
            self.REPORT_DIR.mkdir(parents=True, exist_ok=True)
            return self.REPORT_DIR
        except PermissionError:
            fallback = Path("/tmp/reports")
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback


settings = Settings()