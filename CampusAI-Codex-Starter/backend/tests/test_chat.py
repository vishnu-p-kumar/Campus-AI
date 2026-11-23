from app.api import chat as chat_api
from app.core.config import settings


def test_large_placement_context_is_bounded_and_prefers_relevant_chunks():
    relevant_text = "Synthetic 2026 placement report: average placement rate was 68%. " + ("eligible student outcome. " * 270)
    sources = [
        {"chunk_id": 1, "document_id": 10, "source_type": "document", "title": "Placement Report",
         "text": "unrelated hostel and cafeteria information. " * 400, "lexical_score": 0.1,
         "page_number": 1},
        {"chunk_id": 2, "document_id": 10, "source_type": "document", "title": "Placement Report",
         "text": relevant_text, "lexical_score": 0.9, "page_number": 2},
        {"chunk_id": 3, "document_id": 11, "source_type": "document", "title": "Duplicate Placement Report",
         "text": relevant_text, "lexical_score": 0.9, "page_number": 2},
    ]

    bounded = chat_api._bound_chat_evidence(sources, "What is the average placement rate in 2026?")

    assert sum(len(source["text"]) for source in bounded) <= chat_api.CHAT_EVIDENCE_CHAR_BUDGET
    assert len(bounded) == 1
    assert "68%" in bounded[0]["text"]
    assert all(not any(key.startswith("_") for key in source) for source in bounded)


def test_small_placement_document_is_preserved_in_full():
    source = {"chunk_id": 1, "document_id": 10, "source_type": "document", "title": "Company JD",
              "text": "Complete short job description with eligibility and compensation.", "_retrieval_selected": True}
    assert chat_api._bound_chat_evidence([source], "What is the compensation?") == [{
        "chunk_id": 1, "document_id": 10, "source_type": "document", "title": "Company JD",
        "text": "Complete short job description with eligibility and compensation.",
    }]


def test_ordinary_placement_question_bounds_expanded_document_before_gemini(client, monkeypatch):
    token = auth(client, "bounded-context@example.edu")
    source = {
        "chunk_id": 122, "document_id": 122, "title": "Placement Report 2026",
        "filename": "placement-report-2026.pdf", "version": 1, "category": "placement",
        "approval_status": "approved", "effective_date": None, "expiry_date": None,
        "page_number": 4, "text": "The average placement rate in 2026 was 68%.",
        "lexical_score": 0.9, "source_type": "document",
    }
    expanded_sources = [
        {**source, "chunk_id": index, "text": ("The average placement rate in 2026 was 68%. " if index == 0 else f"Unrelated source detail {index}. ") + ("additional document text. " * 30),
         "page_number": index + 1, "lexical_score": 0.0}
        for index in range(1415)
    ]
    observed = {}
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [source])
    monkeypatch.setattr(chat_api, "_expand_retrieved_documents",
                        lambda *args, **kwargs: expanded_sources)

    def answer(_question, sources, *_args):
        observed["sources"] = sources
        return "The average placement rate was 68% [1]."

    monkeypatch.setattr(chat_api, "generate_grounded_answer", answer)
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: None)

    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "What was the average placement rate in 2026?"})

    assert response.status_code == 200
    assert sum(len(item["text"]) for item in observed["sources"]) <= chat_api.CHAT_EVIDENCE_CHAR_BUDGET
    assert any("68%" in item["text"] for item in observed["sources"])


def test_no_relevant_approved_document_uses_authorized_urls_without_document_generation(client, monkeypatch):
    token = auth(client, "no-relevant-document@example.edu")
    unrelated = {
        "chunk_id": 123, "document_id": 123, "title": "Campus Cafeteria Menu",
        "filename": "cafeteria.pdf", "version": 1, "category": "placement",
        "approval_status": "approved", "effective_date": None, "expiry_date": None,
        "page_number": 1, "text": "The cafeteria serves lunch from noon until two.",
        "lexical_score": 0.0, "source_type": "document",
    }
    document_generation_calls = []
    url_calls = []
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [unrelated])
    monkeypatch.setattr(chat_api, "_expand_retrieved_documents", lambda *_args, **_kwargs: [unrelated])
    monkeypatch.setattr(chat_api, "generate_grounded_answer",
                        lambda *_args, **_kwargs: document_generation_calls.append(True))
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: (
        url_calls.append(True) or (
            "The approved placement report lists 68% [1].",
            [{"citation": 1, "source_type": "web", "title": "Approved placement report",
              "url": "https://placements.example.edu/report"}],
        )
    ))

    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "What was the average placement rate in 2026?"})

    assert response.status_code == 200
    assert document_generation_calls == []
    assert url_calls == [True]
    assert response.json()["citations"][0]["source_type"] == "web"


def auth(client, email):
    return client.post("/api/v1/auth/register", json={"email": email, "full_name": "Student User", "password": "correct horse battery"}).json()["access_token"]


def test_chat_abstains_without_evidence_and_scopes_history(client):
    token = auth(client, "chat1@example.edu")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post("/api/v1/chat/", headers=headers, json={"question": "What is the cafeteria menu for next Tuesday?"})
    assert response.status_code == 200
    assert response.json()["abstained"] is True
    assert response.json()["citations"] == []

    conversation_id = response.json()["conversation_id"]
    other = auth(client, "chat2@example.edu")
    denied = client.get(f"/api/v1/chat/conversations/{conversation_id}", headers={"Authorization": f"Bearer {other}"})
    assert denied.status_code == 404


