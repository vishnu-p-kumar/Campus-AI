from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.api.placement import persist_application
from app.models import Application, Company, CompanyRequirement, Document, Notification, PlacementDrive, StudentProfile, User
from app.core.config import settings
from app.security import hash_password


def test_apply_and_record_selection(client, db_session, tmp_path):
    settings.upload_directory = str(tmp_path)
    student = User(email="candidate@example.edu", full_name="Candidate", password_hash=hash_password("correct horse battery"), role="student")
    student.student_profile = StudentProfile(cgpa=8.5, branch="Computer Science", graduation_year=2027, active_backlogs=0,
                                             historical_backlogs=0, technical_skills=["Python", "SQL"])
    admin = User(email="officer@example.edu", full_name="Officer", password_hash=hash_password("correct horse battery"), role="placement_officer")
    db_session.add_all([student, admin])
    db_session.flush()
    policy = Document(title="Company rule source", category="company-eligibility", filename="criteria.txt", storage_path="unused",
                      version=1, approval_status="approved", uploaded_by=admin.id)
    db_session.add(policy)
    db_session.flush()
    company = Company(name="Verified Company", industry="Technology", job_roles=["Engineer"])
    company.requirements = CompanyRequirement(min_cgpa=7.5, eligible_branches=["Computer Science"], graduation_years=[2027],
                                              max_active_backlogs=0, max_historical_backlogs=1, required_skills=["Python"],
                                              criteria_reviewed=True, source_document_id=policy.id)
    db_session.add(company)
    db_session.flush()
    drive = PlacementDrive(company_id=company.id, title="Graduate Engineer", role="Software Engineer")
    db_session.add(drive)
    db_session.commit()

    student_token = client.post("/api/v1/auth/login", json={"email": student.email, "password": "correct horse battery"}).json()["access_token"]
    student_headers = {"Authorization": f"Bearer {student_token}"}
    missing_resume = client.post(f"/api/v1/placement-drives/{drive.id}/apply", headers=student_headers)
    assert missing_resume.status_code == 422
    applied = client.post(f"/api/v1/placement-drives/{drive.id}/apply", headers=student_headers,
                          files={"resume": ("candidate.txt", b"Candidate resume text", "text/plain")})
    assert applied.status_code == 201, applied.text
    application_id = applied.json()["id"]
    assert applied.json()["resume_filename"] == "candidate.txt"
    application = db_session.get(Application, application_id)
    assert application.resume_storage_path and open(application.resume_storage_path, "rb").read() == b"Candidate resume text"
    dashboard = client.get("/api/v1/students/me/dashboard", headers=student_headers)
    assert dashboard.status_code == 200
    assert any(item["id"] == application_id and item["status"] == "applied" for item in dashboard.json()["applications"])
    officer_token = client.post("/api/v1/auth/login", json={"email": admin.email, "password": "correct horse battery"}).json()["access_token"]
    officer_headers = {"Authorization": f"Bearer {officer_token}"}
    downloaded = client.get(f"/api/v1/placement-drives/applications/{application_id}/resume", headers=officer_headers)
    assert downloaded.status_code == 200 and downloaded.content == b"Candidate resume text"
    assert "candidate.txt" in downloaded.headers["content-disposition"]
    assert client.get(f"/api/v1/placement-drives/applications/{application_id}/resume", headers=student_headers).content == b"Candidate resume text"
    with pytest.raises(HTTPException) as duplicate:
        persist_application(db_session, student.id, drive.id)
    assert duplicate.value.status_code == 409

    selected = client.patch(f"/api/v1/placement-drives/applications/{application_id}/status", headers=officer_headers, json={"status": "selected"})
    assert selected.status_code == 200
    notifications = client.get("/api/v1/notifications/", headers={"Authorization": f"Bearer {student_token}"})
    assert notifications.status_code == 200
    assert len(notifications.json()) == 1
    assert "Software Engineer" in notifications.json()[0]["message"]
    eligibility = client.get(f"/api/v1/companies/{company.id}/eligibility", headers=student_headers)
    assert eligibility.status_code == 200 and eligibility.json()["decision"] == "eligible"
    policy.approval_status = "superseded"
    db_session.commit()
    stale_rule = client.get(f"/api/v1/companies/{company.id}/eligibility", headers=student_headers)
    assert stale_rule.status_code == 200 and stale_rule.json()["decision"] == "needs_manual_verification"
    stale_apply = client.post(f"/api/v1/placement-drives/{drive.id}/apply", headers=student_headers,
                              files={"resume": ("candidate.txt", b"Candidate resume text", "text/plain")})
    assert stale_apply.status_code == 409
    assert stale_apply.json()["detail"]["eligibility"]["decision"] == "needs_manual_verification"
    repeated = client.patch(f"/api/v1/placement-drives/applications/{application_id}/status", headers=officer_headers, json={"status": "selected"})
    assert repeated.status_code == 200
    assert len(client.get("/api/v1/notifications/", headers={"Authorization": f"Bearer {student_token}"}).json()) == 1
    records = client.get("/api/v1/admin/placement-records", headers=officer_headers)
    assert records.status_code == 200
    assert records.json()[0]["company"] == "Verified Company"
    company_applications = client.get("/api/v1/admin/applications", headers=officer_headers)
    assert company_applications.status_code == 200
    assert company_applications.json()[0]["company_id"] == company.id
    assert company_applications.json()[0]["resume_filename"] == "candidate.txt"

    expired_drive = PlacementDrive(company_id=company.id, title="Expired Drive", role="Expired Engineer",
                                   application_deadline=datetime.now(timezone.utc) - timedelta(days=1), status="open")
    db_session.add(expired_drive)
    db_session.commit()
    listed = client.get("/api/v1/placement-drives/", headers=officer_headers)
    assert listed.status_code == 200
    assert next(item for item in listed.json() if item["id"] == expired_drive.id)["status"] == "closed"
    student_listed = client.get("/api/v1/placement-drives/", headers=student_headers)
    assert all(item["id"] != expired_drive.id for item in student_listed.json())
    expired_apply = client.post(f"/api/v1/placement-drives/{expired_drive.id}/apply", headers=student_headers,
                                files={"resume": ("candidate.txt", b"Candidate resume text", "text/plain")})
    assert expired_apply.status_code == 409
    assert "deadline" in expired_apply.json()["detail"].lower()


