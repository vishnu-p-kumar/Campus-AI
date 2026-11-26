import pytest
from sqlalchemy import select
from app.models import InterviewResponse, InterviewSession, User

from app.api import interviews as interviews_api


def register_student(client, email):
    response = client.post("/api/v1/auth/register", json={
        "email": email, "full_name": "Practice Student", "password": "correct horse battery",
    })
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_multiround_interview_persists_private_score_history_and_completion(client):
    student = register_student(client, "practice@example.edu")
    created = client.post("/api/v1/interviews/sessions", headers=student, json={
        "category": "technical", "language": "en", "focus": "backend developer", "question_type": "typed", "question_limit": 2,
    })
    assert created.status_code == 201
    session = created.json()
    assert session["focus"] == "backend developer"
    first_question = session["question"]

    rejected = client.post(f"/api/v1/interviews/sessions/{session['id']}/responses", headers=student,
                          json={"question": "a different question", "answer": "This answer is long enough to validate."})
    assert rejected.status_code == 409

    answer = client.post(f"/api/v1/interviews/sessions/{session['id']}/responses", headers=student,
                         json={"question": first_question, "answer": "First I tested the solution with an example, then I measured the result and learned from it."})
    assert answer.status_code == 200
    assert answer.json()["completed"] is False
    assert answer.json()["answered_count"] == 1
    assert answer.json()["question_limit"] == 2
    assert answer.json()["question"]
    assert "score" not in answer.json() and "feedback" not in answer.json()

    next_prompt = client.post(f"/api/v1/interviews/sessions/{session['id']}/next-question", headers=student)
    assert next_prompt.status_code == 200
    assert next_prompt.json()["question"] != first_question
    second = client.post(f"/api/v1/interviews/sessions/{session['id']}/responses", headers=student,
                         json={"question": next_prompt.json()["question"], "answer": "I would compare both approaches, test edge cases, measure the result, and explain the tradeoff to my team."})
    assert second.status_code == 200
    assert second.json()["completed"] is True
    assert second.json()["answered_count"] == 2
    assert len(second.json()["results"]) == 2
    assert second.json()["results"][0]["answer"].startswith("First I tested")
    assert "score" in second.json()["results"][0]
    detail = client.get(f"/api/v1/interviews/history/{session['id']}", headers=student)
    assert detail.status_code == 200
    assert len(detail.json()["results"]) == 2

    history = client.get("/api/v1/interviews/history", headers=student)
    assert history.status_code == 200
    summary = history.json()[0]
    assert summary["id"] == session["id"]
    assert summary["response_count"] == 2
    assert summary["average_score"] is not None
    assert 1 <= summary["average_score"] <= 5

    assert second.json()["status"] == "completed"
    assert client.post(f"/api/v1/interviews/sessions/{session['id']}/next-question", headers=student).status_code == 404


def test_interview_history_and_sessions_are_user_scoped(client):
    first = register_student(client, "first-practice@example.edu")
    second = register_student(client, "second-practice@example.edu")
    created = client.post("/api/v1/interviews/sessions", headers=first, json={"category": "aptitude"})
    session_id = created.json()["id"]

    assert client.get("/api/v1/interviews/history", headers=second).json() == []
    assert client.get(f"/api/v1/interviews/history/{session_id}", headers=second).status_code == 404
    assert client.post(f"/api/v1/interviews/sessions/{session_id}/next-question", headers=second).status_code == 404
    assert client.post(f"/api/v1/interviews/sessions/{session_id}/complete", headers=second).status_code == 404


def test_interview_session_defaults_to_aptitude_multiple_choice(client, monkeypatch):
    headers = register_student(client, "default-practice@example.edu")
    monkeypatch.setattr(interviews_api, "generate_question", lambda *_args: {
        "question": "What is three plus two?",
        "choices": [{"id": "A", "text": "4"}, {"id": "B", "text": "5"},
                    {"id": "C", "text": "6"}, {"id": "D", "text": "7"}],
        "correct_option": "B",
    })
    created = client.post("/api/v1/interviews/sessions", headers=headers, json={})
    assert created.status_code == 201, created.text
    assert created.json()["category"] == "aptitude"
    assert created.json()["question_type"] == "multiple_choice"
    assert created.json()["generation_mode"] == "gemini"
    assert len(created.json()["options"]) == 4