def test_exhaustive_company_role_questions_request_wider_retrieval(client, monkeypatch):
    token = auth(client, "list-retrieval@example.edu")
    headers = {"Authorization": f"Bearer {token}"}
    observed_limits = []
    source = {
        "chunk_id": 991, "document_id": 991, "title": "EY GDS Consulting Engineer", "filename": "ey-gds.pdf",
        "version": 1, "category": "placement", "approval_status": "approved", "effective_date": None,
        "expiry_date": None, "page_number": 1,
        "text": "EY GDS Consulting Engineer roles listed for placement companies in 2025 and 2026.", "lexical_score": 1.0,
    }

    def retrieve(*_args, **kwargs):
        observed_limits.append(kwargs["limit"])
        return [source]

    monkeypatch.setattr(chat_api, "hybrid_retrieve", retrieve)
    monkeypatch.setattr(chat_api, "generate_grounded_answer", lambda *_args: "The source lists these roles [1].")
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: None)

    for question in (
        "What all roles are listed from EY GDS Consulting Engineer?",
        "List the companies which came for placement in 2025 and 2026.",
    ):
        response = client.post("/api/v1/chat/", headers=headers, json={"question": question})
        assert response.status_code == 200
    assert observed_limits == [24, 24]


def test_company_list_without_year_matched_company_evidence_abstains(client, monkeypatch):
    token = auth(client, "missing-company-years@example.edu")
    headers = {"Authorization": f"Bearer {token}"}
    source = {
        "chunk_id": 992, "document_id": 992, "title": "Placement Guidelines", "filename": "placement-guidelines.pdf",
        "version": 1, "category": "placement", "approval_status": "approved", "effective_date": None,
        "expiry_date": None, "page_number": 1,
        "text": "Companies visiting for recruitment follow the placement office process.", "lexical_score": 1.0,
    }
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [source])
    monkeypatch.setattr(chat_api, "generate_grounded_answer",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unrelated evidence must not be used")))
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: None)

    response = client.post("/api/v1/chat/", headers=headers,
                           json={"question": "List companies which came for placement in 2025 and 2026."})
    assert response.status_code == 200
    assert response.json()["abstained"] is True
    assert response.json()["citations"] == []


def test_company_list_year_evidence_must_be_linked_to_company_placement_context():
    unrelated_split_sources = [
        {"document_id": 1, "title": "Student Resume", "text": "Engineering graduation 2025 and 2026."},
        {"document_id": 2, "title": "Placement Policy", "text": "Companies visit for recruitment."},
    ]
    split_placement_sources = [
        {"document_id": 3, "title": "Placement Companies 2025", "text": "Companies visited in placement 2025."},
        {"document_id": 4, "title": "Placement Companies 2026", "text": "Companies visited in placement 2026."},
    ]
    question = "List companies which came for placement in 2025 and 2026."
    assert chat_api.list_evidence_covers_requested_years(question, unrelated_split_sources) is False
    assert chat_api.list_evidence_covers_requested_years(question, split_placement_sources) is True


def test_comparison_uses_wider_retrieval_and_cites_both_files(client, monkeypatch):
    token = auth(client, "compare-files@example.edu")
    headers = {"Authorization": f"Bearer {token}"}
    observed_limits = []
    sources = [
        {"chunk_id": 993, "document_id": 993, "title": "Acme Placement Policy", "filename": "acme.pdf",
         "version": 1, "category": "placement", "approval_status": "approved", "effective_date": None,
         "expiry_date": None, "page_number": 1, "text": "Acme placement policy requires a minimum CGPA of 7.0.", "lexical_score": 1.0},
        {"chunk_id": 994, "document_id": 994, "title": "Contoso Placement Policy", "filename": "contoso.pdf",
         "version": 1, "category": "placement", "approval_status": "approved", "effective_date": None,
         "expiry_date": None, "page_number": 1, "text": "Contoso placement policy requires a minimum CGPA of 7.5.", "lexical_score": 1.0},
    ]

    def retrieve(*_args, **kwargs):
        observed_limits.append(kwargs["limit"])
        return sources

    monkeypatch.setattr(chat_api, "hybrid_retrieve", retrieve)
    monkeypatch.setattr(chat_api, "generate_grounded_answer", lambda *_args: (
        "Acme requires 7.0 [1], while Contoso requires 7.5 [2]."
    ))
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: None)

    response = client.post("/api/v1/chat/", headers=headers, json={
        "question": "Compare the differences between Acme and Contoso placement policies."
    })
    assert response.status_code == 200
    assert response.json()["abstained"] is False
    assert {citation["document_id"] for citation in response.json()["citations"]} == {993, 994}
    assert observed_limits == [24]


def test_comparison_with_only_one_retrieved_file_abstains(client, monkeypatch):
    token = auth(client, "compare-one-file@example.edu")
    headers = {"Authorization": f"Bearer {token}"}
    source = {
        "chunk_id": 995, "document_id": 995, "title": "Acme Placement Policy", "filename": "acme.pdf",
        "version": 1, "category": "placement", "approval_status": "approved", "effective_date": None,
        "expiry_date": None, "page_number": 1, "text": "Acme placement policy requirements.", "lexical_score": 1.0,
    }
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [source])
    monkeypatch.setattr(chat_api, "generate_grounded_answer",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("both files are required")))
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: None)

    response = client.post("/api/v1/chat/", headers=headers, json={
        "question": "Compare the differences between Acme and Contoso placement policies."
    })
    assert response.status_code == 200
    assert response.json()["abstained"] is True
    assert response.json()["citations"] == []


