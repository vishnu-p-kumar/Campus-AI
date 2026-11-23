from functools import lru_cache
from typing import Literal
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    app_name: str = "CampusAI Placement Intelligence API"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str | None = Field(default=None, repr=False)
    postgres_host: str | None = None
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str | None = None
    postgres_user: str | None = None
    postgres_password: str | None = Field(default=None, repr=False)
    jwt_secret_key: str = "development-only-change-me-before-deploy"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    auth_rate_limit_per_minute: int = 20
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # GEMINI_API_KEY is reserved for resume review and role-skill guidance.
    gemini_api_key: str | None = Field(default=None, repr=False)
    # Placement uses its own key; Gemini quotas are scoped to the key's AI Studio project.
    gemini_placement_api_key: str | None = Field(default=None, repr=False)
    # Interview workflows may use a separate key/project from placement and resume.
    gemini_chat_api_key: str | None = Field(default=None, repr=False)
    gemini_model: str = "gemini-3.5-flash-lite"
    # Free standard-tier models used when the primary model is rate-limited.
    gemini_fallback_models: str = "gemini-2.5-flash-lite,gemini-2.5-flash,gemini-3.1-flash-lite,gemini-3.8-flash,gemini-3.6-flash"
    # Gemini URL Context only reads URLs explicitly approved by an administrator.
    gemini_url_context_enabled: bool = False
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection: str = "campusai_document_chunks"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    faithfulness_model: str | None = None
    faithfulness_min_entailment: float = Field(default=0.70, ge=0, le=1)
    evidence_minimum_score: float = Field(default=0.35, ge=0, le=1)
    upload_directory: str = "./uploads"
    max_upload_size: int = 10_000_000
    clamav_host: str | None = None
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    clamav_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    # Disable the upload endpoint until a malware scanner is available.
    document_uploads_enabled: bool = True
    upload_scan_required: bool = False
    document_ingestion_mode: Literal["inline", "queued"] = "inline"
    ingestion_max_attempts: int = Field(default=3, ge=1, le=10)
    ingestion_worker_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    ingestion_job_lease_seconds: int = Field(default=1800, ge=60, le=7200)
    ocr_enabled: bool = False
    ocr_languages: str = "eng"
    ocr_dpi: int = 200
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    password_reset_url: str = "http://localhost:3000/reset-password"

    model_config = SettingsConfigDict(env_file=("backend/.env", ".env"), extra="ignore", case_sensitive=False)

    @model_validator(mode="after")
    def build_postgres_url(self) -> "Settings":
        # An explicit DATABASE_URL (for example, an isolated test database)
        # takes precedence over component POSTGRES_* settings. Otherwise those
        # settings replace the SQLite development default. SQLAlchemy URL
        # rendering safely escapes special characters in credentials.
        if self.database_url is None:
            if self.postgres_host and self.postgres_db and self.postgres_user and self.postgres_password is not None:
                self.database_url = URL.create(
                    "postgresql+psycopg",
                    username=self.postgres_user,
                    password=self.postgres_password,
                    host=self.postgres_host,
                    port=self.postgres_port,
                    database=self.postgres_db,
                ).render_as_string(hide_password=False)
            else:
                self.database_url = "sqlite:///./campusai.db"
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