def test_student_can_delete_one_practice_history_and_its_saved_answers(client, db_session):
    owner_headers = register_student(client, "delete-practice@example.edu")
    other_headers = register_student(client, "other-delete-practice@example.edu")
    owner_user = db_session.scalar(select(User).where(User.email == "delete-practice@example.edu"))
    first = InterviewSession(user_id=owner_user.id, category="technical", language="en", question_type="typed",
                             question_limit=1, status="completed", score=4.0)
    second = InterviewSession(user_id=owner_user.id, category="hr", language="en", question_type="typed",
                              question_limit=1, status="active", current_question="Tell me about a project.")
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add(InterviewResponse(session_id=first.id, question="Explain an API.", answer="A saved answer.", feedback={}, score=4.0))
    db_session.commit()
    first_id, second_id = first.id, second.id

    deleted = client.delete(f"/api/v1/interviews/history/{first_id}", headers=owner_headers)
    assert deleted.status_code == 204
    assert [item["id"] for item in client.get("/api/v1/interviews/history", headers=owner_headers).json()] == [second_id]
    assert client.get(f"/api/v1/interviews/history/{first_id}", headers=owner_headers).status_code == 404
    assert db_session.scalar(select(InterviewResponse.id).where(InterviewResponse.session_id == first_id)) is None
    assert client.delete(f"/api/v1/interviews/history/{second_id}", headers=other_headers).status_code == 404