def test_student_application_questions_use_only_the_signed_in_students_records(client, db_session, monkeypatch):
    from app.models import Application, Company, PlacementDrive, User

    own_token = auth(client, "own-applications@example.edu")
    other_token = auth(client, "other-applications@example.edu")
    own_user = db_session.query(User).filter_by(email="own-applications@example.edu").one()
    other_user = db_session.query(User).filter_by(email="other-applications@example.edu").one()
    acme = Company(name="Acme Systems")
    contoso = Company(name="Contoso Labs")
    db_session.add_all([acme, contoso])
    db_session.flush()
    acme_drive = PlacementDrive(company_id=acme.id, title="Graduate role", role="Software Engineer")
    contoso_drive = PlacementDrive(company_id=contoso.id, title="Analyst role", role="Data Analyst")
    db_session.add_all([acme_drive, contoso_drive])
    db_session.flush()
    db_session.add_all([
        Application(student_user_id=own_user.id, drive_id=acme_drive.id, status="interview"),
        Application(student_user_id=other_user.id, drive_id=contoso_drive.id, status="selected"),
    ])
    db_session.commit()
    monkeypatch.setattr(chat_api, "generate_grounded_answer",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("personal applications must use structured records")))

    own_headers = {"Authorization": f"Bearer {own_token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}
    own_list = client.post("/api/v1/chat/", headers=own_headers,
                           json={"question": "Which companies did I apply to?"}).json()
    own_status = client.post("/api/v1/chat/", headers=own_headers,
                             json={"question": "What is my application status at Acme Systems?"}).json()
    other_list = client.post("/api/v1/chat/", headers=other_headers,
                             json={"question": "List companies I have applied to."}).json()

    assert own_list["answer"] == "Companies you have applied to: Acme Systems [1]."
    assert own_status["answer"] == "Your application status: Acme Systems (Software Engineer): interview [1]."
    assert other_list["answer"] == "Companies you have applied to: Contoso Labs [1]."
    assert "Acme Systems" not in other_list["answer"]
    assert own_list["citations"][0]["source_type"] == "application_record"


def test_company_drive_status_answers_only_the_requested_status(client, db_session, monkeypatch):
    from app.models import Company, PlacementDrive

    token = auth(client, "company-drive-status@example.edu")
    company = Company(name="Status Systems")
    db_session.add(company)
    db_session.flush()
    db_session.add(PlacementDrive(company_id=company.id, title="Graduate intake", role="Engineer", status="closed"))
    db_session.commit()
    monkeypatch.setattr(chat_api, "generate_grounded_answer",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("structured drive status is authoritative")))

    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "What is the status of Status Systems?"})
    assert response.status_code == 200
    assert response.json()["answer"] == "Status Systems placement drive status: Graduate intake (Engineer): closed [1]."
    assert response.json()["citations"][0]["source_type"] == "drive_record"


def test_specific_company_answer_includes_only_its_admin_details(client, db_session, monkeypatch):
    from app.models import Company, CompanyRequirement, Document, DocumentChunk, User

    token = auth(client, "specific-company-details@example.edu")
    admin = User(email="company-doc-admin@example.edu", full_name="Admin", password_hash="x", role="administrator")
    db_session.add(admin)
    db_session.flush()
    company = Company(name="Acme Systems", industry="Technology", description="Builds enterprise software.",
                      website="https://acme.example", job_roles=["Software Engineer"])
    db_session.add(company)
    db_session.flush()
    company.requirements = CompanyRequirement()
    document = Document(title="Acme role details", category="company-details", filename="acme-details.pdf",
                        storage_path="unused", version=1, approval_status="approved", uploaded_by=admin.id,
                        company_id=company.id)
    db_session.add(document)
    db_session.flush()
    db_session.add(DocumentChunk(document_id=document.id, chunk_index=0, page_number=1,
                                 text="Acme Systems is hiring Software Engineers for its product team."))
    db_session.add(DocumentChunk(document_id=document.id, chunk_index=1, page_number=2,
                                 section="Compensation", text="The annual salary package is 12 LPA."))
    db_session.commit()
    observed = {}
    monkeypatch.setattr(chat_api, "hybrid_retrieve",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("company context must use its complete approved records")))
    monkeypatch.setattr(chat_api, "generate_grounded_answer", lambda _question, sources, *_args: (
        observed.update(sources=sources) or "Acme Systems offers Software Engineer roles [2]. The package is 12 LPA [3]."
    ))
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: None)

    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "What role and salary/package does Acme Systems offer?"})
    assert response.status_code == 200
    passed_sources = observed["sources"]
    assert {source["text"] for source in passed_sources if source.get("document_id") == document.id} == {
        "Acme Systems is hiring Software Engineers for its product team.",
        "The annual salary package is 12 LPA.",
    }
    assert response.json()["answer"] == "Acme Systems offers Software Engineer roles [2]. The package is 12 LPA [3]."
    assert any(source.get("source_type") == "company_record" for source in passed_sources)
    assert response.json()["citations"][0]["document_id"] == document.id


def test_combined_own_applications_and_company_details_are_sent_to_gemini(client, db_session, monkeypatch):
    from app.models import Application, Company, Document, DocumentChunk, PlacementDrive, User

    token = auth(client, "company-detail-applications@example.edu")
    student = db_session.query(User).filter_by(email="company-detail-applications@example.edu").one()
    admin = User(email="company-detail-admin@example.edu", full_name="Admin", password_hash="x", role="administrator")
    db_session.add(admin)
    db_session.flush()
    company = Company(name="Acme Systems", job_roles=["Software Engineer"])
    db_session.add(company)
    db_session.flush()
    drive = PlacementDrive(company_id=company.id, title="Graduate intake", role="Software Engineer")
    db_session.add(drive)
    db_session.flush()
    db_session.add(Application(student_user_id=student.id, drive_id=drive.id, status="interview"))
    document = Document(title="Acme job description", category="company-details", filename="acme-jd.pdf",
                        storage_path="unused", version=1, approval_status="approved", uploaded_by=admin.id,
                        company_id=company.id)
    db_session.add(document)
    db_session.flush()
    db_session.add(DocumentChunk(document_id=document.id, chunk_index=0, page_number=1,
                                 text="Software Engineer. Annual package: 12 LPA."))
    db_session.commit()

    seen = {}
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat_api, "generate_grounded_answer", lambda _question, sources, *_args: (
        seen.update(sources=sources) or "You applied to Acme Systems for Software Engineer [1]. The package is 12 LPA [3]."
    ))
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: None)

    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"}, json={
        "question": "List the companies I have applied to, their offered roles, salaries/packages, and details."
    })

    assert response.status_code == 200
    assert any(source.get("source_type") == "application_record" and "Acme Systems" in source["text"]
               for source in seen["sources"])
    assert any(source.get("document_id") == document.id and "12 LPA" in source["text"]
               for source in seen["sources"])
    assert "12 LPA" in response.json()["answer"]


