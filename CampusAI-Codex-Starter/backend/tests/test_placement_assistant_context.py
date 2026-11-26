import logging
import sys
from types import ModuleType, SimpleNamespace

from app.api import documents as documents_api
from app.core.config import settings
from app.models import Company, CompanyRequirement, Notification, PlacementDrive, User
from app.security import hash_password


def test_chat_answer_removes_bold_markers_citation_numbers_and_source_blocks():
    from app.api.chat import _chat_answer_text

    answer = _chat_answer_text(
        "**Placement overview**\nAverage package: 8.2 LPA [1]\n\nSources:\n[1] Approved report"
    )
    assert answer == "Placement overview\nAverage package: 8.2 LPA"
    assert "**" not in answer
    assert "Sources:" not in answer


def test_chat_reports_missing_placement_dependency_clearly(client, db_session, monkeypatch, caplog):
    from app import placement_query_bot

    def fail_for_missing_dependency(*_args, **_kwargs):
        raise ModuleNotFoundError("dependency unavailable", name="pytz")

    monkeypatch.setattr(placement_query_bot, "ask", fail_for_missing_dependency)
    headers = staff_headers(client, db_session)
    with caplog.at_level(logging.ERROR, logger="app.api.chat"):
        response = client.post("/api/v1/chat/", headers=headers, json={
            "question": "How does placement training work?",
        })

    assert response.status_code == 503
    assert "server dependencies are missing" in response.json()["detail"]
    assert "category=dependency_missing module=pytz" in caplog.text


def staff_headers(client, db_session):
    staff = User(
        email="assistant-admin@example.edu",
        full_name="Assistant Admin",
        password_hash=hash_password("correct horse battery"),
        role="administrator",
    )
    db_session.add(staff)
    db_session.commit()
    response = client.post("/api/v1/auth/login", json={
        "email": staff.email,
        "password": "correct horse battery",
    })
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def student_headers(client, db_session):
    student = User(
        email="assistant-student@example.edu",
        full_name="Assistant Student",
        password_hash=hash_password("correct horse battery"),
        role="student",
    )
    db_session.add(student)
    db_session.commit()
    response = client.post("/api/v1/auth/login", json={
        "email": student.email,
        "password": "correct horse battery",
    })
    return student, {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_chat_uses_only_approved_admin_uploads_as_grounding(client, db_session, monkeypatch, tmp_path):
    from app.placement_query_bot import _load_service

    monkeypatch.setattr(settings, "upload_directory", str(tmp_path / "uploads"))
    monkeypatch.setattr(documents_api, "index_chunks", lambda chunks: len(chunks))
    service = _load_service()
    monkeypatch.delenv("JSONBIN_BIN_ID", raising=False)
    monkeypatch.delenv("JSONBIN_API_KEY", raising=False)
    monkeypatch.setattr(service, "router", lambda _question: SimpleNamespace(name="other", score=0.0))
    faq = ModuleType("faq")
    observed_sources = []

    def mocked_generate_answer(question, external_sources=None):
        observed_sources.append(external_sources)
        if external_sources:
            return "Grounded from uploaded file: " + external_sources[0]["text"], []
        return "No approved upload was supplied.", []

    faq.generate_answer = mocked_generate_answer
    faq.process_folder = lambda *_args, **_kwargs: iter(())
    monkeypatch.setitem(sys.modules, "faq", faq)
    headers = staff_headers(client, db_session)
    upload = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        data={"title": "Synthetic Placement Handbook", "category": "placement-policy"},
        files={"file": (
            "synthetic-placement-handbook.txt",
            b"The synthetic placement minimum CGPA is 7.65 for the 2026 cohort.",
            "text/plain",
        )},
    )
    assert upload.status_code == 201
    document_id = upload.json()["id"]
    question = "What does the synthetic placement handbook say about minimum CGPA?"

    pending = client.post("/api/v1/chat/", headers=headers, json={"question": question})
    assert pending.status_code == 200
    assert pending.json()["citations"] == []

    approved = client.post(f"/api/v1/documents/{document_id}/approve", headers=headers)
    assert approved.status_code == 200
    grounded = client.post("/api/v1/chat/", headers=headers, json={"question": question})
    assert grounded.status_code == 200
    assert observed_sources[-1][0]["document_id"] == document_id
    assert "7.65" in grounded.json()["answer"]
    assert grounded.json()["citations"][0]["document_id"] == document_id
    assert grounded.json()["citations"][0]["filename"] == "synthetic-placement-handbook.txt"

    history = client.get(
        f"/api/v1/chat/conversations/{grounded.json()['conversation_id']}",
        headers=headers,
    )
    assert history.status_code == 200
    assert history.json()[-1]["citations"][0]["document_id"] == document_id