def test_multiple_choice_session_generates_options_and_checks_selected_answer(client, monkeypatch):
    headers = register_student(client, "mcq-practice@example.edu")
    generated = {"question": "Which HTTP method retrieves a resource?", "choices": [
        {"id": "A", "text": "POST"}, {"id": "B", "text": "GET"},
        {"id": "C", "text": "PATCH"}, {"id": "D", "text": "DELETE"}], "correct_option": "B"}
    monkeypatch.setattr(interviews_api, "generate_question", lambda *_args: generated)
    created = client.post("/api/v1/interviews/sessions", headers=headers,
                          json={"category": "technical", "language": "en", "question_type": "multiple_choice", "question_limit": 1,
                                "focus": "Backend API developer; HTTP methods"})
    assert created.status_code == 201, created.text
    session = created.json()
    assert session["question_type"] == "multiple_choice"
    assert [item["id"] for item in session["options"]] == ["A", "B", "C", "D"]
    assert "correct_option" not in session

    response = client.post(f"/api/v1/interviews/sessions/{session['id']}/responses", headers=headers,
                           json={"question": session["question"], "answer": "B"})
    assert response.status_code == 200, response.text
    assert response.json()["completed"] is True
    assert response.json()["results"][0]["score"] == 1
    assert response.json()["correct_count"] == 1
    assert response.json()["question_type"] == "multiple_choice"
    assert "GET" in response.json()["results"][0]["feedback"]["improvements"][0]
    result = response.json()["results"][0]
    assert result["feedback"]["correct_option"] == "B"
    assert [choice["id"] for choice in result["feedback"]["options"]] == ["A", "B", "C", "D"]
    detail = client.get(f"/api/v1/interviews/history/{session['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["results"][0]["feedback"]["correct_text"] == "GET"


def test_coding_category_always_starts_multiple_choice_with_code_snippet(client, monkeypatch):
    headers = register_student(client, "coding-mcq@example.edu")
    observed = {}
    generated = {"question": "What does this print?\n\nCODE_SNIPPET (Python):\nvalues = [2, 3]\nprint(values[0] + values[1])", "choices": [
        {"id": "A", "text": "23"}, {"id": "B", "text": "5"},
        {"id": "C", "text": "[2, 3]"}, {"id": "D", "text": "Error"}], "correct_option": "B"}
    def generate(_category, _language, _focus, question_type, *_args):
        observed["question_type"] = question_type
        return generated
    monkeypatch.setattr(interviews_api, "generate_question", generate)
    created = client.post("/api/v1/interviews/sessions", headers=headers, json={
        "category": "coding", "question_type": "typed", "question_limit": 1,
    })
    assert created.status_code == 201, created.text
    assert created.json()["question_type"] == "multiple_choice"
    assert observed["question_type"] == "multiple_choice"
    assert "CODE_SNIPPET" in created.json()["question"]
    assert len(created.json()["options"]) == 4


def test_multiple_choice_generation_uses_curated_fallback_for_a_five_question_session(client, monkeypatch):
    headers = register_student(client, "invalid-mcq@example.edu")
    monkeypatch.setattr(interviews_api, "generate_question", lambda *_args: None)
    response = client.post("/api/v1/interviews/sessions", headers=headers,
                           json={"category": "technical", "question_type": "multiple_choice", "question_limit": 5})
    assert response.status_code == 201, response.text
    session = response.json()
    assert session["generation_mode"] == "curated-question-bank"
    seen = set()
    for index in range(5):
        question = session["question"]
        options = session["options"]
        assert question not in seen
        seen.add(question)
        assert len(options) == 4
        assert {option["id"] for option in options} == {"A", "B", "C", "D"}
        assert "correct_option" not in session and "correct_answer" not in session
        answered = client.post(f"/api/v1/interviews/sessions/{session['id']}/responses", headers=headers,
                               json={"question": question, "answer": options[0]["id"]})
        assert answered.status_code == 200, answered.text
        if index < 4:
            assert answered.json()["completed"] is False
            assert answered.json()["generation_mode"] == "curated-question-bank"
            session["question"] = answered.json()["question"]
            session["options"] = answered.json()["options"]
        else:
            assert answered.json()["completed"] is True
            assert answered.json()["answered_count"] == 5
    assert len(seen) == 5


def test_multiple_choice_scores_correct_as_one_and_wrong_as_zero(client, monkeypatch):
    headers = register_student(client, "binary-mcq@example.edu")
    generated = [
        {"question": "Which structure maps keys to values?", "choices": [
            {"id": "A", "text": "Queue"}, {"id": "B", "text": "Hash map"},
            {"id": "C", "text": "Stack"}, {"id": "D", "text": "Tree"}], "correct_option": "B"},
        {"question": "Which database feature speeds up lookups?", "choices": [
            {"id": "A", "text": "Index"}, {"id": "B", "text": "Trigger"},
            {"id": "C", "text": "View"}, {"id": "D", "text": "Transaction"}], "correct_option": "A"},
    ]
    monkeypatch.setattr(interviews_api, "generate_question", lambda *_args: generated.pop(0))
    created = client.post("/api/v1/interviews/sessions", headers=headers, json={
        "category": "technical", "question_type": "multiple_choice", "question_limit": 2,
    })
    session = created.json()
    first = client.post(f"/api/v1/interviews/sessions/{session['id']}/responses", headers=headers,
                        json={"question": session["question"], "answer": "C"})
    assert first.status_code == 200
    second = client.post(f"/api/v1/interviews/sessions/{session['id']}/responses", headers=headers,
                         json={"question": first.json()["question"], "answer": "A"})
    assert second.status_code == 200
    result = second.json()
    assert [item["score"] for item in result["results"]] == [0, 1]
    assert result["correct_count"] == 1
    assert result["question_limit"] == 2


def test_typed_answer_is_reviewed_against_generated_reference_answer(client, monkeypatch):
    headers = register_student(client, "typed-reference@example.edu")
    expected = "A hash map stores key-value pairs and provides expected constant-time lookup."
    observed = {}
    monkeypatch.setattr(interviews_api, "generate_question", lambda *_args: {
        "question": "How does a hash map store and retrieve values?", "reference_answer": expected,
    })
    def review(question, answer, language, reference_answer):
        observed.update(question=question, answer=answer, language=language, reference_answer=reference_answer)
        return {"score": 4.5, "strengths": ["Accurate key-value explanation."], "improvements": ["Mention collision handling."],
                "correct_answer": reference_answer, "assessment_note": "Practice review."}
    monkeypatch.setattr(interviews_api, "review_answer", review)
    created = client.post("/api/v1/interviews/sessions", headers=headers, json={
        "category": "technical", "question_type": "typed", "question_limit": 1,
    })
    session = created.json()
    assert "reference_answer" not in session
    response = client.post(f"/api/v1/interviews/sessions/{session['id']}/responses", headers=headers, json={
        "question": session["question"], "answer": "A hash map stores key-value pairs with expected constant-time lookup.",
    })
    assert response.status_code == 200
    assert response.json()["results"][0]["score"] == 4.5
    assert response.json()["results"][0]["feedback"]["correct_answer"] == expected
    assert observed["reference_answer"] == expected


def test_interview_questions_progress_by_topic_and_difficulty_and_return_with_saved_answer(client, monkeypatch):
    headers = register_student(client, "progressive-practice@example.edu")
    generated_calls = []

    def generate(category, language, focus, question_type, topic, difficulty, previous):
        generated_calls.append((category, topic, difficulty, list(previous)))
        return {"question": f"{difficulty.title()} question about {topic}?", "choices": [
            {"id": "A", "text": f"First {topic} choice"}, {"id": "B", "text": f"Second {topic} choice"},
            {"id": "C", "text": f"Third {topic} choice"}, {"id": "D", "text": f"Fourth {topic} choice"}], "correct_option": "A"}

    monkeypatch.setattr(interviews_api, "generate_question", generate)
    created = client.post("/api/v1/interviews/sessions", headers=headers, json={
        "category": "technical", "question_type": "multiple_choice", "question_limit": 3,
    })
    assert created.status_code == 201
    first = created.json()
    first_options = [option["text"] for option in first["options"]]

    second_response = client.post(f"/api/v1/interviews/sessions/{first['id']}/responses", headers=headers,
                                  json={"question": first["question"], "answer": "A"})
    assert second_response.status_code == 200
    second = second_response.json()
    assert second["question"] != first["question"]
    assert [option["text"] for option in second["options"]] != first_options

    third_response = client.post(f"/api/v1/interviews/sessions/{first['id']}/responses", headers=headers,
                                 json={"question": second["question"], "answer": "B"})
    assert third_response.status_code == 200
    assert third_response.json()["question"] != second["question"]
    assert [call[2] for call in generated_calls] == ["easy", "medium", "difficult"]
    assert len({call[1] for call in generated_calls}) == 3
    assert generated_calls[1][3] == [first["question"]]


def test_interview_topic_plan_spans_category_topics(client, monkeypatch):
    headers = register_student(client, "topic-practice@example.edu")
    calls = []
    def generate(_category, _language, _focus, _question_type, topic, difficulty, previous):
        calls.append((topic, difficulty, previous))
        return f"Discuss {topic} at {difficulty} level."
    monkeypatch.setattr(interviews_api, "generate_question", generate)
    created = client.post("/api/v1/interviews/sessions", headers=headers, json={
        "category": "hr", "question_type": "typed", "question_limit": 3,
    })
    session = created.json()
    response = client.post(f"/api/v1/interviews/sessions/{session['id']}/responses", headers=headers, json={
        "question": session["question"], "answer": "I set a clear priority, communicated early, and completed the work with my team.",
    })
    assert response.status_code == 200
    assert response.json()["question"] == "Discuss team disagreement at medium level."
    assert calls[0][0] != calls[1][0]
    assert calls[0][1:2] == ("easy",)
    assert calls[1][1:2] == ("medium",)


def test_interview_ask_endpoint_uses_gemini_answer(client, monkeypatch):
    headers = register_student(client, "interview-tutor@example.edu")
    observed = {}
    structured = {"short_answer": "A hash table maps keys to values.", "explanation": "A hash function finds a bucket.",
                  "key_points": ["Average lookup is fast."], "next_question": "How are hash collisions handled?"}
    def answer(question, focus, language):
        observed.update(question=question, focus=focus, language=language)
        return structured
    monkeypatch.setattr(interviews_api, "answer_interview_question", answer)
    response = client.post("/api/v1/interviews/ask", headers=headers, json={
        "question": "Explain a hash table", "focus": "Backend engineer", "language": "en"})
    assert response.status_code == 200
    assert "hash function" in response.json()["answer"]["explanation"]
    assert response.json()["answer"]["next_question"] == "How are hash collisions handled?"
    assert observed == {"question": "Explain a hash table", "focus": "Backend engineer", "language": "en"}


def test_interview_tutor_reports_gemini_overload_with_retry_hint(client, monkeypatch, caplog):
    headers = register_student(client, "interview-tutor-overload@example.edu")

    class ProviderUnavailable(RuntimeError):
        code = 503

    def fail(*_args):
        raise ProviderUnavailable("private provider response must not be shown")

    monkeypatch.setattr(interviews_api, "answer_interview_question", fail)
    response = client.post("/api/v1/interviews/ask", headers=headers, json={
        "question": "What is a REST API?", "language": "en",
    })

    assert response.status_code == 503
    assert response.headers["retry-after"] == "15"
    assert "temporarily overloaded or timed out" in response.json()["detail"]
    assert "private provider response" not in response.text
    assert "category=provider_server_error status_code=503" in caplog.text


@pytest.mark.parametrize(("language", "answer", "expected_script"), [
    ("hi", "पहले मैंने उदाहरण से जाँचा क्योंकि परिणाम मापना जरूरी था। फिर टीम के लिए सीखा हुआ तरीका बताया।", "पहले"),
    ("kn", "ಮೊದಲು ಉದಾಹರಣೆಯಿಂದ ಪರೀಕ್ಷೆ ಮಾಡಿದೆ, ಏಕೆಂದರೆ ಫಲಿತಾಂಶ ಅಳೆಯುವುದು ಮುಖ್ಯ. ನಂತರ ತಂಡಕ್ಕೆ ಕಲಿತ ವಿಧಾನ ವಿವರಿಸಿದೆ.", "ಮೊದಲು"),
])
def test_multilingual_interview_fallback_localizes_questions_and_feedback(
    client, monkeypatch, language, answer, expected_script
):
    headers = register_student(client, f"practice-{language}@example.edu")
    monkeypatch.setattr(interviews_api, "generate_question", lambda *_args: None)
    monkeypatch.setattr(interviews_api, "review_answer", lambda *_args: None)

    created = client.post("/api/v1/interviews/sessions", headers=headers,
                          json={"category": "technical", "language": language, "question_type": "typed", "question_limit": 1})
    assert created.status_code == 201
    session = created.json()
    assert expected_script in answer
    assert session["question"]
    script_range = ("\u0900", "\u097f") if language == "hi" else ("\u0c80", "\u0cff")
    assert any(script_range[0] <= character <= script_range[1] for character in session["question"])
    assert session["generation_mode"] == "curated-question-bank"
    assert session["language_note"] is None

    response = client.post(f"/api/v1/interviews/sessions/{session['id']}/responses", headers=headers,
                           json={"question": session["question"], "answer": answer})
    assert response.status_code == 200
    feedback = response.json()["results"][0]["feedback"]
    assert feedback["assessment_note"]
    assert feedback["rubric_signals"]
    assert response.json()["completed"] is True
    assert feedback["strengths"][0] != "You provided a response with concrete detail."

