from app.api import resumes as resumes_api
from app.models import ResumeAnalysis, SkillGapAnalysis, User
from app.upload_scan import MalwareDetected
from sqlalchemy import select


def test_resume_summary_and_persisted_skill_gap(client, monkeypatch):
    resume_review = {"summary": "A Python developer with a data-analysis project.", "strengths": ["Built a Python project."],
                     "improvement_areas": [{"section": "Projects", "current_excerpt": "Built a Python data analysis app.",
                                            "recommendation": "Add a measurable outcome if available.", "changes_to_make": ["Add a verified outcome."]}],
                     "provider": "Gemini", "sections_extracted_by_ai": True,
                     "extracted_sections": {"skills": ["Python", "SQL"], "education": ["B.Tech, 2027"],
                                                "projects": ["Built a Python data analysis app."], "experience": []},
                         "role_comparison": {"role_summary": "A data engineering role.", "candidate_alignment": "Python and SQL are present.",
                                             "required_skills": ["Python", "SQL", "Docker"], "matching_skills": ["Python", "SQL"],
                                             "missing_skills": ["Docker"], "roadmap": [], "resume_changes": [], "provider": "Gemini"}}
    skill_guidance = {"role_summary": "A data engineering role.", "candidate_alignment": "Python and SQL are present.",
                      "required_skills": ["Python", "SQL", "Docker"], "matching_skills": ["Python", "SQL"], "missing_skills": ["Docker"],
                      "roadmap": [{"skill": "Docker", "priority": "medium", "topics": "Images", "project": "Containerize an API", "estimated_duration": "1 week"}],
                      "resume_changes": [{"skill": "Docker", "section": "Projects", "current_excerpt": "Built a Python data analysis app.", "change": "After building it, add a project entry describing the containerized API."}],
                      "provider": "Gemini"}
    monkeypatch.setattr(resumes_api, "analyze_resume_text", lambda _text: resume_review)
    analysis_inputs = []
    monkeypatch.setattr(resumes_api, "analyze_resume_text", lambda *args: (analysis_inputs.append(args) or resume_review))
    monkeypatch.setattr(resumes_api, "review_skill_gap", lambda *_args: skill_guidance)
    monkeypatch.setattr(resumes_api.settings, "gemini_api_key", "test-resume-key")
    register = client.post("/api/v1/auth/register", json={"email": "resume@example.edu", "full_name": "Resume User", "password": "correct horse battery"})
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}
    document = b"Alex Candidate\nemail alex@example.edu\nEducation: B.Tech, 2027\nSkills: Python, SQL\nProject: Built a Python data analysis app."
    parsed = client.post("/api/v1/resumes/analyze", headers=headers,
                         data={"job_title": "Data Engineer", "job_description": "We need Python, SQL, Docker and PostgreSQL skills for data services."},
                         files={"file": ("resume.txt", document, "text/plain")})
    assert parsed.status_code == 200, parsed.text
    assert "python" in parsed.json()["skills"]
    assert parsed.json()["ai_review"]["summary"] == resume_review["summary"]
    assert "extracted_sections" not in parsed.json()["ai_review"]
    assert parsed.json()["ai_status"] == "complete"
    assert parsed.json()["role_comparison"]["matching_skills"] == ["Python", "SQL"]
    assert "Built a Python data analysis app" in analysis_inputs[0][0]
    assert analysis_inputs[0][1:] == ("Data Engineer", "We need Python, SQL, Docker and PostgreSQL skills for data services.")
    assert parsed.json()["privacy"].startswith("The uploaded files and full resume text are not saved")

    gap = client.post("/api/v1/resumes/skill-gap", headers=headers, json={"job_title": "Data Engineer", "job_description": "We need Python, SQL, Docker, and PostgreSQL skills to build data services."})
    assert gap.status_code == 200, gap.text
    assert {skill.casefold() for skill in gap.json()["matching_skills"]} >= {"python", "sql"}
    assert gap.json()["missing_skills"] == ["Docker"]
    assert gap.json()["ai_guidance"] == skill_guidance
    history = client.get("/api/v1/resumes/skill-gap/history", headers=headers)
    assert history.status_code == 200 and history.json()[0]["job_title"] == "Data Engineer"
    assert history.json()[0]["ai_guidance"] == skill_guidance
    assert history.json()[0]["ai_status"] == "complete"
    latest = client.get("/api/v1/resumes/latest", headers=headers)
    assert latest.json()["ai_review"]["summary"] == resume_review["summary"]
    assert latest.json()["ai_status"] == "complete"


