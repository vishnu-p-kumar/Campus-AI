from datetime import datetime, timezone

from app.ai.retrieval import retrieve
from app.models import Company, Document, User
from app.security import hash_password
from app.upload_scan import MalwareDetected, ScannerUnavailable


def test_postgres_document_scope_lock_uses_stable_scope_key():
    from types import SimpleNamespace

    from app.api.documents import _lock_document_scope

    class RecordingSession:
        def __init__(self):
            self.statement = None
            self.parameters = None

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement, parameters):
            self.statement = str(statement)
            self.parameters = parameters

    db = RecordingSession()
    _lock_document_scope(db, "Rules", 7, "2026-27")
    first_key = db.parameters["scope_lock_key"]
    assert "pg_advisory_xact_lock" in db.statement
    _lock_document_scope(db, "Rules", 7, "2026-27")
    assert db.parameters["scope_lock_key"] == first_key
    _lock_document_scope(db, "Rules", 8, "2026-27")
    assert db.parameters["scope_lock_key"] != first_key


def admin_headers(client, db_session):
    admin = User(email="officer@example.edu", full_name="Placement Officer", password_hash=hash_password("correct horse battery"), role="placement_officer")
    db_session.add(admin)
    db_session.commit()
    response = client.post("/api/v1/auth/login", json={"email": admin.email, "password": "correct horse battery"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def upload_policy(client, headers, title, content, effective):
    return client.post("/api/v1/documents/upload", headers=headers,
                       data={"title": title, "category": "placement-policy", "effective_date": effective},
                       files={"file": ("policy.txt", content.encode(), "text/plain")})


def test_document_approval_and_temporal_versioning(client, db_session, monkeypatch, tmp_path):
    from app.core.config import settings
    monkeypatch.setattr(settings, "upload_directory", str(tmp_path / "uploads"))
    headers = admin_headers(client, db_session)

    first = upload_policy(client, headers, "Eligibility Policy", "The minimum CGPA requirement is 7.5 for placement applicants.", "2024-01-01T00:00:00Z")
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    assert client.post(f"/api/v1/documents/{first_id}/approve", headers=headers).status_code == 200

    second = upload_policy(client, headers, "Eligibility Policy", "The minimum CGPA requirement is 8.0 for placement applicants.", "2025-01-01T00:00:00Z")
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    assert second.json()["version"] == 2
    assert client.post(f"/api/v1/documents/{second_id}/approve", headers=headers).status_code == 200

    current = retrieve(db_session, "minimum CGPA requirement")
    assert {item["document_id"] for item in current} == {second_id}
    historical = retrieve(db_session, "minimum CGPA requirement", as_of=datetime(2024, 6, 1, tzinfo=timezone.utc))
    assert {item["document_id"] for item in historical} == {first_id}


def test_document_rejection_only_changes_pending_review(client, db_session, monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "upload_directory", str(tmp_path / "uploads"))
    headers = admin_headers(client, db_session)
    pending = upload_policy(client, headers, "Rejectable Policy", "A pending placement policy for testing.", "2026-01-01T00:00:00Z")
    assert pending.status_code == 201
    pending_id = pending.json()["id"]
    rejected = client.post(f"/api/v1/documents/{pending_id}/reject", headers=headers)
    assert rejected.status_code == 200
    assert rejected.json()["approval_status"] == "rejected"
    repeated_rejection = client.post(f"/api/v1/documents/{pending_id}/reject", headers=headers)
    assert repeated_rejection.status_code == 409

    approved = upload_policy(client, headers, "Approved Policy", "An approved placement policy for testing.", "2026-01-01T00:00:00Z")
    assert approved.status_code == 201
    approved_id = approved.json()["id"]
    assert client.post(f"/api/v1/documents/{approved_id}/approve", headers=headers).status_code == 200
    reject_approved = client.post(f"/api/v1/documents/{approved_id}/reject", headers=headers)
    assert reject_approved.status_code == 409
    row = db_session.get(Document, approved_id)
    assert row.approval_status == "approved"


def test_document_upload_rejects_invalid_extension(client, db_session, monkeypatch, tmp_path):
    from app.core.config import settings
    monkeypatch.setattr(settings, "upload_directory", str(tmp_path / "uploads"))
    headers = admin_headers(client, db_session)
    response = client.post("/api/v1/documents/upload", headers=headers,
                           data={"title": "Invalid", "category": "general"},
                           files={"file": ("payload.exe", b"MZ", "application/octet-stream")})
    assert response.status_code == 400


def test_document_upload_logs_sanitized_vector_failure_and_keeps_lexical_chunks(client, db_session, monkeypatch, tmp_path, caplog):
    from app.api import documents as documents_api
    from app.core.config import settings

    monkeypatch.setattr(settings, "upload_directory", str(tmp_path / "uploads"))
    monkeypatch.setattr(
        documents_api,
        "index_chunks",
        lambda _chunks: (_ for _ in ()).throw(RuntimeError("private endpoint and api-key detail")),
    )
    headers = admin_headers(client, db_session)
    response = upload_policy(client, headers, "Indexing fallback policy", "Placement applicants require an updated academic profile.", "2026-01-01T00:00:00Z")

    assert response.status_code == 201, response.text
    assert response.json()["chunks_created"] > 0
    assert response.json()["vectors_indexed"] == 0
    assert "stage=upload exception_type=RuntimeError" in caplog.text
    assert "private endpoint" not in caplog.text
    assert "api-key" not in caplog.text


def test_document_vector_metadata_preserves_expiry_on_upload_and_approval(client, db_session, monkeypatch, tmp_path):
    from app.api import documents as documents_api
    from app.core.config import settings

    monkeypatch.setattr(settings, "upload_directory", str(tmp_path / "uploads"))
    indexed_batches = []
    monkeypatch.setattr(documents_api, "index_chunks", lambda chunks: (indexed_batches.append(chunks) or len(chunks)))
    headers = admin_headers(client, db_session)
    expiry = "2027-06-30T00:00:00Z"
    uploaded = client.post("/api/v1/documents/upload", headers=headers,
                           data={"title": "Expiring policy", "category": "placement-policy", "expiry_date": expiry},
                           files={"file": ("policy.txt", b"Approved placement eligibility rules apply.", "text/plain")})
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["chunk_ids"]
    assert indexed_batches[0][0]["chunk_id"] == uploaded.json()["chunk_ids"][0]
    assert indexed_batches[0][0]["chunk_id"] is not None
    assert indexed_batches[0][0]["expiry_date"].isoformat().startswith("2027-06-30")

    approved = client.post(f"/api/v1/documents/{uploaded.json()['id']}/approve", headers=headers)
    assert approved.status_code == 200
    assert indexed_batches[1][0]["expiry_date"].isoformat().startswith("2027-06-30")


def test_document_upload_rejects_infected_content_before_persisting(client, db_session, monkeypatch, tmp_path):
    from app.api import documents as documents_api
    from app.core.config import settings

    upload_directory = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_directory", str(upload_directory))
    monkeypatch.setattr(documents_api, "scan_upload", lambda _content: (_ for _ in ()).throw(MalwareDetected()))
    headers = admin_headers(client, db_session)
    response = client.post("/api/v1/documents/upload", headers=headers,
                           data={"title": "Infected test", "category": "general"},
                           files={"file": ("policy.txt", b"malicious test payload", "text/plain")})
    assert response.status_code == 400
    assert "malware scan" in response.json()["detail"]
    assert not upload_directory.exists()


def test_document_upload_fails_closed_when_required_scanner_is_unavailable(client, db_session, monkeypatch, tmp_path):
    from app.api import documents as documents_api
    from app.core.config import settings

    upload_directory = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_directory", str(upload_directory))
    monkeypatch.setattr(documents_api, "scan_upload", lambda _content: (_ for _ in ()).throw(ScannerUnavailable()))
    headers = admin_headers(client, db_session)
    response = client.post("/api/v1/documents/upload", headers=headers,
                           data={"title": "Unscanned test", "category": "general"},
                           files={"file": ("policy.txt", b"unscanned test payload", "text/plain")})
    assert response.status_code == 503
    assert not upload_directory.exists()


def test_document_parser_errors_do_not_echo_private_content_or_paths(client, db_session, monkeypatch, tmp_path, caplog):
    from app.api import documents as documents_api
    from app.core.config import settings

    upload_directory = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_directory", str(upload_directory))
    private_marker = "PRIVATE_POLICY_FRAGMENT"

    def fail_extraction(_path, **_kwargs):
        raise RuntimeError(f"parser failed near {private_marker} at C:/Users/staff/policy.pdf")

    monkeypatch.setattr(documents_api, "extract_pages", fail_extraction)
    response = client.post("/api/v1/documents/upload", headers=admin_headers(client, db_session),
                           data={"title": "Parser failure test", "category": "general"},
                           files={"file": ("policy.txt", b"A short policy sentence.", "text/plain")})
    assert response.status_code == 422
    assert private_marker not in response.text
    assert "C:/Users/staff" not in response.text
    assert private_marker not in caplog.text
    assert "Document extraction failed; exception_type=RuntimeError" in caplog.text
    assert list(upload_directory.iterdir()) == []


def test_document_metadata_suggestions_are_staff_visible_without_overriding_category(client, db_session, monkeypatch, tmp_path):
    from app.core.config import settings
    monkeypatch.setattr(settings, "upload_directory", str(tmp_path / "uploads"))
    headers = admin_headers(client, db_session)
    response = client.post("/api/v1/documents/upload", headers=headers,
                           data={"title": "Eligibility criteria", "category": "general"},
                           files={"file": ("criteria.txt", b"COMPANY ELIGIBILITY RULES\nEligibility criteria include minimum CGPA and backlog limits. Effective from: 2026-07-01.", "text/plain")})
    assert response.status_code == 201, response.text
    listed = client.get("/api/v1/documents/", headers=headers)
    assert listed.status_code == 200
    document = next(item for item in listed.json() if item["id"] == response.json()["id"])
    assert document["category"] == "general"
    assert document["suggested_category"] == "company-eligibility"
    assert document["metadata_candidates"]["date_candidates"]["effective"] == ["2026-07-01"]


def test_document_versions_are_scoped_by_company_and_academic_year(client, db_session, monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "upload_directory", str(tmp_path / "uploads"))
    company_a = Company(name="Scope A")
    company_b = Company(name="Scope B")
    db_session.add_all([company_a, company_b])
    db_session.commit()
    headers = admin_headers(client, db_session)

    first = client.post("/api/v1/documents/upload", headers=headers,
                        data={"title": "Same title", "category": "general", "company_id": str(company_a.id), "academic_year": "2025-26"},
                        files={"file": ("scope.txt", b"Company A placement policy.", "text/plain")})
    other_scope = client.post("/api/v1/documents/upload", headers=headers,
                              data={"title": "Same title", "category": "general", "company_id": str(company_b.id), "academic_year": "2025-26"},
                              files={"file": ("scope.txt", b"Company B placement policy.", "text/plain")})
    assert first.status_code == other_scope.status_code == 201
    assert first.json()["version"] == other_scope.json()["version"] == 1
    assert client.post(f"/api/v1/documents/{first.json()['id']}/approve", headers=headers).status_code == 200
    assert client.post(f"/api/v1/documents/{other_scope.json()['id']}/approve", headers=headers).status_code == 200
    db_session.expire_all()
    assert db_session.get(Document, first.json()["id"]).approval_status == "approved"

    cross_scope = client.post("/api/v1/documents/upload", headers=headers,
                              data={"title": "Same title", "category": "general", "company_id": str(company_b.id),
                                    "academic_year": "2025-26", "supersedes_id": str(first.json()["id"])},
                              files={"file": ("scope.txt", b"Invalid cross-scope superseding upload.", "text/plain")})
    assert cross_scope.status_code == 422


def test_document_version_chain_blocks_pending_and_only_supersedes_current(client, db_session, monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "upload_directory", str(tmp_path / "uploads"))
    headers = admin_headers(client, db_session)
    first = upload_policy(client, headers, "Version chain", "The current rule is 7.0 CGPA.", "2025-01-01T00:00:00Z")
    assert first.status_code == 201
    blocked = upload_policy(client, headers, "Version chain", "A second pending document.", "2025-02-01T00:00:00Z")
    assert blocked.status_code == 409
    assert client.post(f"/api/v1/documents/{first.json()['id']}/approve", headers=headers).status_code == 200

    second = upload_policy(client, headers, "Version chain", "The current rule is 8.0 CGPA.", "2026-01-01T00:00:00Z")
    assert second.status_code == 201, second.text
    assert second.json()["version"] == 2
    listed = client.get("/api/v1/documents/", headers=headers).json()
    second_row = next(row for row in listed if row["id"] == second.json()["id"])
    assert second_row["supersedes_id"] == first.json()["id"]
    assert client.post(f"/api/v1/documents/{second.json()['id']}/approve", headers=headers).status_code == 200

    stale_branch = client.post("/api/v1/documents/upload", headers=headers,
                               data={"title": "Version chain", "category": "placement-policy", "supersedes_id": str(first.json()["id"])},
                               files={"file": ("policy.txt", b"Attempt to branch from an old version.", "text/plain")})
    assert stale_branch.status_code == 409