def test_question_about_term_in_document_sends_every_document_chunk_to_gemini(client, db_session, monkeypatch):
    from app.models import Document, DocumentChunk, User

    token = auth(client, "consulting-engineering-question@example.edu")
    admin = User(email="consulting-doc-admin@example.edu", full_name="Admin", password_hash="x", role="administrator")
    db_session.add(admin)
    db_session.flush()
    document = Document(title="EY GDS role specification", category="company-details", filename="ey-gds-role.pdf",
                        storage_path="unused", version=1, approval_status="approved", uploaded_by=admin.id)
    db_session.add(document)
    db_session.flush()
    chunks = [
        "EY Global Delivery Services provides technology consulting services.",
        "Consulting Engineering is the service line that designs and builds technology solutions for clients.",
        "Position Title: Consulting - Technology Analyst. Responsibilities include software delivery and client collaboration.",
    ]
    for index, text in enumerate(chunks):
        db_session.add(DocumentChunk(document_id=document.id, chunk_index=index, page_number=index + 1, text=text))
    db_session.commit()

    selected = {"chunk_id": 1, "document_id": document.id, "company_id": None,
                "title": document.title, "filename": document.filename, "category": document.category,
                "version": 1, "approval_status": "approved", "effective_date": None, "expiry_date": None,
                "page_number": 1, "section": None, "text": chunks[0], "lexical_score": 1.0}
    observed = {}
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [selected])

    def answer(_question, sources, *_args):
        observed["sources"] = sources
        return "Consulting Engineering is a service line for designing and building client technology solutions [2]."

    monkeypatch.setattr(chat_api, "generate_grounded_answer", answer)
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: None)
    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "What is the Consulting Engineering?"})

    assert response.status_code == 200
    assert [source["text"] for source in observed["sources"]] == chunks
    assert "service line" in response.json()["answer"]
    assert response.json()["abstained"] is False


def test_company_package_and_compensation_questions_include_admin_drive_amount(client, db_session, monkeypatch):
    from app.models import Company, PlacementDrive

    token = auth(client, "eygds-package-questions@example.edu")
    company = Company(name="EYGDS", job_roles=["Consulting Engineering"])
    db_session.add(company)
    db_session.flush()
    db_session.add(PlacementDrive(company_id=company.id, title="Placement Consulting Engineering",
                                 role="Consulting Engineering", package_lpa=6.0, location="Bengaluru"))
    db_session.commit()

    seen = []
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [])

    def answer(question, sources, *_args):
        seen.append((question, sources))
        if "base salary" in question.casefold() or "salary" in question.casefold():
            return "EYGDS lists a 6 LPA package, but base salary is not separately stated [1]."
        return "EYGDS offers a placement package of 6 LPA [1]."

    monkeypatch.setattr(chat_api, "generate_grounded_answer", answer)
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: None)
    questions = [
        "What is the package offered by the EYGDS?",
        "What is the compensation offered by the EYGDS?",
        "What package does EY GDS offer?",
        "What base salary is offered by EYGDS?",
    ]

    for question in questions:
        response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                               json={"question": question})
        assert response.status_code == 200
        assert response.json()["abstained"] is False, f"{question}: {response.json()}"
        assert "6 LPA" in response.json()["answer"]
        assert response.json()["citations"][0]["source_type"] == "company_record"

    assert len(seen) == len(questions)
    for _, sources in seen:
        record = next(source for source in sources if source.get("source_type") == "company_record")
        assert '"package_lpa": 6.0' in record["text"]
        assert '"compensation_package_lpa": 6.0' in record["text"]
        assert '"location": "Bengaluru"' in record["text"]


def test_company_question_sends_admin_criteria_and_unassigned_linked_documents(client, db_session, monkeypatch):
    from app.models import Company, CompanyRequirement, Document, DocumentChunk, User

    token = auth(client, "eygds-criteria-question@example.edu")
    admin = User(email="eygds-criteria-admin@example.edu", full_name="Admin", password_hash="x", role="administrator")
    db_session.add(admin)
    db_session.flush()
    company = Company(name="EYGDS", job_roles=["Consulting Engineering"])
    db_session.add(company)
    db_session.flush()
    criteria_doc = Document(title="Consulting Engineering (EY GDS)", category="company-eligibility",
                            filename="eygds-eligibility.pdf", storage_path="unused", version=1,
                            approval_status="approved", uploaded_by=admin.id)
    named_doc = Document(title="EYGDS eligibility details", category="company-eligibility",
                         filename="eygds-details.pdf", storage_path="unused", version=1,
                         approval_status="approved", uploaded_by=admin.id)
    db_session.add_all([criteria_doc, named_doc])
    db_session.flush()
    company.requirements = CompanyRequirement(
        min_cgpa=6.0, eligible_branches=["CSE", "ECE"], max_active_backlogs=0,
        criteria_reviewed=True, source_document_id=criteria_doc.id,
    )
    db_session.add_all([
        DocumentChunk(document_id=criteria_doc.id, chunk_index=0, page_number=1,
                      text="Consulting Engineering (EY GDS) position specification."),
        DocumentChunk(document_id=criteria_doc.id, chunk_index=1, page_number=2,
                      text="The role includes client technology consulting and solution delivery."),
        DocumentChunk(document_id=named_doc.id, chunk_index=0, page_number=1,
                      text="EYGDS role applications require a completed student profile."),
    ])
    db_session.commit()

    seen = {}
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [])

    def answer(_question, sources, *_args):
        seen["sources"] = sources
        return "EYGDS minimum criteria are CGPA 6.0, CSE or ECE, and no active backlogs [1]."

    monkeypatch.setattr(chat_api, "generate_grounded_answer", answer)
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: None)
    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"}, json={
        "question": "What is the minimum criteria for the company EYGDS?"
    })

    assert response.status_code == 200
    assert response.json()["abstained"] is False
    assert "CGPA 6.0" in response.json()["answer"]
    criteria_chunks = [source for source in seen["sources"] if source.get("document_id") == criteria_doc.id]
    named_chunks = [source for source in seen["sources"] if source.get("document_id") == named_doc.id]
    assert [source["text"] for source in criteria_chunks] == [
        "Consulting Engineering (EY GDS) position specification.",
    ]
    assert [source["text"] for source in named_chunks] == [
        "EYGDS role applications require a completed student profile."
    ]
    assert any(source.get("source_type") == "company_record" and '"minimum_cgpa": 6.0' in source["text"]
               for source in seen["sources"])


