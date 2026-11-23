from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select


@pytest.mark.skipif(not os.getenv("CAMPUSAI_TEST_POSTGRES_URL"), reason="requires disposable PostgreSQL test service")
def test_postgres_auth_throttle_is_atomic_across_concurrent_connections(monkeypatch):
    from app import main as main_module
    from app.core.config import settings
    from app.models import AuthRateLimitBucket

    engine = create_engine(os.environ["CAMPUSAI_TEST_POSTGRES_URL"], pool_size=12, max_overflow=0)
    address = f"postgres-auth-test-{uuid4()}"
    digest = hmac.new(settings.jwt_secret_key.encode(), address.encode(), hashlib.sha256).hexdigest()
    first_window = int(time.time() // 60) * 60
    test_engine = main_module.engine
    try:
        AuthRateLimitBucket.__table__.create(engine, checkfirst=True)
        monkeypatch.setattr(main_module, "engine", engine)
        monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 20)
        with ThreadPoolExecutor(max_workers=12) as pool:
            decisions = list(pool.map(
                lambda _: main_module.consume_auth_rate_limit(address, now=first_window), range(32)
            ))

        assert sum(allowed for allowed, _ in decisions) == 20
        assert sum(not allowed for allowed, _ in decisions) == 12
        with engine.connect() as connection:
            attempts = connection.execute(select(AuthRateLimitBucket.attempts).where(
                AuthRateLimitBucket.rate_key == digest,
                AuthRateLimitBucket.window_start == first_window // 60,
            )).scalar_one()
        assert attempts == 32

    finally:
        monkeypatch.setattr(main_module, "engine", test_engine)
        with engine.begin() as connection:
            connection.execute(delete(AuthRateLimitBucket).where(AuthRateLimitBucket.rate_key == digest))
        engine.dispose()


@pytest.mark.skipif(not os.getenv("CAMPUSAI_TEST_POSTGRES_URL"), reason="requires disposable PostgreSQL test service")
def test_postgres_refresh_token_can_only_be_consumed_once():
    from sqlalchemy.orm import sessionmaker

    from app.api.auth import consume_refresh_token
    from app.models import RefreshToken, User
    from app.security import refresh_token_hash

    engine = create_engine(os.environ["CAMPUSAI_TEST_POSTGRES_URL"], pool_size=12, max_overflow=0)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    raw = f"postgres-refresh-test-{uuid4()}"
    email = f"{uuid4()}@example.edu"
    User.__table__.create(engine, checkfirst=True)
    RefreshToken.__table__.create(engine, checkfirst=True)
    try:
        with sessions.begin() as session:
            user = User(email=email, full_name="Refresh Test", password_hash="unused", role="student")
            session.add(user)
            session.flush()
            user_id = user.id
            session.add(RefreshToken(token_hash=refresh_token_hash(raw), user_id=user_id,
                                     expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)))

        def consume(_index):
            with sessions.begin() as session:
                return consume_refresh_token(session, raw)

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(consume, range(32)))

        assert results.count(user_id) == 1
        assert results.count(None) == 31
    finally:
        with engine.begin() as connection:
            connection.execute(delete(RefreshToken).where(RefreshToken.token_hash == refresh_token_hash(raw)))
            connection.execute(delete(User).where(User.email == email))
        engine.dispose()


@pytest.mark.skipif(not os.getenv("CAMPUSAI_TEST_POSTGRES_URL"), reason="requires disposable PostgreSQL test service")
def test_postgres_password_reset_token_can_only_be_consumed_once():
    from sqlalchemy.orm import sessionmaker

    from app.api.auth import consume_password_reset_token
    from app.models import PasswordResetToken, User
    from app.security import refresh_token_hash

    engine = create_engine(os.environ["CAMPUSAI_TEST_POSTGRES_URL"], pool_size=12, max_overflow=0)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    raw = f"postgres-reset-test-{uuid4()}"
    email = f"{uuid4()}@example.edu"
    User.__table__.create(engine, checkfirst=True)
    PasswordResetToken.__table__.create(engine, checkfirst=True)
    try:
        with sessions.begin() as session:
            user = User(email=email, full_name="Reset Test", password_hash="unused", role="student")
            session.add(user)
            session.flush()
            user_id = user.id
            session.add(PasswordResetToken(token_hash=refresh_token_hash(raw), user_id=user_id,
                                           expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)))

        def consume(_index):
            with sessions.begin() as session:
                return consume_password_reset_token(session, raw, email)

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(consume, range(32)))

        assert results.count(user_id) == 1
        assert results.count(None) == 31
    finally:
        with engine.begin() as connection:
            connection.execute(delete(PasswordResetToken).where(PasswordResetToken.token_hash == refresh_token_hash(raw)))
            connection.execute(delete(User).where(User.email == email))
        engine.dispose()
