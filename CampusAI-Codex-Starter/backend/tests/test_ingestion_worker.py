from datetime import datetime, timedelta, timezone

from app.models import Document, DocumentChunk, DocumentIngestionJob
from app.security import hash_password
from app import ingestion_worker


def _officer(client, db):
    from app.models import User
    user = User(email="queue-officer@example.edu", full_name="Queue Officer",
                password_hash=hash_password("correct horse battery"), role="placement_officer")
    db.add(user)
    db.commit()
    login = client.post("/api/v1/auth/login", json={"email": user.email, "password": "correct horse battery"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_queued_upload_worker_and_approval(client, db_session, monkeypatch, tmp_path):
    from app.api import documents as api
    from app.core.config import settings
    monkeypatch.setattr(settings, "document_ingestion_mode", "queued")
    monkeypatch.setattr(settings, "upload_directory", str(tmp_path / "unused"))
    monkeypatch.setattr(api, "scan_upload", lambda _content: None)
    monkeypatch.setattr(ingestion_worker, "index_chunks", lambda chunks: len(chunks))
    headers = _officer(client, db_session)
    response = client.post("/api/v1/documents/upload", headers=headers,
                           data={"title": "Queued policy", "category": "placement-policy"},
                           files={"file": ("policy.txt", b"COMPANY ELIGIBILITY RULES. Eligibility criteria: applicants need a minimum CGPA of 7.0.", "text/plain")})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["ingestion_status"] == "queued"
    assert db_session.query(DocumentChunk).count() == 0
    job = db_session.query(DocumentIngestionJob).one()
    assert job.payload == b"COMPANY ELIGIBILITY RULES. Eligibility criteria: applicants need a minimum CGPA of 7.0."
    assert not (tmp_path / "unused").exists()
    assert client.post(f"/api/v1/documents/{result['id']}/approve", headers=headers).status_code == 409

    assert ingestion_worker.process_next_ingestion_job(db_session)
    doc = db_session.get(Document, result["id"])
    job = db_session.query(DocumentIngestionJob).one()
    assert doc.ingestion_status == "completed"
    assert doc.suggested_category == "company-eligibility"
    assert job.status == "completed" and job.payload is None
    assert db_session.query(DocumentChunk).filter_by(document_id=doc.id).one().text == "COMPANY ELIGIBILITY RULES. Eligibility criteria: applicants need a minimum CGPA of 7.0."
    assert client.post(f"/api/v1/documents/{doc.id}/approve", headers=headers).status_code == 200


def test_worker_retries_transient_extraction_failure(client, db_session, monkeypatch):
    from app.api import documents as api
    from app.core.config import settings
    monkeypatch.setattr(settings, "document_ingestion_mode", "queued")
    monkeypatch.setattr(api, "scan_upload", lambda _content: None)
    headers = _officer(client, db_session)
    response = client.post("/api/v1/documents/upload", headers=headers,
                           data={"title": "Retry policy", "category": "general"},
                           files={"file": ("policy.txt", b"Retry extraction should eventually succeed.", "text/plain")})
    assert response.status_code == 201
    original = ingestion_worker.extract_pages
    monkeypatch.setattr(ingestion_worker, "extract_pages", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("temporary")))
    start = datetime.now(timezone.utc)
    assert ingestion_worker.process_next_ingestion_job(db_session, now=start)
    job = db_session.query(DocumentIngestionJob).one()
    assert job.status == "queued" and job.attempts == 1 and job.payload
    monkeypatch.setattr(ingestion_worker, "extract_pages", original)
    assert ingestion_worker.process_next_ingestion_job(db_session, now=start + timedelta(seconds=10))
    assert db_session.query(DocumentIngestionJob).one().status == "completed"


def test_reject_cancels_queued_job_and_discards_bytes(client, db_session, monkeypatch):
    from app.api import documents as api
    from app.core.config import settings
    monkeypatch.setattr(settings, "document_ingestion_mode", "queued")
    monkeypatch.setattr(api, "scan_upload", lambda _content: None)
    headers = _officer(client, db_session)
    response = client.post("/api/v1/documents/upload", headers=headers,
                           data={"title": "Cancelled policy", "category": "general"},
                           files={"file": ("policy.txt", b"This queued document will be rejected.", "text/plain")})
    doc_id = response.json()["id"]
    assert client.post(f"/api/v1/documents/{doc_id}/reject", headers=headers).status_code == 200
    job = db_session.query(DocumentIngestionJob).one()
    assert job.status == "cancelled" and job.payload is None
    assert not ingestion_worker.process_next_ingestion_job(db_session)