def test_decimal_policy_answer_sentence_coverage_keeps_following_citation_attached():
    answer = "The minimum CGPA is 7.5 [1]. Applications close on 30 June [2]."
    assert chat_api.verify_citation_coverage(answer, {1, 2}) == 1.0


def test_uncited_colon_header_does_not_fail_coverage_for_cited_answer_items():
    answer = (
        "The minimum eligibility criteria for EYGDS are:\n"
        "* Minimum CGPA: 6.0 [1]\n"
        "* Eligible branches: CSE and ECE [1]\n"
        "* Maximum active backlogs: 0 [1]"
    )
    assert chat_api.verify_citation_coverage(answer, {1}) == 1.0


def test_chat_sends_retrieved_chunks_to_gemini_even_when_confidence_threshold_is_not_met(client, monkeypatch):
    token = auth(client, "configured-cutoff@example.edu")
    source = {
        "chunk_id": 940, "document_id": 240, "title": "Approved Placement Policy", "version": 1,
        "category": "placement-policy", "approval_status": "approved", "effective_date": None,
        "expiry_date": None, "page_number": 1,
        "text": "CGPA requirement is 7.5.", "lexical_score": 1.0,
    }
    seen = []
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [source])
    monkeypatch.setattr(chat_api, "generate_grounded_answer", lambda _question, sources, *_args: (
        seen.extend(sources) or "The CGPA requirement is 7.5 [1]."
    ))
    monkeypatch.setattr(settings, "evidence_minimum_score", 0.95)
    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "What is the CGPA requirement?"})
    assert response.status_code == 200
    assert response.json()["abstained"] is False
    assert response.json()["confidence_label"] == "weak"
    assert response.json()["evidence_minimum_score"] == 0.95
    assert seen[0]["text"] == source["text"]


def test_chat_uses_authorized_web_fallback_and_returns_sources(client, monkeypatch):
    token = auth(client, "authorized-web-fallback@example.edu")
    source = {"citation": 1, "source_type": "web", "title": "Official placement rules",
              "url": "https://placements.example.edu/rules"}
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer",
                        lambda *_args, **_kwargs: ("The policy requires an application.", [source]))
    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "How do I apply for placements?"})
    assert response.status_code == 200
    assert response.json()["abstained"] is False
    assert response.json()["citations"] == [source]
    history = client.get(f"/api/v1/chat/conversations/{response.json()['conversation_id']}",
                         headers={"Authorization": f"Bearer {token}"})
    assert history.json()[-1]["citations"] == [source]


def test_chat_sends_partial_evidence_to_gemini_and_abstains_if_answer_is_uncited(client, monkeypatch):
    token = auth(client, "partial-evidence@example.edu")
    source = {
        "chunk_id": 941, "document_id": 241, "title": "Placement Policy", "version": 1,
        "category": "placement-policy", "approval_status": "approved", "effective_date": None,
        "expiry_date": None, "page_number": 1, "text": "CGPA eligibility policy details are maintained here.",
        "lexical_score": 0.0,
    }
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [source])
    seen = []
    monkeypatch.setattr(chat_api, "generate_grounded_answer", lambda _question, sources, *_args: (
        seen.extend(sources) or "The retrieved source does not give a numerical cutoff."
    ))
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: None)
    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "What is minimum CGPA eligibility cutoff?"})
    assert response.status_code == 200
    assert response.json()["confidence_label"] == "partial"
    assert response.json()["abstained"] is True
    assert response.json()["citations"] == []
    assert seen[0]["text"] == source["text"]


def test_chat_conversation_deletion_removes_messages_and_is_user_scoped(client):
    owner = {"Authorization": f"Bearer {auth(client, 'delete-chat@example.edu')}"}
    other = {"Authorization": f"Bearer {auth(client, 'other-chat@example.edu')}"}
    response = client.post("/api/v1/chat/", headers=owner, json={"question": "What is the placement office contact?"})
    conversation_id = response.json()["conversation_id"]

    denied = client.delete(f"/api/v1/chat/conversations/{conversation_id}", headers=other)
    assert denied.status_code == 404
    assert client.get(f"/api/v1/chat/conversations/{conversation_id}", headers=owner).status_code == 200

    deleted = client.delete(f"/api/v1/chat/conversations/{conversation_id}", headers=owner)
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/chat/conversations/{conversation_id}", headers=owner).status_code == 404
    assert all(item["id"] != conversation_id for item in client.get("/api/v1/chat/conversations", headers=owner).json())