def test_resume_upload_rejects_infected_content_before_analysis(client, monkeypatch):
    register = client.post("/api/v1/auth/register", json={"email": "infected-resume@example.edu", "full_name": "Resume User", "password": "correct horse battery"})
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}
    monkeypatch.setattr(resumes_api, "scan_upload", lambda _content: (_ for _ in ()).throw(MalwareDetected()))
    response = client.post("/api/v1/resumes/analyze", headers=headers,
                           files={"file": ("resume.txt", b"malicious test payload", "text/plain")})
    assert response.status_code == 400
    assert "malware scan" in response.json()["detail"]


def test_resume_sections_use_grounded_structured_ai_extraction(client, monkeypatch):
    register = client.post("/api/v1/auth/register", json={"email": "resume-sections@example.edu", "full_name": "Resume User", "password": "correct horse battery"})
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}
    review = {"summary": "A computer engineering student with a Python API project.", "strengths": ["Built a Python API."],
              "improvement_areas": [
                  {"section": "Projects", "current_excerpt": "Built a FastAPI inventory service.",
                   "recommendation": "The project outcome is unclear.", "changes_to_make": ["Describe your contribution."]},
                  {"section": "Experience", "current_excerpt": "Invented text not in the source.",
                   "recommendation": "Clarify this section.", "changes_to_make": ["Add a verified detail."]},
              ], "provider": "Gemini", "sections_extracted_by_ai": True,
              "extracted_sections": {"skills": ["Python", "FastAPI", "NotInResume"],
                                     "education": ["Bachelor of Engineering, 2026"],
                                     "projects": ["Built a FastAPI inventory service."],
                                     "experience": ["Software intern at Demo Labs."]}}
    monkeypatch.setattr(resumes_api.settings, "gemini_api_key", "configured-test-key")
    monkeypatch.setattr(resumes_api, "analyze_resume_text", lambda *_args: review.copy())
    document = b"Education: Bachelor of Engineering, 2026\nSkills: Python, FastAPI\nProjects: Built a FastAPI inventory service.\nExperience: Software intern at Demo Labs."
    response = client.post("/api/v1/resumes/analyze", headers=headers,
                           files={"file": ("resume.txt", document, "text/plain")})
    assert response.status_code == 200, response.text
    assert response.json()["skills"] == ["python", "fastapi"]
    assert response.json()["education"] == ["Bachelor of Engineering, 2026"]
    assert response.json()["projects"] == ["Built a FastAPI inventory service."]
    assert response.json()["experience"] == ["Software intern at Demo Labs."]
    improvements = response.json()["ai_review"]["improvement_areas"]
    assert improvements[0]["current_excerpt"] == "Built a FastAPI inventory service."
    assert improvements[0]["changes_to_make"] == ["Describe your contribution."]
    assert improvements[1]["current_excerpt"] == ""
    assert "NotInResume" not in str(response.json())
    assert "extracted_sections" not in response.json()["ai_review"]


def test_resume_skill_extraction_keeps_short_and_punctuated_skills():
    text = "Skills: C++, C#, Go, R, Rust"
    skills = resumes_api._grounded_resume_section(["C++", "C#", "Go", "R", "Rust", "Java"], text, 40,
                                                   lowercase=True, allow_short=True)
    assert skills == ["c++", "c#", "go", "r", "rust"]


