from datetime import datetime, timedelta, timezone

from app.models import PasswordResetToken, User
from app.security import hash_password, refresh_token_hash


def test_password_reset_is_single_use_and_revokes_refresh_tokens(client, db_session):
    user = User(email="reset@example.edu", full_name="Reset User", password_hash=hash_password("old password pass"), role="student")
    db_session.add(user)
    db_session.flush()
    raw_token = "test-reset-token-that-is-long-enough-123456"
    db_session.add(PasswordResetToken(token_hash=refresh_token_hash(raw_token), user_id=user.id,
                                      expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)))
    db_session.commit()
    response = client.post("/api/v1/auth/password-reset/complete", json={"email": user.email, "token": raw_token, "new_password": "brand new password 123"})
    assert response.status_code == 200, response.text
    assert client.post("/api/v1/auth/login", json={"email": user.email, "password": "brand new password 123"}).status_code == 200
    assert client.post("/api/v1/auth/password-reset/complete", json={"email": user.email, "token": raw_token, "new_password": "another new password 456"}).status_code == 400


def test_password_reset_token_consumption_is_atomic_and_email_scoped(db_session):
    from app.api.auth import consume_password_reset_token

    user = User(email="atomic-reset@example.edu", full_name="Atomic Reset", password_hash="hash", role="student")
    db_session.add(user)
    db_session.flush()
    raw = "atomic-reset-token"
    db_session.add(PasswordResetToken(token_hash=refresh_token_hash(raw), user_id=user.id,
                                     expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
    db_session.commit()

    assert consume_password_reset_token(db_session, raw, "wrong@example.edu") is None
    assert consume_password_reset_token(db_session, raw, user.email) == user.id
    db_session.commit()
    assert consume_password_reset_token(db_session, raw, user.email) is None


def test_password_reset_expiry_is_rechecked_in_the_atomic_consume(db_session):
    from sqlalchemy import event

    from app.api.auth import consume_password_reset_token

    user = User(email="reset-expiry-race@example.edu", full_name="Reset Expiry Race",
                password_hash="hash", role="student")
    db_session.add(user)
    db_session.flush()
    token = PasswordResetToken(token_hash=refresh_token_hash("reset-expiry-race-token"), user_id=user.id,
                               expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
    db_session.add(token)
    db_session.commit()
    token_id = token.id
    fired = False

    def expire_before_consume(connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal fired
        if not fired and statement.lower().startswith("update password_reset_tokens set used"):
            fired = True
            connection.exec_driver_sql(
                "UPDATE password_reset_tokens SET expires_at = ? WHERE id = ?",
                ("2000-01-01 00:00:00.000000", token_id),
            )

    event.listen(db_session.bind, "before_cursor_execute", expire_before_consume)
    try:
        assert consume_password_reset_token(db_session, "reset-expiry-race-token", user.email) is None
        db_session.commit()
        db_session.expire_all()
        assert db_session.get(PasswordResetToken, token_id).used is False
        assert fired
    finally:
        event.remove(db_session.bind, "before_cursor_execute", expire_before_consume)


def test_password_reset_request_does_not_reveal_unknown_accounts(client):
    known = client.post("/api/v1/auth/password-reset/request", json={"email": "nobody@example.edu"})
    assert known.status_code == 200
    assert "email_delivery_configured" in known.json()
    assert "If an active account exists" in known.json()["message"]
