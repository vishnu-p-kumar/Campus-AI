from app.models import User
from app.security import hash_password


def test_admin_user_listing_handles_legacy_reserved_email_domains(client, db_session):
    admin = User(
        email="admin-users@example.edu",
        full_name="Admin User Listing",
        password_hash=hash_password("e2e-administrator-password-2026"),
        role="administrator",
    )
    legacy_user = User(
        email="archived-user@example.invalid",
        full_name="Archived Test User",
        password_hash=hash_password("legacy-test-password"),
        role="student",
    )
    db_session.add_all([admin, legacy_user])
    db_session.commit()

    login = client.post("/api/v1/auth/login", json={
        "email": admin.email,
        "password": "e2e-administrator-password-2026",
    })
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.get("/api/v1/admin/users", headers=headers)

    assert response.status_code == 200
    assert any(row["email"] == "archived-user@example.invalid" for row in response.json())
