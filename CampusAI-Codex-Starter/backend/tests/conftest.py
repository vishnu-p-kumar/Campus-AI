import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Keep the ordinary unit/API suite isolated on SQLite even when the developer's
# backend/.env targets PostgreSQL. PostgreSQL integration tests opt in through
# CAMPUSAI_TEST_POSTGRES_URL and use their own uniquely scoped rows.
os.environ["DATABASE_URL"] = "sqlite:///./campusai.db"
for _name in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
    os.environ[_name] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["GEMINI_PLACEMENT_API_KEY"] = ""
os.environ["GEMINI_CHAT_API_KEY"] = ""
os.environ["QDRANT_URL"] = ""
os.environ["QDRANT_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app import main as main_module


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = session_factory()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(db_session):
    original_engine = main_module.engine
    main_module.engine = db_session.get_bind()
    def override_db():
        yield db_session
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    main_module.engine = original_engine
