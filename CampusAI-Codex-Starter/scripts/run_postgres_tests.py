"""Run the PostgreSQL integration tests using backend/.env credentials safely."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402


def main() -> int:
    database_url = settings.database_url
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg":
        print("PostgreSQL tests require POSTGRES_* values in backend/.env.")
        return 2
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        print("Refusing to run concurrency tests against a non-local database host.")
        return 2
    if url.database != "campusai" and not (url.database or "").endswith("_test"):
        print("Refusing to run tests against an unrecognized database name.")
        return 2
    if settings.environment.casefold() == "production":
        print("Refusing to run integration tests in production mode.")
        return 2

    engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            database_name, version = connection.execute(
                text("select current_database(), version()")
            ).one()
            if database_name != url.database:
                print("Connected database name did not match configured test target.")
                return 2
            print(f"PostgreSQL target verified: {database_name} ({version.split(',')[0]}).")
    except SQLAlchemyError as exc:
        print(f"PostgreSQL connection failed ({type(exc).__name__}); credentials were not displayed.")
        return 2
    finally:
        engine.dispose()

    env = os.environ.copy()
    env["CAMPUSAI_TEST_POSTGRES_URL"] = database_url
    env["GEMINI_API_KEY"] = ""
    env["GEMINI_PLACEMENT_API_KEY"] = ""
    env["GEMINI_CHAT_API_KEY"] = ""
    env["QDRANT_URL"] = ""
    env["QDRANT_API_KEY"] = ""
    test_files = [
        "backend/tests/test_auth_postgres_concurrency.py",
        "backend/tests/test_postgres_application_concurrency.py",
        "backend/tests/test_postgres_document_scope_lock.py",
        "backend/tests/test_postgres_policy_application_race.py",
    ]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *test_files, "-q"],
        cwd=ROOT,
        env=env,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