def test_student_company_and_drive_lists_hide_companies_they_are_not_eligible_for(client, db_session):
    student = User(email="eligible-list@example.edu", full_name="Eligible List", password_hash=hash_password("correct horse battery"), role="student")
    student.student_profile = StudentProfile(cgpa=8.5, branch="Computer Science", graduation_year=2027,
                                             active_backlogs=0, historical_backlogs=0)
    admin = User(email="eligible-list-admin@example.edu", full_name="Admin", password_hash=hash_password("correct horse battery"), role="administrator")
    db_session.add_all([student, admin])
    db_session.flush()
    eligible_policy = Document(title="Eligible company criteria", category="company-eligibility", filename="eligible.txt",
                               storage_path="unused", version=1, approval_status="approved", uploaded_by=admin.id)
    ineligible_policy = Document(title="Ineligible company criteria", category="company-eligibility", filename="ineligible.txt",
                                 storage_path="unused", version=1, approval_status="approved", uploaded_by=admin.id)
    db_session.add_all([eligible_policy, ineligible_policy])
    db_session.flush()
    eligible_company = Company(name="Eligible Systems")
    eligible_company.requirements = CompanyRequirement(
        min_cgpa=7.0, eligible_branches=["Computer Science"], graduation_years=[2027],
        max_active_backlogs=0, max_historical_backlogs=0, criteria_reviewed=True,
        source_document_id=eligible_policy.id,
    )
    ineligible_company = Company(name="Higher Cutoff Systems")
    ineligible_company.requirements = CompanyRequirement(
        min_cgpa=9.0, eligible_branches=["Computer Science"], graduation_years=[2027],
        max_active_backlogs=0, max_historical_backlogs=0, criteria_reviewed=True,
        source_document_id=ineligible_policy.id,
    )
    db_session.add_all([eligible_company, ineligible_company])
    db_session.flush()
    db_session.add_all([
        PlacementDrive(company_id=eligible_company.id, title="Eligible intake", role="Engineer"),
        PlacementDrive(company_id=ineligible_company.id, title="High cutoff intake", role="Engineer"),
    ])
    db_session.commit()

    student_token = client.post("/api/v1/auth/login", json={
        "email": student.email, "password": "correct horse battery",
    }).json()["access_token"]
    admin_token = client.post("/api/v1/auth/login", json={
        "email": admin.email, "password": "correct horse battery",
    }).json()["access_token"]
    student_headers = {"Authorization": f"Bearer {student_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    visible_companies = client.get("/api/v1/companies/", headers=student_headers).json()
    visible_drives = client.get("/api/v1/placement-drives/", headers=student_headers).json()
    all_companies = client.get("/api/v1/companies/", headers=admin_headers).json()
    all_drives = client.get("/api/v1/placement-drives/", headers=admin_headers).json()
    assert [row["name"] for row in visible_companies] == ["Eligible Systems"]
    assert [row["company_name"] for row in visible_drives] == ["Eligible Systems"]
    assert len(all_companies) == 2
    assert len(all_drives) == 2


def test_student_cannot_update_profile(client):
    register = client.post("/api/v1/auth/register", json={"email": "partial@example.edu", "full_name": "Partial Profile", "password": "correct horse battery"})
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}
    profile = client.put("/api/v1/students/me", headers=headers, json={"technical_skills": ["Python"]})
    assert profile.status_code == 403
    assert "administrator" in profile.json()["detail"].lower()