def test_chat_answers_admin_company_profile_and_open_drive(client, db_session):
    headers = staff_headers(client, db_session)
    company = Company(
        name="Synthetic Robotics Ltd",
        industry="Robotics",
        description="Builds warehouse automation systems.",
        website="https://robotics.example.edu",
        job_roles=["Controls Engineer", "Software Engineer"],
    )
    company.requirements = CompanyRequirement(
        min_cgpa=7.25,
        eligible_branches=["CSE", "ECE"],
        graduation_years=[2026],
        max_active_backlogs=0,
        required_skills=["Python", "Control systems"],
        criteria_reviewed=True,
    )
    db_session.add(company)
    db_session.flush()
    db_session.add(PlacementDrive(
        company_id=company.id,
        title="Synthetic Robotics Campus Drive",
        role="Controls Engineer",
        package_lpa=12.5,
        location="Bengaluru",
        selection_process=["Technical interview", "HR interview"],
        status="open",
    ))
    db_session.commit()

    response = client.post("/api/v1/chat/", headers=headers, json={
        "question": "Tell me about Synthetic Robotics Ltd company profile, roles, and drive details."
    })
    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "Builds warehouse automation systems" in answer
    assert "Controls Engineer" in answer
    assert "7.25" in answer
    assert "12.5 LPA" in answer
    assert response.json()["citations"][0]["source_type"] == "company_record"
    assert response.json()["citations"][0]["company_id"] == company.id


def test_candidate_can_get_full_notification_by_title_without_marking_it_read(client, db_session):
    student, headers = student_headers(client, db_session)
    notice = Notification(
        user_id=student.id,
        title="Synthetic interview schedule",
        message="Your interview begins Friday at 10:30 AM in Room 204.",
    )
    db_session.add(notice)
    db_session.commit()

    response = client.post("/api/v1/chat/", headers=headers, json={
        "question": "Show me the full message named Synthetic interview schedule."
    })
    assert response.status_code == 200
    assert "Your interview begins Friday at 10:30 AM in Room 204." in response.json()["answer"]
    assert response.json()["citations"][0]["source_type"] == "notification_record"
    assert response.json()["citations"][0]["notification_id"] == notice.id
    db_session.refresh(notice)
    assert notice.read_at is None


def test_staff_can_check_a_named_candidates_unread_notification(client, db_session):
    staff = staff_headers(client, db_session)
    student = User(
        email="named-candidate@example.edu",
        full_name="Named Candidate",
        password_hash=hash_password("correct horse battery"),
        role="student",
    )
    db_session.add(student)
    db_session.flush()
    notice = Notification(
        user_id=student.id,
        title="Synthetic drive update",
        message="A placement drive is open for your branch.",
    )
    db_session.add(notice)
    db_session.commit()

    response = client.post("/api/v1/chat/", headers=staff, json={
        "question": "Show unread notifications for candidate Named Candidate."
    })
    assert response.status_code == 200
    assert "Notifications for Named Candidate" in response.json()["answer"]
    assert "Synthetic drive update" in response.json()["answer"]
    assert response.json()["citations"][0]["notification_id"] == notice.id
