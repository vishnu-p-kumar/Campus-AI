from datetime import datetime, timezone

from app.models import (
    Application, AuditLog, ChatMessage, Company, Conversation, InterviewResponse,
    InterviewSession, Notification, PasswordResetToken, PlacementDrive, PlacementRecord,
    RefreshToken, ResumeAnalysis, SkillGapAnalysis, StudentProfile, User,
)
from app.security import hash_password


def test_student_account_deletion_erases_user_owned_data_without_sqlite_cascades(client, db_session):
    email = "erase-everything@example.edu"
    registration = client.post("/api/v1/auth/register", json={
        "email": email, "full_name": "Erasure Test", "password": "correct horse battery",
    })
    assert registration.status_code == 201
    user = db_session.query(User).filter_by(email=email).one()
    user_id = user.id

    company = Company(name="Erasure Test Employer")
    db_session.add(company)
    db_session.flush()
    drive = PlacementDrive(company_id=company.id, title="Graduate role", role="Engineer")
    db_session.add(drive)
    resume = ResumeAnalysis(user_id=user_id, filename="resume.txt", skills=["python"])
    session = InterviewSession(user_id=user_id, category="technical", language="en", status="completed")
    conversation = Conversation(user_id=user_id, title="Private policy question")
    db_session.add_all([resume, session, conversation])
    db_session.flush()

    db_session.add_all([
        SkillGapAnalysis(user_id=user_id, resume_analysis_id=resume.id, job_description_hash="a" * 64),
        InterviewResponse(session_id=session.id, question="Explain a tradeoff", answer="Private answer", score=3.0),
        ChatMessage(conversation_id=conversation.id, role="user", content="Private question"),
        Application(student_user_id=user_id, drive_id=drive.id, status="applied"),
        PlacementRecord(student_user_id=user_id, company_id=company.id, drive_id=drive.id, role="Engineer"),
        Notification(user_id=user_id, title="Private notice", message="Private message"),
        RefreshToken(token_hash="b" * 64, user_id=user_id, expires_at=datetime.now(timezone.utc)),
        PasswordResetToken(token_hash="c" * 64, user_id=user_id, expires_at=datetime.now(timezone.utc)),
        AuditLog(actor_user_id=user_id, action="user.update", resource_type="user", resource_id=str(user_id), details={"is_active": False}),
    ])
    db_session.commit()

    result = client.delete("/api/v1/students/me", headers={"Authorization": f"Bearer {registration.json()['access_token']}"})
    assert result.status_code == 204
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {registration.json()['access_token']}"}).status_code == 401
    for model in (User, StudentProfile, Conversation, ChatMessage, InterviewSession, InterviewResponse,
                  ResumeAnalysis, SkillGapAnalysis, Application, Notification,
                  RefreshToken, PasswordResetToken):
        assert db_session.query(model).count() == 0, model.__name__
    anonymized_placement = db_session.query(PlacementRecord).one()
    assert anonymized_placement.student_user_id is None

    deletion_audit = db_session.query(AuditLog).filter_by(action="student.account_delete").one()
    assert deletion_audit.actor_user_id is None
    assert deletion_audit.resource_id is None
    assert deletion_audit.details == {"actor_erased": True}
    assert db_session.query(AuditLog).filter_by(action="user.update").one().resource_id is None

    administrator = User(email="retention-admin@example.edu", full_name="Retention Admin",
                         password_hash=hash_password("correct horse battery"), role="administrator")
    db_session.add(administrator)
    db_session.commit()
    login = client.post("/api/v1/auth/login", json={"email": administrator.email, "password": "correct horse battery"})
    records = client.get("/api/v1/admin/placement-records", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    retained = next(item for item in records.json() if item["company"] == "Erasure Test Employer")
    assert retained["student"] == "Former student (account deleted)"
    assert retained["student_email"] is None
