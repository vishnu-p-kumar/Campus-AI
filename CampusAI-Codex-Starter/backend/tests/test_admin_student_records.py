from app.models import StudentProfile, User
from app.security import hash_password, verify_password


def _headers(client, db_session):
    admin = User(email="student-record-admin@example.edu", full_name="Student Records Admin",
                 password_hash=hash_password("admin-password-2026"), role="administrator")
    db_session.add(admin)
    db_session.commit()
    response = client.post("/api/v1/auth/login", json={"email": admin.email, "password": "admin-password-2026"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_admin_can_create_and_update_student_record(client, db_session):
    headers = _headers(client, db_session)
    created = client.post("/api/v1/admin/students", headers=headers, json={
        "full_name": "Student Record Test", "email": "student-record@example.edu", "password": "student-password",
        "student_id": "SR-1042", "department": "Engineering", "branch": "Computer Science",
        "graduation_year": 2027, "cgpa": 8.4, "semester": 6, "active_backlogs": 0,
        "historical_backlogs": 1, "technical_skills": ["Python", "SQL"], "soft_skills": ["Teamwork"],
        "certifications": ["Cloud Fundamentals"], "projects": ["Placement portal"], "placement_status": "seeking",
    })
    assert created.status_code == 201
    student_id = created.json()["id"]
    assert created.json()["profile"]["student_id"] == "SR-1042"
    student = db_session.get(User, student_id)
    assert student and verify_password("student-password", student.password_hash)
    assert "password_hash" not in created.json()

    updated = client.put(f"/api/v1/admin/students/{student_id}", headers=headers, json={"cgpa": 9.1, "technical_skills": ["Python", "FastAPI"]})
    assert updated.status_code == 200
    assert updated.json()["profile"]["cgpa"] == 9.1
    assert updated.json()["profile"]["technical_skills"] == ["Python", "FastAPI"]


def test_students_cannot_create_or_edit_student_records(client, db_session):
    student = User(email="self-edit@example.edu", full_name="Self Edit Student",
                   password_hash=hash_password("student-password"), role="student")
    student.student_profile = StudentProfile()
    db_session.add(student)
    db_session.commit()
    response = client.post("/api/v1/auth/login", json={"email": student.email, "password": "student-password"})
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    assert client.post("/api/v1/admin/students", headers=headers, json={}).status_code == 403
    assert client.put("/api/v1/admin/students/1", headers=headers, json={"cgpa": 9}).status_code == 403
    assert client.put("/api/v1/students/me", headers=headers, json={"cgpa": 9}).status_code == 403
