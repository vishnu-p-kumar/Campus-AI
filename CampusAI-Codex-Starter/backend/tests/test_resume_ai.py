import json
from types import SimpleNamespace

from app.ai import gemini, resume
from app.core.config import settings


def test_resume_review_uses_resume_key_and_redacts_contact_details(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "resume-key")
    calls = []

    class Models:
        def generate_content(self, *, model, config, contents):
            calls.append((model, config, contents))
            return SimpleNamespace(text=json.dumps({
                "summary": "A student developer with a data project.",
                "strengths": ["Built a data project."],
                "improvement_areas": [{"section": "Projects", "current_excerpt": "Project: Python data app.",
                                       "recommendation": "The project outcome is unclear.",
                                       "changes_to_make": ["Describe your specific contribution.", "Add a verified outcome if available."]}],
                "extracted_sections": {"skills": ["Python", "SQL"], "education": ["B.Tech, 2027"],
                                       "projects": ["Project: Python data app."], "experience": []},
            }))

    close_calls = []
    monkeypatch.setattr(resume, "_create_client", lambda key: (
        calls.append(("api_key", key)) or SimpleNamespace(models=Models(), close=lambda: close_calls.append(True))
    ))

    result = resume.analyze_resume_text("Alex\nEmail: alex@example.edu\nPhone: +1 555 123 4567\nEducation: B.Tech, 2027\nSkills: Python, SQL\nProject: Python data app.")

    assert result["provider"] == "Gemini"
    assert result["summary"].startswith("A student developer")
    assert result["sections_extracted_by_ai"] is True
    assert result["extracted_sections"]["projects"] == ["Project: Python data app."]
    improvement = result["improvement_areas"][0]
    assert improvement["current_excerpt"] == "Project: Python data app."
    assert improvement["changes_to_make"] == ["Describe your specific contribution.", "Add a verified outcome if available."]
    prompt = calls[1][2]
    assert "alex@example.edu" not in prompt
    assert "555 123 4567" not in prompt
    assert "[redacted email]" in prompt and "[redacted phone]" in prompt
    assert calls[0] == ("api_key", "resume-key")
    assert close_calls == [True]


def test_role_guidance_returns_gemini_skill_match_and_section_edits(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "resume-key")
    response = SimpleNamespace(text=json.dumps({
        "role_summary": "A data engineering role.",
        "candidate_alignment": "The resume lists Python.",
        "required_skills": ["Python", "Docker"], "matching_skills": ["Python"], "missing_skills": ["Docker"],
        "roadmap": [{"skill": "Docker", "priority": "medium", "topics": "Images and networking", "project": "Containerize a small API", "estimated_duration": "1 week"}],
        "resume_changes": [{"skill": "Docker", "section": "Projects", "current_excerpt": "Python API project", "change": "After building one, describe how you containerized the API."}],
    }))
    monkeypatch.setattr(resume, "_create_client", lambda _key: SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **_kwargs: response)
    ))

    result = resume.review_skill_gap(
        "Data Engineer", "Python and Docker required.",
        {"skills": ["Python"], "education": [], "projects": ["Python API project"], "experience": []},
    )

    assert result["required_skills"] == ["Python", "Docker"]
    assert result["matching_skills"] == ["Python"]
    assert result["missing_skills"] == ["Docker"]
    assert [item["skill"] for item in result["resume_changes"]] == ["Docker"]


