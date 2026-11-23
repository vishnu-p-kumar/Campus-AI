from types import SimpleNamespace

from app.ai import gemini
from app.core.config import settings


def test_quota_error_switches_to_next_free_model(monkeypatch):
    monkeypatch.setattr(settings, "gemini_model", "primary-model")
    monkeypatch.setattr(settings, "gemini_fallback_models", "fallback-one,fallback-two")
    calls = []

    class QuotaExceeded(Exception):
        code = 429

    class Models:
        def generate_content(self, *, model, contents, config=None):
            calls.append(model)
            if model == "primary-model":
                raise QuotaExceeded()
            return SimpleNamespace(text='{"ok": true}')

    response, model = gemini.generate_content_with_fallback(
        SimpleNamespace(models=Models()), contents="test", require_json=True
    )

    assert response.text == '{"ok": true}'
    assert model == "fallback-one"
    assert calls == ["primary-model", "fallback-one"]


def test_gemini_409_too_many_requests_switches_to_next_free_model(monkeypatch):
    monkeypatch.setattr(settings, "gemini_model", "primary-model")
    monkeypatch.setattr(settings, "gemini_fallback_models", "fallback-one,fallback-two")
    calls = []

    class TooManyRequests(Exception):
        code = 409

    class Models:
        def generate_content(self, *, model, contents, config=None):
            calls.append(model)
            if model == "primary-model":
                raise TooManyRequests("private provider response")
            return SimpleNamespace(text="answer")

    response, model = gemini.generate_content_with_fallback(
        SimpleNamespace(models=Models()), contents="test"
    )

    assert response.text == "answer"
    assert model == "fallback-one"
    assert calls == ["primary-model", "fallback-one"]


def test_gemini_409_wrapped_api_error_switches_models_when_body_names_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "gemini_model", "primary-model")
    monkeypatch.setattr(settings, "gemini_fallback_models", "fallback-one")
    calls = []

    class APIError(Exception):
        code = 409

    class Models:
        def generate_content(self, *, model, contents, config=None):
            calls.append(model)
            if model == "primary-model":
                raise APIError("409 TooManyRequests")
            return SimpleNamespace(text="answer")

    response, model = gemini.generate_content_with_fallback(
        SimpleNamespace(models=Models()), contents="test"
    )

    assert response.text == "answer"
    assert model == "fallback-one"
    assert calls == ["primary-model", "fallback-one"]


def test_all_gemini_409_rate_limited_models_raise_quota_error(monkeypatch):
    monkeypatch.setattr(settings, "gemini_model", "primary-model")
    monkeypatch.setattr(settings, "gemini_fallback_models", "fallback-one")
    calls = []

    class TooManyRequests(Exception):
        code = 409

    class Models:
        def generate_content(self, *, model, contents, config=None):
            calls.append(model)
            raise TooManyRequests()

    try:
        gemini.generate_content_with_fallback(SimpleNamespace(models=Models()), contents="test")
        assert False, "Expected GeminiQuotaExhausted"
    except gemini.GeminiQuotaExhausted:
        pass

    assert calls == ["primary-model", "fallback-one"]


def test_503_retries_current_model_then_uses_fallback(monkeypatch):
    monkeypatch.setattr(settings, "gemini_model", "primary-model")
    monkeypatch.setattr(settings, "gemini_fallback_models", "fallback-one")
    monkeypatch.setattr(gemini.time, "sleep", lambda _delay: None)
    calls = []

    class TemporarilyUnavailable(Exception):
        code = 503

    class Models:
        def generate_content(self, *, model, contents, config=None):
            calls.append(model)
            if model == "primary-model":
                raise TemporarilyUnavailable()
            return SimpleNamespace(text="ok")

    response, model = gemini.generate_content_with_fallback(
        SimpleNamespace(models=Models()), contents="test"
    )

    assert response.text == "ok"
    assert model == "fallback-one"
    assert calls == ["primary-model", "primary-model", "fallback-one"]


def test_504_gateway_timeout_skips_to_the_next_model(monkeypatch):
    monkeypatch.setattr(settings, "gemini_model", "primary-model")
    monkeypatch.setattr(settings, "gemini_fallback_models", "fallback-one,fallback-two")
    calls = []

    class GatewayTimeout(Exception):
        code = 504

    class Models:
        def generate_content(self, *, model, contents, config=None):
            calls.append(model)
            if model != "fallback-two":
                raise GatewayTimeout()
            return SimpleNamespace(text="ok")

    response, model = gemini.generate_content_with_fallback(
        SimpleNamespace(models=Models()), contents="test", retry_503=False,
    )
    assert response.text == "ok"
    assert model == "fallback-two"
    assert calls == ["primary-model", "fallback-one", "fallback-two"]


def test_fast_interview_fallback_skips_503_retry_and_limits_model_attempts(monkeypatch):
    monkeypatch.setattr(settings, "gemini_model", "primary-model")
    monkeypatch.setattr(settings, "gemini_fallback_models", "fallback-one,fallback-two")
    sleep_calls = []
    monkeypatch.setattr(gemini.time, "sleep", lambda delay: sleep_calls.append(delay))
    calls = []

    class TemporarilyUnavailable(Exception):
        code = 503

    class Models:
        def generate_content(self, *, model, contents, config=None):
            calls.append(model)
            if model == "primary-model":
                raise TemporarilyUnavailable()
            return SimpleNamespace(text="ok")

    response, model = gemini.generate_content_with_fallback(
        SimpleNamespace(models=Models()), contents="test", max_models=2, retry_503=False
    )

    assert response.text == "ok"
    assert model == "fallback-one"
    assert calls == ["primary-model", "fallback-one"]
    assert sleep_calls == []


def test_unavailable_fallback_model_is_skipped(monkeypatch):
    monkeypatch.setattr(settings, "gemini_model", "primary-model")
    monkeypatch.setattr(settings, "gemini_fallback_models", "missing-model,available-model")
    calls = []

    class ModelNotFound(Exception):
        code = 404

    class Models:
        def generate_content(self, *, model, contents, config=None):
            calls.append(model)
            if model in {"primary-model", "missing-model"}:
                raise ModelNotFound()
            return SimpleNamespace(text="ok")

    response, model = gemini.generate_content_with_fallback(
        SimpleNamespace(models=Models()), contents="test"
    )

    assert response.text == "ok"
    assert model == "available-model"
    assert calls == ["primary-model", "missing-model", "available-model"]
