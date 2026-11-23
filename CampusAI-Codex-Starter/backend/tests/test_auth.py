def test_student_registration_profile_and_role_boundary(client):
    response = client.post("/api/v1/auth/register", json={
        "email": "student@example.edu", "full_name": "Test Student", "password": "correct horse battery",
    })
    assert response.status_code == 201
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    profile = client.get("/api/v1/students/me", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["user_id"] == response.json()["user"]["id"]

    admin = client.get("/api/v1/admin/analytics", headers=headers)
    assert admin.status_code == 403


def test_registration_accepts_six_character_password_and_rejects_shorter(client):
    short = client.post("/api/v1/auth/register", json={
        "email": "short-password@example.edu", "full_name": "Short Password", "password": "abc12",
    })
    assert short.status_code == 422
    accepted = client.post("/api/v1/auth/register", json={
        "email": "six-password@example.edu", "full_name": "Six Password", "password": "abc123",
    })
    assert accepted.status_code == 201


def test_refresh_token_rotates_and_logout_revokes(client):
    login = client.post("/api/v1/auth/register", json={
        "email": "rotate@example.edu", "full_name": "Rotate User", "password": "correct horse battery",
    })
    assert "campusai_refresh" in client.cookies
    refreshed = client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    old = login.cookies.get("campusai_refresh")
    current = refreshed.cookies.get("campusai_refresh")
    client.cookies.set("campusai_refresh", old)
    assert client.post("/api/v1/auth/refresh").status_code == 401
    client.cookies.set("campusai_refresh", current)
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_refresh_token_consumption_is_one_time(db_session):
    from datetime import datetime, timedelta, timezone

    from app.api.auth import consume_refresh_token
    from app.models import RefreshToken, User
    from app.security import refresh_token_hash

    user = User(email="refresh-once@example.edu", full_name="Refresh Once", password_hash="hash", role="student")
    db_session.add(user)
    db_session.flush()
    raw = "one-time-refresh-token"
    db_session.add(RefreshToken(token_hash=refresh_token_hash(raw), user_id=user.id,
                                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
    db_session.commit()

    assert consume_refresh_token(db_session, raw) == user.id
    db_session.commit()
    assert consume_refresh_token(db_session, raw) is None


def test_refresh_token_expiry_is_rechecked_in_the_atomic_consume(db_session):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import event

    from app.api.auth import consume_refresh_token
    from app.models import RefreshToken, User
    from app.security import refresh_token_hash

    user = User(email="refresh-expiry-race@example.edu", full_name="Expiry Race", password_hash="hash", role="student")
    db_session.add(user)
    db_session.flush()
    token = RefreshToken(token_hash=refresh_token_hash("expiry-race-token"), user_id=user.id,
                         expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
    db_session.add(token)
    db_session.commit()
    token_id = token.id
    fired = False

    def expire_before_consume(connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal fired
        if not fired and statement.lower().startswith("update refresh_tokens set revoked"):
            fired = True
            connection.exec_driver_sql(
                "UPDATE refresh_tokens SET expires_at = ? WHERE id = ?",
                ("2000-01-01 00:00:00.000000", token_id),
            )

    event.listen(db_session.bind, "before_cursor_execute", expire_before_consume)
    try:
        assert consume_refresh_token(db_session, "expiry-race-token") is None
        db_session.commit()
        db_session.expire_all()
        assert db_session.get(RefreshToken, token_id).revoked is False
        assert fired
    finally:
        event.remove(db_session.bind, "before_cursor_execute", expire_before_consume)


def test_production_cookie_session_requests_require_an_origin(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "environment", "production")
    credentials = {"email": "origin-required@example.edu", "full_name": "Origin Required", "password": "correct horse battery"}
    assert client.post("/api/v1/auth/register", json=credentials).status_code == 403
    assert client.post("/api/v1/auth/login", json={"email": credentials["email"], "password": credentials["password"]}).status_code == 403
    assert client.post("/api/v1/auth/refresh").status_code == 403
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post("/api/v1/auth/login", headers={"Origin": "https://attacker.example"},
                       json={"email": credentials["email"], "password": credentials["password"]}).status_code == 403


def test_auth_throttle_is_database_backed_and_returns_window_retry(client, db_session):
    from app.models import AuthRateLimitBucket

    for _ in range(20):
        assert client.post("/api/v1/auth/refresh").status_code == 401
    limited = client.post("/api/v1/auth/refresh")
    assert limited.status_code == 429
    assert 1 <= int(limited.headers["Retry-After"]) <= 60
    rows = db_session.query(AuthRateLimitBucket).all()
    assert len(rows) == 1
    assert rows[0].attempts == 21
    assert rows[0].rate_key != "127.0.0.1"


def test_auth_throttle_upsert_is_atomic_for_concurrent_requests(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine
    from sqlalchemy import select

    from app import main as main_module
    from app.db import Base
    from app.models import AuthRateLimitBucket
    test_engine = create_engine(f"sqlite:///{tmp_path / 'limits.db'}", connect_args={"timeout": 30})
    Base.metadata.create_all(test_engine)
    monkeypatch.setattr(main_module, "engine", test_engine)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            decisions = list(pool.map(lambda _: main_module.consume_auth_rate_limit("shared-client", now=1200), range(24)))
        assert sum(allowed for allowed, _ in decisions) == 20
        assert sum(not allowed for allowed, _ in decisions) == 4
        with test_engine.connect() as connection:
            attempts = connection.execute(select(AuthRateLimitBucket.attempts)).scalar_one()
            assert attempts == 24
    finally:
        test_engine.dispose()
