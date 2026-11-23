from app.models import User
from app.security import hash_password


def test_admin_dashboard_chat_usage_count_uses_persisted_messages(client, db_session):
    student = client.post("/api/v1/auth/register", json={
        "email": "analytics-student@example.edu", "full_name": "Analytics Student", "password": "correct horse battery",
    })
    student_headers = {"Authorization": f"Bearer {student.json()['access_token']}"}
    chat = client.post("/api/v1/chat/", headers=student_headers, json={"question": "What is the cafeteria menu next Tuesday?"})
    assert chat.status_code == 200

    admin = User(email="analytics-admin@example.edu", full_name="Analytics Admin",
                 password_hash=hash_password("e2e-administrator-password-2026"), role="administrator")
    db_session.add(admin)
    db_session.commit()
    login = client.post("/api/v1/auth/login", json={"email": admin.email, "password": "e2e-administrator-password-2026"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    metrics = client.get("/api/v1/admin/analytics", headers=headers)

    assert metrics.status_code == 200
    assert metrics.json()["chat_messages"] == 2
    assert metrics.json()["students"] == 1
