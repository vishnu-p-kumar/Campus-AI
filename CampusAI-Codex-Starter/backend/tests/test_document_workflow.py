from datetime import datetime, timezone

from app.ai.retrieval import retrieve
from app.models import Company, Document, User
from app.security import hash_password


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


def administrator_headers(client, db_session):
    admin = User(email="admin-domain@example.edu", full_name="CampusAI Administrator",
                 password_hash=hash_password("correct horse battery"), role="administrator")
    db_session.add(admin)
    db_session.commit()
    response = client.post("/api/v1/auth/login", json={"email": admin.email, "password": "correct horse battery"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_admin_manages_authorized_urls_and_url_context_switch(client, db_session, monkeypatch):
    from app.ai import gemini
    from app.core.config import settings

    admin = administrator_headers(client, db_session)
    officer = admin_headers(client, db_session)
    monkeypatch.setattr(settings, "gemini_url_context_enabled", True)
    monkeypatch.setattr(settings, "gemini_placement_api_key", "test-placement-key")

    assert client.get("/api/v1/documents/authorized-sources", headers=officer).status_code == 403
    initial = client.get("/api/v1/documents/authorized-sources", headers=admin)
    assert initial.status_code == 200 and initial.json()["enabled"] is False
    assert client.put("/api/v1/documents/authorized-sources/settings", headers=admin,
                      json={"enabled": True}).status_code == 409

    invalid = client.post("/api/v1/documents/authorized-sources", headers=admin,
                          json={"url": "http://placements.example.edu/policy"})
    assert invalid.status_code == 422
    private_ip = client.post("/api/v1/documents/authorized-sources", headers=admin,
                             json={"url": "https://127.0.0.1/policy"})
    assert private_ip.status_code == 422

    added = client.post("/api/v1/documents/authorized-sources", headers=admin,
                        json={"url": "https://www.placements.example.edu/placement/policy"})
    assert added.status_code == 201
    assert added.json()["domain"] == "placements.example.edu"
    assert added.json()["url"] == "https://www.placements.example.edu/placement/policy"
    assert client.post("/api/v1/documents/authorized-sources", headers=admin,
                       json={"url": "https://www.placements.example.edu/placement/policy"}).status_code == 409
    second_page = client.post("/api/v1/documents/authorized-sources", headers=admin,
                              json={"url": "https://placements.example.edu/another"})
    assert second_page.status_code == 201

    enabled = client.put("/api/v1/documents/authorized-sources/settings", headers=admin,
                         json={"enabled": True})
    assert enabled.status_code == 200 and enabled.json()["active"] is True
    assert [row["url"] for row in gemini.authorized_source_urls(db_session)] == [
        "https://placements.example.edu/another", "https://www.placements.example.edu/placement/policy"]
    assert gemini.placement_url_context_is_enabled(db_session)

    removed = client.delete(f"/api/v1/documents/authorized-sources/{added.json()['id']}", headers=admin)
    assert removed.status_code == 204
    still_active = client.get("/api/v1/documents/authorized-sources", headers=admin)
    assert still_active.json()["active"] is True
    assert [row["url"] for row in gemini.authorized_source_urls(db_session)] == ["https://placements.example.edu/another"]
    assert client.delete(f"/api/v1/documents/authorized-sources/{second_page.json()['id']}", headers=admin).status_code == 204
    no_urls = client.get("/api/v1/documents/authorized-sources", headers=admin)
    assert no_urls.json()["enabled"] is True and no_urls.json()["active"] is False
    assert gemini.authorized_source_urls(db_session) == []


def test_admin_cannot_enable_web_search_when_server_kill_switch_is_off(client, db_session, monkeypatch):
    from app.core.config import settings

    admin = administrator_headers(client, db_session)
    monkeypatch.setattr(settings, "gemini_url_context_enabled", False)
    monkeypatch.setattr(settings, "gemini_placement_api_key", "test-placement-key")
    added = client.post("/api/v1/documents/authorized-sources", headers=admin,
                        json={"url": "https://placements.example.edu"})
    assert added.status_code == 201
    enabled = client.put("/api/v1/documents/authorized-sources/settings", headers=admin,
                         json={"enabled": True})
    assert enabled.status_code == 409
    assert client.get("/api/v1/documents/authorized-sources", headers=admin).json()["active"] is False


def test_admin_cannot_add_more_than_twenty_authorized_urls(client, db_session):
    admin = administrator_headers(client, db_session)
    for index in range(20):
        response = client.post("/api/v1/documents/authorized-sources", headers=admin,
                               json={"url": f"https://placements.example.edu/page-{index}"})
        assert response.status_code == 201
    too_many = client.post("/api/v1/documents/authorized-sources", headers=admin,
                           json={"url": "https://placements.example.edu/page-21"})
    assert too_many.status_code == 409


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


def test_placement_assistant_examples_upload_approval_chunk_retrieval_gemini_and_web_fallback(
    client, db_session, monkeypatch, tmp_path,
):
    from app.api import chat as chat_api
    from app.api import documents as documents_api
    from app.core.config import settings
    from app.ai import retrieval

    monkeypatch.setattr(settings, "upload_directory", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "faithfulness_model", None)
    monkeypatch.setattr(chat_api, "assess_cited_claims", lambda claims, _sources: claims)
    monkeypatch.setattr(documents_api, "index_chunks", lambda chunks: len(chunks))
    monkeypatch.setattr(retrieval, "retrieve_dense", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(retrieval, "rerank", lambda _query, rows: rows)
    admin = admin_headers(client, db_session)
    document_text = (
        "Minimum CGPA for placement applicants is 7.5.\n\n"
        "Applications close on 30 June 2026."
    )
    upload = client.post("/api/v1/documents/upload", headers=admin,
                         data={"title": "Placement Handbook 2026", "category": "placement-policy"},
                         files={"file": ("BNMIT_Placement_Handbook_2026.txt", document_text.encode(), "text/plain")})
    assert upload.status_code == 201, upload.text
    assert upload.json()["chunks_created"] == 2
    document_id = upload.json()["id"]
    assert client.post(f"/api/v1/documents/{document_id}/approve", headers=admin).status_code == 200

    student_login = client.post("/api/v1/auth/register", json={
        "email": "placement-assistant-examples@example.edu", "full_name": "Placement Assistant Examples",
        "password": "correct horse battery",
    })
    student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}
    seen = []
    def fake_gemini(question, sources, *_args):
        seen.append((question, sources))
        if "CGPA" in question:
            citation = next(index for index, source in enumerate(sources, 1) if "CGPA" in source["text"])
            return f"The minimum CGPA is 7.5 [{citation}]."
        citation = next(index for index, source in enumerate(sources, 1) if "close" in source["text"])
        return f"Applications close on 30 June 2026 [{citation}]."

    monkeypatch.setattr(chat_api, "generate_grounded_answer", fake_gemini)
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: (
        "The official government page lists a scholarship deadline of 15 July [1].",
        [{"citation": 1, "source_type": "web", "title": "Official government scholarship page",
          "url": "https://scholarships.gov.example/deadlines"}],
    ))

    cgpa = client.post("/api/v1/chat/", headers=student_headers,
                       json={"question": "What is the minimum CGPA for placement?"})
    deadline = client.post("/api/v1/chat/", headers=student_headers,
                           json={"question": "When do placement applications close?"})
    website = client.post("/api/v1/chat/", headers=student_headers,
                          json={"question": "What is the government scholarship deadline?"})

    assert cgpa.status_code == deadline.status_code == website.status_code == 200
    assert cgpa.json()["answer"].startswith("The minimum CGPA is 7.5 [")
    assert cgpa.json()["citations"][0]["filename"] == "BNMIT_Placement_Handbook_2026.txt"
    assert cgpa.json()["citations"][0]["document_id"] == document_id
    assert deadline.json()["answer"].startswith("Applications close on 30 June 2026 [")
    assert website.json()["citations"][0]["source_type"] == "web"
    assert len(seen) == 2
    assert any(source["text"] == "Minimum CGPA for placement applicants is 7.5." for source in seen[0][1])
    assert any(source["text"] == "Applications close on 30 June 2026." for source in seen[1][1])


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

def test_document_upload_succeeds_without_external_scanning(client, db_session, monkeypatch, tmp_path):
    from app.api import documents as documents_api
    from app.core.config import settings

    upload_directory = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_directory", str(upload_directory))
    monkeypatch.setattr(documents_api, "index_chunks", lambda chunks: len(chunks))
    headers = admin_headers(client, db_session)

    response = upload_policy(
        client, headers, "Unscanned placement policy",
        "Applicants need a minimum CGPA of 7.5.", "2026-01-01T00:00:00Z",
    )
    assert response.status_code == 201, response.text
    assert response.json()["chunks_created"] > 0
    assert upload_directory.exists()