def test_resume_ai_failure_does_not_save_local_analysis(client, monkeypatch):
    register = client.post("/api/v1/auth/register", json={"email": "resume-ai-down@example.edu", "full_name": "Resume User", "password": "correct horse battery"})
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}
    monkeypatch.setattr(resumes_api.settings, "gemini_api_key", "configured-test-key")
    monkeypatch.setattr(resumes_api, "analyze_resume_text", lambda *_args: (_ for _ in ()).throw(RuntimeError("temporary provider outage")))
    response = client.post("/api/v1/resumes/analyze", headers=headers,
                           files={"file": ("resume.txt", b"Student. Skills: Python. Project: Python API.", "text/plain")})
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]
    latest = client.get("/api/v1/resumes/latest", headers=headers)
    assert latest.json() == {"analysis": None}


def test_resume_analysis_requires_configured_ai_key(client, monkeypatch):
    register = client.post("/api/v1/auth/register", json={"email": "resume-headings@example.edu", "full_name": "Resume User", "password": "correct horse battery"})
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}
    monkeypatch.setattr(resumes_api.settings, "gemini_api_key", "")
    document = b"EDUCATION\nBachelor of Engineering, Computer Science, 2026\nSkills: Python and SQL"
    response = client.post("/api/v1/resumes/analyze", headers=headers,
                           files={"file": ("resume.txt", document, "text/plain")})
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
    assert client.get("/api/v1/resumes/latest", headers=headers).json() == {"analysis": None}


def test_role_pdf_comparison_reuses_the_selected_resume_and_uses_ai(client, db_session, monkeypatch):
    register = client.post("/api/v1/auth/register", json={
        "email": "role-pdf-compare@example.edu", "full_name": "Role PDF User", "password": "correct horse battery",
    })
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}
    user = db_session.scalar(select(User).where(User.email == "role-pdf-compare@example.edu"))
    selected = ResumeAnalysis(user_id=user.id, filename="first-resume.txt", skills=["python", "sql"],
                              education=[], projects=["Built a Python API"], experience=[], quality_feedback=[])
    later = ResumeAnalysis(user_id=user.id, filename="later-resume.txt", skills=["java"],
                           education=[], projects=[], experience=[], quality_feedback=[])
    db_session.add_all([selected, later])
    db_session.commit()
    db_session.refresh(selected)
    monkeypatch.setattr(resumes_api, "extract_pages", lambda _path: [(1, "Role: Python developer. Python, SQL, Docker, and Java skills required to build APIs.")])
    monkeypatch.setattr(resumes_api.settings, "gemini_api_key", "configured-test-key")
    monkeypatch.setattr(resumes_api, "review_skill_gap", lambda *_args: {
        "role_summary": "Python developer", "candidate_alignment": "Python and SQL appear in the resume.",
        "required_skills": ["Python", "SQL", "Docker", "Java"], "matching_skills": ["Python", "SQL"],
        "missing_skills": ["Docker", "Java"], "roadmap": [], "resume_changes": [], "provider": "Gemini",
    })

    response = client.post("/api/v1/resumes/skill-gap/compare", headers=headers,
                           data={"resume_analysis_id": str(selected.id), "job_title": "Python Developer"},
                           files={"role_file": ("role.pdf", b"%PDF-1.4 fake but validated by test double", "application/pdf")})
    assert response.status_code == 200, response.text
    assert {skill.casefold() for skill in response.json()["matching_skills"]} >= {"python", "sql"}
    assert "java" not in {skill.casefold() for skill in response.json()["matching_skills"]}
    assert {"docker", "java"}.issubset({skill.casefold() for skill in response.json()["missing_skills"]})
    record = db_session.scalar(select(SkillGapAnalysis).where(SkillGapAnalysis.user_id == user.id))
    assert record.resume_analysis_id == selected.id
    assert record.job_title == "Python Developer"


