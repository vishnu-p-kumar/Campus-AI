import hashlib
import hmac
import logging
import time
import asyncio
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.api import admin, auth, chat, companies, dashboard, documents, evaluation, interviews, notifications, placement, resumes, students
from app.ai import retrieval
from app.core.config import settings
from app.db import engine
from app.models import AuthRateLimitBucket
from app.upload_scan import ScannerUnavailable, check_scanner

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Student placement workflows, deterministic eligibility, document-grounded assistance and research evaluation.",
)


def validate_production_configuration(config=settings) -> None:
    if config.environment.casefold() != "production":
        return
    if len(config.jwt_secret_key) < 32 or config.jwt_secret_key == "development-only-change-me-before-deploy":
        raise RuntimeError("Production requires a strong JWT_SECRET_KEY of at least 32 characters")
    if not config.database_url.startswith(("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")):
        raise RuntimeError("Production requires PostgreSQL via DATABASE_URL")
    if not config.qdrant_url or not config.qdrant_api_key:
        raise RuntimeError("Production requires QDRANT_URL and QDRANT_API_KEY")
    origins = config.allowed_origins
    parsed_origins = [urlsplit(origin) for origin in origins]
    if not origins or "*" in origins or any(
        parts.scheme != "https" or not parts.hostname or parts.username or parts.password
        or parts.path or parts.query or parts.fragment for parts in parsed_origins
    ):
        raise RuntimeError("Production CORS_ORIGINS must contain only explicit HTTPS origins")
    reset_url = urlsplit(config.password_reset_url)
    if reset_url.scheme != "https" or not reset_url.netloc or reset_url.hostname in {"localhost", "127.0.0.1"}:
        raise RuntimeError("Production PASSWORD_RESET_URL must use a public HTTPS origin")
    if not config.upload_scan_required or not config.clamav_host:
        raise RuntimeError("Production requires UPLOAD_SCAN_REQUIRED=true and a configured CLAMAV_HOST")


validate_production_configuration()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

logger = logging.getLogger(__name__)


def consume_auth_rate_limit(address: str, now: float | None = None) -> tuple[bool, int]:
    """Atomically consume one shared auth attempt and return (allowed, retry_after)."""
    current = time.time() if now is None else now
    window = int(current // 60)
    digest = hmac.new(settings.jwt_secret_key.encode(), address.encode(), hashlib.sha256).hexdigest()
    dialect = engine.dialect.name
    insert = postgres_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
    if insert is None:
        raise RuntimeError(f"Shared authentication throttling is unsupported for database dialect {dialect}")
    with engine.begin() as connection:
        connection.execute(delete(AuthRateLimitBucket).where(AuthRateLimitBucket.window_start < window - 1))
        statement = insert(AuthRateLimitBucket).values(rate_key=digest, window_start=window, attempts=1)
        statement = statement.on_conflict_do_update(
            index_elements=[AuthRateLimitBucket.rate_key, AuthRateLimitBucket.window_start],
            set_={"attempts": AuthRateLimitBucket.attempts + 1},
        ).returning(AuthRateLimitBucket.attempts)
        attempts = connection.execute(statement).scalar_one()
    retry_after = max(1, int((window + 1) * 60 - current))
    return attempts <= settings.auth_rate_limit_per_minute, retry_after


@app.middleware("http")
async def auth_rate_limit(request: Request, call_next):
    if request.url.path.endswith(("/auth/login", "/auth/register", "/auth/refresh", "/auth/password-reset/request", "/auth/password-reset/complete")):
        address = request.client.host if request.client else "unknown"
        try:
            allowed, retry_after = await asyncio.to_thread(consume_auth_rate_limit, address)
        except Exception:
            logger.exception("Shared authentication throttling failed")
            return JSONResponse({"detail": "Authentication is temporarily unavailable."}, status_code=503)
        if not allowed:
            return JSONResponse({"detail": "Too many authentication requests. Try again shortly."}, status_code=429, headers={"Retry-After": str(retry_after)})
    return await call_next(request)


for router in (auth.router, students.router, dashboard.router, companies.router, placement.router, documents.router,
               chat.router, resumes.router, interviews.router, notifications.router, admin.router, evaluation.router):
    app.include_router(router, prefix=settings.api_prefix)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "campusai-api", "version": app.version}


@app.get("/health/ready", tags=["system"])
def ready() -> dict[str, str]:
    dependencies = {"status": "ready", "database": "connected"}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Readiness database check failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "database": "unavailable"},
        ) from None

    if settings.qdrant_url:
        try:
            client = retrieval.qdrant_client()
            if client is None:
                raise RuntimeError("Qdrant client is not configured")
            client.get_collections()
            dependencies["vector_store"] = "connected"
        except Exception as exc:
            logger.warning("Readiness vector-store check failed (%s)", type(exc).__name__)
            dependencies.update(status="not_ready", vector_store="unavailable")
    else:
        dependencies["vector_store"] = "not_configured"

    if settings.clamav_host or settings.upload_scan_required:
        try:
            check_scanner()
            dependencies["upload_scanner"] = "connected"
        except ScannerUnavailable:
            dependencies.update(status="not_ready", upload_scanner="unavailable")
    else:
        dependencies["upload_scanner"] = "not_configured"

    if dependencies["status"] != "ready":
        raise HTTPException(status_code=503, detail=dependencies)
    return dependencies