def test_chat_safe_abstention_uses_selected_hindi_or_kannada_language(client):
    cases = [
        ("hi", "localized-hindi@example.edu", "स्वीकृत प्लेसमेंट दस्तावेज़ों में पर्याप्त प्रमाण नहीं मिला"),
        ("kn", "localized-kannada@example.edu", "ಅನುಮೋದಿತ ಉದ್ಯೋಗ ನಿಯೋಜನೆ ದಾಖಲೆಗಳಲ್ಲಿ ಸಾಕಷ್ಟು ಸಾಕ್ಷ್ಯ ಸಿಗಲಿಲ್ಲ"),
    ]
    for language, email, expected in cases:
        token = auth(client, email)
        response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                              json={"question": "What is the placement office contact?", "language": language})
        assert response.status_code == 200
        assert response.json()["abstained"] is True
        assert expected in response.json()["answer"]


def test_chat_rewrites_short_followup_from_owned_conversation_context(client, monkeypatch):
    token = auth(client, "context@example.edu")
    headers = {"Authorization": f"Bearer {token}"}
    retrieval_queries = []
    generation_contexts = []
    source = {
        "chunk_id": 10, "document_id": 4, "title": "Placement policy", "version": 1,
        "category": "placement-policy", "approval_status": "approved", "effective_date": None,
        "expiry_date": None, "page_number": 2,
        "text": "Candidates need a minimum CGPA of 6.0 and may have up to one backlog for placement.",
        "lexical_score": 1.0,
    }

    def retrieve(_db, query, **_filters):
        retrieval_queries.append(query)
        return [source]

    def generate(question, _sources, _language, context):
        generation_contexts.append(context)
        return "The policy requires a minimum CGPA of 6.0 [1]. The policy allows up to one backlog [1]."

    monkeypatch.setattr(chat_api, "hybrid_retrieve", retrieve)
    monkeypatch.setattr(chat_api, "generate_grounded_answer", generate)
    first = client.post("/api/v1/chat/", headers=headers, json={"question": "What CGPA is required for placement?"})
    assert first.status_code == 200 and first.json()["abstained"] is False
    conversation_id = first.json()["conversation_id"]
    followup = client.post("/api/v1/chat/", headers=headers, json={
        "conversation_id": conversation_id, "question": "What about backlogs?",
    })
    assert followup.status_code == 200 and followup.json()["abstained"] is False
    assert followup.json()["confidence_label"] == "partial"
    assert "What CGPA is required for placement?" in retrieval_queries[1]
    assert "What about backlogs?" in retrieval_queries[1]
    assert followup.json()["answer"].endswith("[1].")
    assert len(generation_contexts) == 2


def test_chat_query_rewrite_does_not_merge_independent_questions():
    assert chat_api.rewrite_follow_up("How do I prepare for an interview?", ["What is the CGPA cutoff?"]) == "How do I prepare for an interview?"


def test_chat_returns_sanitized_unavailable_response_on_provider_failure(client, monkeypatch):
    token = auth(client, "provider-error@example.edu")
    source = {
        "chunk_id": 90, "document_id": 20, "title": "Approved Placement Policy", "version": 1,
        "category": "placement-policy", "approval_status": "approved", "effective_date": None,
        "expiry_date": None, "page_number": 1,
        "text": "The placement CGPA requirement is 7.5 for placement applicants.", "lexical_score": 1.0,
    }
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [source])
    monkeypatch.setattr(chat_api, "generate_grounded_answer", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider key=private-secret")))

    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"}, json={"question": "What is the placement CGPA requirement?"})
    assert response.status_code == 503
    assert "private-secret" not in response.text
    assert "try again later" in response.json()["detail"]


def test_chat_abstains_when_generated_numeric_requirement_is_not_in_cited_source(client, monkeypatch):
    token = auth(client, "unsupported-number@example.edu")
    source = {
        "chunk_id": 91, "document_id": 21, "title": "Approved Placement Policy", "version": 1,
        "category": "placement-policy", "approval_status": "approved", "effective_date": None,
        "expiry_date": None, "page_number": 1,
        "text": "The placement CGPA requirement is 7.5 for placement applicants.", "lexical_score": 1.0,
    }
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [source])
    monkeypatch.setattr(chat_api, "generate_grounded_answer", lambda *_args, **_kwargs: "The placement CGPA requirement is 9.0 [1].")
    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "What is the placement CGPA requirement?"})
    assert response.status_code == 200
    assert response.json()["abstained"] is True
    assert response.json()["citations"] == []
    assert response.json()["claim_support"][0]["unsupported_numeric_claims"] == ["9.0"]


def test_chat_abstains_when_optional_semantic_check_rejects_claim(client, monkeypatch):
    token = auth(client, "unsupported-semantic@example.edu")
    source = {
        "chunk_id": 191, "document_id": 31, "title": "Approved Placement Policy", "version": 1,
        "category": "placement-policy", "approval_status": "approved", "effective_date": None,
        "expiry_date": None, "page_number": 1,
        "text": "The placement office is in the main building.", "lexical_score": 1.0,
    }
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [source])
    monkeypatch.setattr(chat_api, "generate_grounded_answer",
                        lambda *_args, **_kwargs: "The office is located in the library [1].")
    monkeypatch.setattr(chat_api, "assess_cited_claims", lambda claims, _sources:
                        [{**claim, "semantic_support": False} for claim in claims])
    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "Where is the placement office?"})
    assert response.status_code == 200
    assert response.json()["abstained"] is True
    assert response.json()["citations"] == []


