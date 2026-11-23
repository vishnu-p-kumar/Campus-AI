from datetime import datetime, timedelta, timezone
import os
from threading import Event, Thread
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker


@pytest.mark.skipif(not os.getenv("CAMPUSAI_TEST_POSTGRES_URL"), reason="requires disposable PostgreSQL test service")
def test_document_approval_serializes_against_eligibility_application(monkeypatch):
    from app.api import documents, placement
    from app.models import (
        Application,
        AuditLog,
        Company,
        CompanyRequirement,
        Document,
        PlacementDrive,
        ResumeAnalysis,
        StudentProfile,
        User,
    )

    engine = create_engine(os.environ["CAMPUSAI_TEST_POSTGRES_URL"], pool_size=4, max_overflow=0)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    unique = uuid4().hex
    title = f"Policy approval race {unique}"
    email = f"{unique}@example.edu"
    company_name = f"Policy race {unique}"
    admin_id = student_id = company_id = old_doc_id = new_doc_id = drive_id = requirement_id = None
    approval_has_lock = Event()
    release_approval = Event()
    application_waiting = Event()
    application_done = Event()
    approval_errors = []
    application_result = []
    original_document_lock = documents._lock_document_scope
    original_application_lock = placement.lock_document_scope

    for model in (User, StudentProfile, Company, Document, CompanyRequirement, PlacementDrive, Application, AuditLog, ResumeAnalysis):
        model.__table__.create(engine, checkfirst=True)

    try:
        with sessions.begin() as db:
            admin = User(email=f"admin-{email}", full_name="Placement Admin", password_hash="unused", role="administrator")
            student = User(email=email, full_name="Eligible Student", password_hash="unused", role="student")
            db.add_all([admin, student])
            db.flush()
            db.add(StudentProfile(
                user_id=student.id,
                student_id=f"ST-{unique}",
                branch="Computer Science",
                graduation_year=2027,
                cgpa=8.5,
                active_backlogs=0,
                historical_backlogs=0,
                technical_skills=["Python"],
            ))
            db.add(ResumeAnalysis(user_id=student.id, filename="resume.txt"))
            company = Company(name=company_name)
            db.add(company)
            db.flush()
            old_doc = Document(
                title=title, category="company-eligibility", company_id=company.id,
                academic_year="2026-27", filename="policy-v1.txt", storage_path="unused",
                version=1, approval_status="approved", ingestion_status="completed", uploaded_by=admin.id,
            )
            db.add(old_doc)
            db.flush()
            new_doc = Document(
                title=title, category="company-eligibility", company_id=company.id,
                academic_year="2026-27", filename="policy-v2.txt", storage_path="unused",
                version=2, approval_status="pending", ingestion_status="completed",
                supersedes_id=old_doc.id, uploaded_by=admin.id,
            )
            db.add(new_doc)
            db.flush()
            requirement = CompanyRequirement(
                company_id=company.id,
                min_cgpa=7.0,
                eligible_branches=["Computer Science"],
                graduation_years=[2027],
                max_active_backlogs=0,
                max_historical_backlogs=1,
                required_skills=["Python"],
                criteria_reviewed=True,
                source_document_id=old_doc.id,
            )
            drive = PlacementDrive(
                company_id=company.id,
                title="Race Test Drive",
                role="Software Engineer",
                application_deadline=datetime.now(timezone.utc) + timedelta(days=3),
            )
            db.add_all([requirement, drive])
            db.flush()
            admin_id, student_id = admin.id, student.id
            company_id, old_doc_id, new_doc_id = company.id, old_doc.id, new_doc.id
            requirement_id, drive_id = requirement.id, drive.id

        def pause_after_scope_lock(db, scope_title, scope_company_id, academic_year):
            original_document_lock(db, scope_title, scope_company_id, academic_year)
            approval_has_lock.set()
            if not release_approval.wait(timeout=10):
                raise TimeoutError("approval test did not release its policy-scope lock")

        def observe_application_lock(db, scope_title, scope_company_id, academic_year):
            application_waiting.set()
            return original_application_lock(db, scope_title, scope_company_id, academic_year)

        monkeypatch.setattr(documents, "_lock_document_scope", pause_after_scope_lock)
        monkeypatch.setattr(placement, "lock_document_scope", observe_application_lock)
        monkeypatch.setattr(documents, "index_chunks", lambda _records: 0)

        def approve_new_version():
            try:
                with sessions() as db:
                    actor = db.get(User, admin_id)
                    documents.approve_document(new_doc_id, actor=actor, db=db)
            except Exception as exc:
                approval_errors.append(exc)

        def apply_to_drive():
            try:
                with sessions() as db:
                    student = db.get(User, student_id)
                    try:
                        application_result.append(("created", placement.apply_to_drive(drive_id, user=student, db=db)))
                    except HTTPException as exc:
                        application_result.append(("rejected", exc.status_code))
                    except Exception as exc:
                        application_result.append(("error", type(exc).__name__))
            finally:
                application_done.set()

        approval_thread = Thread(target=approve_new_version, daemon=True)
        application_thread = Thread(target=apply_to_drive, daemon=True)
        approval_thread.start()
        assert approval_has_lock.wait(timeout=5), "approval did not acquire the policy-scope lock"
        application_thread.start()
        assert application_waiting.wait(timeout=5), "application did not reach the policy-scope lock"
        assert not application_done.wait(timeout=0.5), "application bypassed the active approval transaction"
        release_approval.set()
        approval_thread.join(timeout=10)
        application_thread.join(timeout=10)
        assert not approval_thread.is_alive() and not application_thread.is_alive()
        assert not approval_errors
        assert application_result == [("rejected", 409)], application_result

        with sessions() as db:
            assert db.get(Document, old_doc_id).approval_status == "superseded"
            assert db.get(Document, new_doc_id).approval_status == "approved"
            assert db.query(Application).filter_by(student_user_id=student_id, drive_id=drive_id).count() == 0
    finally:
        release_approval.set()
        approval_thread = locals().get("approval_thread")
        application_thread = locals().get("application_thread")
        if approval_thread:
            approval_thread.join(timeout=10)
        if application_thread:
            application_thread.join(timeout=10)
        with engine.begin() as connection:
            if drive_id is not None:
                connection.execute(delete(Application).where(Application.drive_id == drive_id))
            if new_doc_id is not None:
                connection.execute(delete(AuditLog).where(AuditLog.resource_id == str(new_doc_id)))
            if requirement_id is not None:
                connection.execute(delete(CompanyRequirement).where(CompanyRequirement.id == requirement_id))
            if drive_id is not None:
                connection.execute(delete(PlacementDrive).where(PlacementDrive.id == drive_id))
            if new_doc_id is not None:
                connection.execute(delete(Document).where(Document.id == new_doc_id))
            if old_doc_id is not None:
                connection.execute(delete(Document).where(Document.id == old_doc_id))
            if company_id is not None:
                connection.execute(delete(Company).where(Company.id == company_id))
            if student_id is not None:
                connection.execute(delete(StudentProfile).where(StudentProfile.user_id == student_id))
                connection.execute(delete(User).where(User.id == student_id))
            if admin_id is not None:
                connection.execute(delete(User).where(User.id == admin_id))
        engine.dispose()