def test_placement_assistant_answers_only_the_students_notification_status(client, db_session):
    student = User(email="notification-chat@example.edu", full_name="Notification Chat", password_hash=hash_password("correct horse battery"), role="student")
    other = User(email="other-notification@example.edu", full_name="Other Student", password_hash=hash_password("correct horse battery"), role="student")
    db_session.add_all([student, other])
    db_session.flush()
    db_session.add_all([
        Notification(user_id=student.id, title="Interview scheduled", message="Your interview is Friday."),
        Notification(user_id=student.id, title="Application update", message="Your application entered screening.", read_at=datetime.now(timezone.utc)),
        Notification(user_id=other.id, title="Private update", message="This belongs to another student."),
    ])
    db_session.commit()
    token = client.post("/api/v1/auth/login", json={"email": student.email, "password": "correct horse battery"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    received = client.post("/api/v1/chat/", headers=headers, json={"question": "What notifications have I received?"})
    assert received.status_code == 200
    assert "Interview scheduled" in received.json()["answer"]
    assert "unread" in received.json()["answer"]
    assert "Application update" in received.json()["answer"]
    assert "read" in received.json()["answer"]
    assert "Private update" not in received.json()["answer"]
    assert received.json()["citations"][0]["source_type"] == "notification_record"

    unread_count = client.post("/api/v1/chat/", headers=headers, json={"question": "How many unread notifications do I have?"})
    assert unread_count.status_code == 200
    assert "1 unread notification" in unread_count.json()["answer"]

    read_list = client.post("/api/v1/chat/", headers=headers, json={"question": "Which notifications have I marked read?"})
    assert read_list.status_code == 200
    assert "Application update" in read_list.json()["answer"]
    assert "Interview scheduled" not in read_list.json()["answer"]


def test_application_status_lock_returns_current_row(db_session):
    from app.api.placement import lock_application_for_update
    from app.models import Application, Company, PlacementDrive

    user = User(email="status-lock@example.edu", full_name="Status Lock", password_hash="hash", role="student")
    company = Company(name="Status Lock Company")
    db_session.add_all([user, company])
    db_session.flush()
    drive = PlacementDrive(company_id=company.id, title="Status lock drive", role="Engineer")
    db_session.add(drive)
    db_session.flush()
    application = Application(student_user_id=user.id, drive_id=drive.id, status="screening")
    db_session.add(application)
    db_session.commit()

    locked = lock_application_for_update(db_session, application.id)
    assert locked.status == "screening"