def test_role_comparison_with_pasted_details_requires_gemini(client, db_session, monkeypatch):
    register = client.post("/api/v1/auth/register", json={
        "email": "role-text-compare@example.edu", "full_name": "Role Text User", "password": "correct horse battery",
    })
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}
    user = db_session.scalar(select(User).where(User.email == "role-text-compare@example.edu"))
    resume = ResumeAnalysis(user_id=user.id, filename="student.txt", skills=["react"],
                            education=[], projects=[], experience=[], quality_feedback=[])
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(resume)
    response = client.post("/api/v1/resumes/skill-gap/compare", headers=headers, data={
        "resume_analysis_id": str(resume.id), "job_title": "Frontend Developer",
        "job_description": "Looking for React, TypeScript, and accessible interface development skills.",
    })
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_role_comparison_requires_title_but_accepts_title_without_details(client, db_session, monkeypatch):
    register = client.post("/api/v1/auth/register", json={
        "email": "role-title-only@example.edu", "full_name": "Role Title User", "password": "correct horse battery",
    })
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}
    user = db_session.scalar(select(User).where(User.email == "role-title-only@example.edu"))
    resume = ResumeAnalysis(user_id=user.id, filename="student.txt", skills=["python"],
                            education=[], projects=["Built a Python API"], experience=[], quality_feedback=[])
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(resume)
    monkeypatch.setattr(resumes_api.settings, "gemini_api_key", "configured-test-key")
    calls = []
    monkeypatch.setattr(resumes_api, "review_skill_gap", lambda title, details, summary: (
        calls.append((title, details, summary)) or {
            "role_summary": "Backend role", "candidate_alignment": "Python is evidenced.",
            "required_skills": ["Python"], "matching_skills": ["Python"], "missing_skills": [],
            "roadmap": [], "resume_changes": [], "provider": "Gemini",
        }
    ))

    missing_title = client.post("/api/v1/resumes/skill-gap/compare", headers=headers,
                                data={"resume_analysis_id": str(resume.id)})
    assert missing_title.status_code == 422

    response = client.post("/api/v1/resumes/skill-gap/compare", headers=headers,
                           data={"resume_analysis_id": str(resume.id), "job_title": "Backend Developer"})
    assert response.status_code == 200, response.text
    assert response.json()["job_title"] == "Backend Developer"
    assert calls[0][0] == "Backend Developer"
    assert calls[0][1] == ""

    full_resume = "Resume top section\n" + ("More resume details. " * 1000) + "COMPLETE_RESUME_END_MARKER"
    monkeypatch.setattr(resumes_api, "extract_pages", lambda path: [(1, full_resume)])
    with_file = client.post(
        "/api/v1/resumes/skill-gap/compare", headers=headers,
        data={"resume_analysis_id": str(resume.id), "job_title": "Backend Developer"},
        files={"resume_file": ("student.txt", full_resume.encode(), "text/plain")},
    )
    assert with_file.status_code == 200, with_file.text
    assert calls[1][2]["resume_text"].endswith("COMPLETE_RESUME_END_MARKER")


def test_resume_parser_errors_do_not_echo_private_content_or_paths(client, monkeypatch, caplog):
    register = client.post("/api/v1/auth/register", json={
        "email": "resume-parser-error@example.edu", "full_name": "Resume User", "password": "correct horse battery",
    })
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}
    private_marker = "PRIVATE_RESUME_FRAGMENT"

    def fail_extraction(_path):
        raise RuntimeError(f"parser failed near {private_marker} at C:/Users/student/resume.txt")

    monkeypatch.setattr(resumes_api, "extract_pages", fail_extraction)
    response = client.post("/api/v1/resumes/analyze", headers=headers,
                           files={"file": ("resume.txt", b"Publicly harmless test body.", "text/plain")})
    assert response.status_code == 422
    assert private_marker not in response.text
    assert "C:/Users/student" not in response.text
    assert private_marker not in caplog.text
    assert "Resume extraction failed (RuntimeError)" in caplog.text