def test_resume_and_target_role_are_analyzed_in_one_gemini_request(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "resume-key")
    calls = []
    output = {
        "summary": "A Python developer.", "strengths": ["Built an API."], "improvement_areas": [],
        "extracted_sections": {"skills": ["Python"], "education": [], "projects": ["Built a Python API."], "experience": []},
        "role_comparison": {
            "role_summary": "Backend developer", "candidate_alignment": "Python is evidenced.",
            "required_skills": ["Python", "Docker"], "matching_skills": ["Python"], "missing_skills": ["Docker"],
            "roadmap": [{"skill": "Docker", "priority": "medium", "topics": "Images", "project": "Containerize an API", "estimated_duration": "1 week"}],
            "resume_changes": [{"skill": "Docker", "section": "Projects", "current_excerpt": "Built a Python API.", "change": "After building it, describe the container setup."}],
        },
    }

    class Models:
        def generate_content(self, *, model, config, contents):
            calls.append(contents)
            return SimpleNamespace(text=json.dumps(output))

    monkeypatch.setattr(resume, "_create_client", lambda _key: SimpleNamespace(models=Models()))
    result = resume.analyze_resume_text("Skills: Python\nProjects: Built a Python API.", "Backend Developer", "Python and Docker required for API development.")

    assert len(calls) == 1
    assert "Built a Python API" in calls[0]
    assert "Backend Developer" in calls[0] and "Docker required" in calls[0]
    assert result["role_comparison"]["matching_skills"] == ["Python"]
    assert result["role_comparison"]["missing_skills"] == ["Docker"]

    title_only_result = resume.analyze_resume_text("Skills: Python\nProjects: Built a Python API.", "Data Engineer")
    assert len(calls) == 2
    assert "Data Engineer" in calls[1]
    assert title_only_result["role_comparison"]["required_skills"] == ["Python", "Docker"]


def test_resume_generation_uses_a_bounded_free_model_fallback_chain(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "resume-key")
    monkeypatch.setattr(resume, "_create_client", lambda _key: SimpleNamespace())
    captured = {}

    def generate(_client, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text='{"ok": true}'), "free-model"

    monkeypatch.setattr(resume, "generate_content_with_fallback", generate)
    assert resume._generate_json("Return JSON.") == {"ok": True}
    assert captured["max_models"] == 4
    assert captured["retry_503"] is False
    assert captured["config"]["max_output_tokens"] == 1600


def test_resume_generation_skips_a_503_model_and_uses_fallback(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "resume-key")
    attempts = []
    delays = []

    class TemporaryUnavailable(Exception):
        code = 503

    class Models:
        def generate_content(self, **_kwargs):
            attempts.append(True)
            if len(attempts) == 1:
                raise TemporaryUnavailable()
            return SimpleNamespace(text='{"ok": true}')

    monkeypatch.setattr(resume, "_create_client", lambda _key: SimpleNamespace(models=Models()))
    monkeypatch.setattr(gemini.time, "sleep", delays.append)

    result = resume._generate_json("Return JSON.")

    assert result == {"ok": True}
    assert len(attempts) == 2
    assert delays == []


def test_malformed_gemini_json_is_retried(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "resume-key")
    attempts = []
    delays = []

    class Models:
        def generate_content(self, **_kwargs):
            attempts.append(True)
            text = "not complete json" if len(attempts) == 1 else '{"ok": true}'
            return SimpleNamespace(text=text)

    monkeypatch.setattr(resume, "_create_client", lambda _key: SimpleNamespace(models=Models()))
    monkeypatch.setattr(gemini.time, "sleep", delays.append)

    result = resume._generate_json("Return JSON.")

    assert result == {"ok": True}
    assert len(attempts) == 2
    assert delays == [0.5]


def test_resume_review_sends_text_after_former_sixteen_thousand_character_limit(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "resume-key")
    prompts = []
    result = {
        "summary": "A student with a complete resume.", "strengths": [], "improvement_areas": [],
        "extracted_sections": {"skills": [], "education": [], "projects": [], "experience": []},
    }

    class Models:
        def generate_content(self, *, model, config, contents):
            prompts.append(contents)
            return SimpleNamespace(text=json.dumps(result))

    monkeypatch.setattr(resume, "_create_client", lambda _key: SimpleNamespace(models=Models()))
    full_resume = "Skills: Python\n" + ("additional resume detail " * 900) + "FINAL_RESUME_LINE_MUST_REACH_AI"

    resume.analyze_resume_text(full_resume)

    assert "FINAL_RESUME_LINE_MUST_REACH_AI" in prompts[0]
    assert len(prompts[0]) > 16_000