def test_chat_uses_authorized_url_answer_when_document_claim_is_unsupported(client, monkeypatch):
    token = auth(client, "authorized-url-fallback@example.edu")
    source = {
        "chunk_id": 193, "document_id": 33, "title": "Unrelated Placement Notes", "version": 1,
        "category": "placement-policy", "approval_status": "approved", "effective_date": None,
        "expiry_date": None, "page_number": 1,
        "text": "The placement office is in the main building.", "lexical_score": 1.0,
    }
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [source])
    monkeypatch.setattr(chat_api, "generate_grounded_answer",
                        lambda *_args, **_kwargs: "The placement percentage is 80% [1].")
    monkeypatch.setattr(chat_api, "assess_cited_claims", lambda claims, _sources:
                        [{**claim, "semantic_support": False} for claim in claims])
    monkeypatch.setattr(chat_api, "generate_authorized_url_answer", lambda *_args, **_kwargs: (
        "The official report gives a combined placement, higher education, and entrepreneurship rate of 59.08% [1].",
        [{"citation": 1, "source_type": "web", "title": "BNMIT placement report",
          "url": "https://www.bnmit.org/wp-content/uploads/2026/08/Placement-Report-2022-26-1.pdf"}],
    ))

    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "What is the placement percentage of the year 2026?"})

    assert response.status_code == 200
    assert response.json()["abstained"] is False
    assert "59.08%" in response.json()["answer"]
    assert response.json()["citations"][0]["source_type"] == "web"


def test_chat_abstains_when_configured_semantic_verifier_fails(client, monkeypatch):
    token = auth(client, "broken-semantic@example.edu")
    source = {
        "chunk_id": 192, "document_id": 32, "title": "Approved Placement Policy", "version": 1,
        "category": "placement-policy", "approval_status": "approved", "effective_date": None,
        "expiry_date": None, "page_number": 1,
        "text": "The placement office is in the main building.", "lexical_score": 1.0,
    }
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [source])
    monkeypatch.setattr(chat_api, "generate_grounded_answer",
                        lambda *_args, **_kwargs: "The office is in the main building [1].")
    monkeypatch.setattr(chat_api, "assess_cited_claims",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private detail")))
    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "Where is the placement office?"})
    assert response.status_code == 200
    assert response.json()["abstained"] is True
    assert response.json()["citations"] == []
    assert "private detail" not in response.text


def test_chat_abstains_on_short_uncited_claim_after_cited_statement(client, monkeypatch):
    token = auth(client, "short-uncited-claim@example.edu")
    source = {
        "chunk_id": 94, "document_id": 24, "title": "Approved Placement Policy", "version": 1,
        "category": "placement-policy", "approval_status": "approved", "effective_date": None,
        "expiry_date": None, "page_number": 1,
        "text": "The placement CGPA requirement is 7.5 for placement applicants.", "lexical_score": 1.0,
    }
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [source])
    monkeypatch.setattr(chat_api, "generate_grounded_answer", lambda *_args, **_kwargs:
                        "The placement CGPA requirement is 7.5 for applicants [1]. The approved policy sets the placement threshold [1]. Applicants should meet the stated CGPA before applying [1]. The requirement applies to placement applicants [1]. Backlogs are allowed.")

    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "What is the placement CGPA requirement?"})
    assert response.status_code == 200
    assert response.json()["abstained"] is True
    assert response.json()["citations"] == []
    assert response.json()["citation_coverage"] == 0.8


def test_chat_deterministically_abstains_and_cites_conflicting_active_rules(client, monkeypatch):
    token = auth(client, "conflicting-rules@example.edu")
    sources = [
        {"chunk_id": 92, "document_id": 22, "title": "Policy A", "version": 1, "category": "placement-policy",
         "approval_status": "approved", "effective_date": None, "expiry_date": None, "page_number": 2,
         "text": "Minimum CGPA for placement applicants is 7.5.", "lexical_score": 1.0},
        {"chunk_id": 93, "document_id": 23, "title": "Policy B", "version": 1, "category": "placement-policy",
         "approval_status": "approved", "effective_date": None, "expiry_date": None, "page_number": 1,
         "text": "Minimum CGPA for placement applicants is 8.0.", "lexical_score": 1.0},
    ]
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: sources)
    monkeypatch.setattr(chat_api, "generate_grounded_answer", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not generate through conflict")))
    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "What is the CGPA placement requirement?"})
    assert response.status_code == 200
    result = response.json()
    assert result["abstained"] is True
    assert {citation["document_id"] for citation in result["citations"]} == {22, 23}
    assert any("conflict" in warning for warning in result["temporal_warnings"])


def test_numeric_claim_support_normalizes_format_and_small_number_words():
    answer = "Applicants may have up to 1 backlog under these verified requirements [1]. The score must be 7.5 for admission [1]."
    sources = [{"text": "The approved rule permits one backlog and requires a score of 7.50."}]
    checks = chat_api.analyze_claim_support(answer, sources)
    assert checks[0]["unsupported_numeric_claims"] == []
    assert checks[1]["unsupported_numeric_claims"] == []


def test_citation_checks_include_short_claims():
    answer = "Applicants must meet a CGPA of 7.5 [1]. Backlogs are allowed."
    sources = [{"text": "Applicants must meet a CGPA of 7.5."}]

    assert chat_api.verify_citation_coverage(answer, {1}) == 0.5
    checks = chat_api.analyze_claim_support(answer, sources)
    assert len(checks) == 2
    assert checks[1]["citation_associated"] is False


def test_citation_checks_split_semicolon_separated_claims():
    answer = "The CGPA requirement is 7.5 [1]; Backlogs are allowed."

    assert chat_api.verify_citation_coverage(answer, {1}) == 0.5
    assert chat_api.analyze_claim_support(answer, [{"text": "The CGPA requirement is 7.5."}])[1]["citation_associated"] is False


def test_numeric_claim_support_normalizes_indic_digits():
    checks = chat_api.analyze_claim_support(
        "न्यूनतम CGPA ७.५ होना चाहिए [1]।",
        [{"text": "The minimum CGPA must be 7.50."}],
    )

    assert checks[0]["unsupported_numeric_claims"] == []


