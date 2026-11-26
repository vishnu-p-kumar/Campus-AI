from app.api import chat as chat_api


def auth(client, email, role="student", db_session=None):
    if role != "student":
        from app.models import User
        from app.security import hash_password
        user = User(
            email=email,
            full_name="Placement Chat Staff",
            password_hash=hash_password("correct horse battery"),
            role=role,
        )
        db_session.add(user)
        db_session.commit()
        response = client.post("/api/v1/auth/login", json={
            "email": email,
            "password": "correct horse battery",
        })
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    response = client.post("/api/v1/auth/register", json={
        "email": email,
        "full_name": "Placement Chat Student",
        "password": "correct horse battery",
    })
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_chat_uses_placement_query_bot_and_persists_formatted_answer(client, monkeypatch):
    headers = auth(client, "placement-bot-chat@example.edu")
    calls = []

    def ask(question, **options):
        calls.append((question, options))
        return {
            "answer": "**Placement eligibility**\n- Minimum CGPA: 7.5 [1]\n\nSources:\n[1] internal file",
            "route": "faq",
            "score": 0.82,
            "queries_used": 1,
            "daily_query_limit": 25,
            "queries_remaining": 24,
            "reset_date": "2026-11-26",
        }

    monkeypatch.setattr("app.placement_query_bot.ask", ask)
    response = client.post("/api/v1/chat/", headers=headers, json={
        "question": "What is the minimum CGPA for placement?",
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == "Placement eligibility\n- Minimum CGPA: 7.5"
    assert body["route"] == "faq"
    assert body["queries_remaining"] == 24
    assert body["citations"] == []
    assert calls == [("What is the minimum CGPA for placement?", {})]

    history = client.get(
        f"/api/v1/chat/conversations/{body['conversation_id']}",
        headers=headers,
    )
    assert history.status_code == 200
    assert [message["role"] for message in history.json()] == ["user", "assistant"]
    assert history.json()[-1]["content"] == body["answer"]


def test_chat_does_not_leak_conversations_between_students(client, monkeypatch):
    first_headers = auth(client, "first-chat-owner@example.edu")
    second_headers = auth(client, "second-chat-owner@example.edu")
    monkeypatch.setattr("app.placement_query_bot.ask", lambda *_args, **_kwargs: {
        "answer": "Placement FAQ answer.", "route": "faq", "score": 0.7,
    })
    created = client.post("/api/v1/chat/", headers=first_headers, json={
        "question": "How does placement training work?",
    })
    assert created.status_code == 200, created.text
    conversation_id = created.json()["conversation_id"]

    read = client.get(f"/api/v1/chat/conversations/{conversation_id}", headers=second_headers)
    delete = client.delete(f"/api/v1/chat/conversations/{conversation_id}", headers=second_headers)
    assert read.status_code == 404
    assert delete.status_code == 404
    assert client.get(f"/api/v1/chat/conversations/{conversation_id}", headers=first_headers).status_code == 200


def test_chat_uses_local_company_answers_without_charging_bot_query(client, db_session, monkeypatch):
    from app.models import Company

    headers = auth(client, "company-chat@example.edu", role="administrator", db_session=db_session)
    company = Company(
        name="Synthetic Company Chat Ltd",
        industry="Software",
        description="Builds campus hiring software.",
        job_roles=["Software Engineer"],
    )
    db_session.add(company)
    db_session.commit()
    calls = []

    def ask(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "answer": kwargs["answer_override"],
            "route": "faq",
            "score": 0.8,
            "queries_used": 0,
            "daily_query_limit": 25,
            "queries_remaining": 25,
        }

    monkeypatch.setattr("app.placement_query_bot.ask", ask)
    response = client.post("/api/v1/chat/", headers=headers, json={
        "question": "Tell me about Synthetic Company Chat Ltd roles and details.",
    })

    assert response.status_code == 200, response.text
    assert "Builds campus hiring software." in response.json()["answer"]
    assert "Software Engineer" in response.json()["answer"]
    assert response.json()["citations"][0]["company_id"] == company.id
    assert calls and calls[0][1]["log_query"] is False
    assert "answer_override" in calls[0][1]


def test_chat_strips_answer_citations_and_source_section():
    answer = chat_api._chat_answer_text(
        "**Eligibility**\n- CGPA 7.5 [1]\n\nSources:\n[1] approved handbook"
    )
    assert answer == "Eligibility\n- CGPA 7.5"