def test_historical_date_inference_supports_hindi_kannada_and_indic_year_digits():
    cases = [
        ("What was the CGPA rule in 2024?", 2024),
        ("२०२४ में CGPA का नियम क्या था?", 2024),
        ("೨೦೨೪ರಲ್ಲಿ CGPA ನಿಯಮ ಏನಿತ್ತು?", 2024),
    ]
    for question, year in cases:
        inferred = chat_api.infer_historical_date(question)
        assert inferred is not None
        assert inferred.year == year
        assert inferred.month == 12 and inferred.day == 31


def test_conflicting_policy_warnings_are_localized_for_hindi_and_kannada():
    sources = [
        {"document_id": 1, "text": "Minimum CGPA for placement applicants is 7.5."},
        {"document_id": 2, "text": "Minimum CGPA for placement applicants is 8.0."},
    ]
    hindi = chat_api.detect_numeric_policy_conflicts("CGPA क्या है?", sources, "hi")
    kannada = chat_api.detect_numeric_policy_conflicts("CGPA ಅಗತ್ಯವೇನು?", sources, "kn")
    assert hindi and "सीजीपीए आवश्यकता" in hindi[0]
    assert kannada and "ಸಿಜಿಪಿಎ ಅರ್ಹತೆ" in kannada[0]


def test_historical_chat_uses_localized_year_inference_and_temporal_warning(client, monkeypatch):
    source = {
        "chunk_id": 300, "document_id": 30, "title": "Placement Policy", "version": 1,
        "category": "placement-policy", "approval_status": "superseded", "effective_date": None,
        "expiry_date": None, "page_number": 1, "text": "Applicants should confirm historical rules with the Placement Office.",
        "lexical_score": 1.0,
    }
    cases = [
        ("hi", "ऐतिहासिक-hindi@example.edu", "२०२४ में CGPA का नियम क्या था?", "की ऐतिहासिक खोज"),
        ("kn", "historical-kannada@example.edu", "೨೦೨೪ರಲ್ಲಿ CGPA ನಿಯಮ ಏನಿತ್ತು?", "ರ ಐತಿಹಾಸಿಕ ಹುಡುಕಾಟ"),
    ]
    observed_dates = []

    def retrieve(_db, _query, **filters):
        observed_dates.append(filters["as_of"])
        return [source]

    monkeypatch.setattr(chat_api, "hybrid_retrieve", retrieve)
    monkeypatch.setattr(chat_api, "generate_grounded_answer",
                        lambda *_args: "Please confirm the applicable historical placement rule [1].")
    for language, email, question, warning in cases:
        token = auth(client, email)
        response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                               json={"question": question, "language": language})
        assert response.status_code == 200, response.text
        assert response.json()["abstained"] is False
        assert response.json()["citations"]
        assert warning in response.json()["temporal_warnings"][0]

    assert [value.year for value in observed_dates] == [2024, 2024]


def test_numeric_claim_support_normalizes_hindi_and_kannada_number_words():
    cases = [
        ("न्यूनतम CGPA सात दशमलव पाँच होना चाहिए [1]।", "The minimum CGPA must be 7.50."),
        ("ಕನಿಷ್ಠ CGPA ಏಳು ದಶಮಾಂಶ ಐದು ಇರಬೇಕು [1].", "Minimum CGPA must be seven point five."),
        ("न्यूनतम CGPA आठ दशमलव पाँच होना चाहिए [1]।", "Minimum CGPA must be 7.5."),
    ]
    results = [chat_api.analyze_claim_support(answer, [{"text": source}])[0]["unsupported_numeric_claims"]
               for answer, source in cases]

    assert results == [[], [], ["आठ दशमलव पाँच"]]


def test_chat_abstains_on_unsupported_hindi_number_word_claim(client, monkeypatch):
    token = auth(client, "unsupported-hindi-number@example.edu")
    source = {
        "chunk_id": 301, "document_id": 31, "title": "Approved Placement Policy", "version": 1,
        "category": "placement-policy", "approval_status": "approved", "effective_date": None,
        "expiry_date": None, "page_number": 1, "text": "The minimum CGPA must be 7.5 for placement applicants.",
        "lexical_score": 1.0,
    }
    monkeypatch.setattr(chat_api, "hybrid_retrieve", lambda *_args, **_kwargs: [source])
    monkeypatch.setattr(chat_api, "generate_grounded_answer",
                        lambda *_args: "न्यूनतम CGPA आठ दशमलव पाँच होना चाहिए [1]।")

    response = client.post("/api/v1/chat/", headers={"Authorization": f"Bearer {token}"},
                           json={"question": "CGPA क्या होना चाहिए?", "language": "hi"})

    assert response.status_code == 200
    assert response.json()["abstained"] is True
    assert response.json()["citations"] == []
    assert response.json()["claim_support"][0]["unsupported_numeric_claims"] == ["आठ दशमलव पाँच"]


def test_numeric_claim_support_preserves_percent_units_across_languages():
    cases = [
        ("The policy sets a score of 7.5% [1].", "The policy sets a score of 7.5."),
        ("The policy sets a score of 7.50% [1].", "The policy sets a score of 7.5 percent."),
        ("लक्ष्य 7.5 प्रतिशत होना चाहिए [1]।", "लक्ष्य 7.50% होना चाहिए।"),
        ("ಗುರಿ ಏಳು ದಶಮಾಂಶ ಐದು ಶೇಕಡಾ ಇರಬೇಕು [1].", "The target is 7.5%."),
    ]
    results = [chat_api.analyze_claim_support(answer, [{"text": source}])[0]["unsupported_numeric_claims"]
               for answer, source in cases]

    assert results == [["7.5%"], [], [], []]
