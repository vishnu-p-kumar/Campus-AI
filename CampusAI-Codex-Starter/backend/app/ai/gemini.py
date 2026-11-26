import json
import logging
import re
import time

from app.core.config import settings

logger = logging.getLogger(__name__)


class GeminiQuotaExhausted(RuntimeError):
    """All configured generation models returned a rate/quota limit response."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class GeminiGenerationError(RuntimeError):
    """Safe generation failure metadata for API responses and operational logs."""

    def __init__(self, message: str, *, category: str, status_code: int | None = None):
        super().__init__(message)
        self.category = category
        self.status_code = status_code


_PROVIDER_REASON_CATEGORIES = {
    "API_KEY_INVALID": "invalid_api_key",
    "INVALID_API_KEY": "invalid_api_key",
    "API_KEY_EXPIRED": "expired_api_key",
    "KEY_EXPIRED": "expired_api_key",
    "SERVICE_DISABLED": "api_not_enabled",
    "API_NOT_ENABLED": "api_not_enabled",
    "BILLING_DISABLED": "billing_not_enabled",
    "BILLING_NOT_ENABLED": "billing_not_enabled",
    "QUOTA_EXCEEDED": "quota_exhausted",
    "RESOURCE_EXHAUSTED": "quota_exhausted",
    "TOO_MANY_REQUESTS": "rate_limited",
    "TOO_MANY_REQUEST": "rate_limited",
    "RATE_LIMIT_EXCEEDED": "rate_limited",
    "MODEL_NOT_FOUND": "model_not_found",
    "INVALID_ARGUMENT": "invalid_request",
    "PERMISSION_DENIED": "permission_denied",
}


def _safe_provider_reason(exc: Exception) -> str | None:
    """Map allow-listed SDK reason enums to a diagnostic category; never log payload text."""
    try:
        details = getattr(exc, "details", None)
    except Exception:
        return None
    pending = [(details, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 8:
            continue
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).casefold() in {"reason", "status", "code", "type"} and isinstance(child, str):
                    enum = child.rsplit("/", 1)[-1].rsplit(".", 1)[-1].upper()
                    category = _PROVIDER_REASON_CATEGORIES.get(enum)
                    if category:
                        return category
                if isinstance(child, (dict, list, tuple)):
                    pending.append((child, depth + 1))
        elif isinstance(value, (list, tuple)):
            pending.extend((child, depth + 1) for child in value if isinstance(child, (dict, list, tuple)))
    return None


def _provider_failure_diagnostic(exc: Exception) -> tuple[str, int | None]:
    """Return only coarse, non-sensitive provider diagnostics for server logs."""
    pending = [exc]
    seen: set[int] = set()
    fallback: tuple[str, int | None] = ("provider_or_sdk_error", None)
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        status_code = getattr(current, "code", None)
        if not isinstance(status_code, int):
            status_code = getattr(current, "status_code", None)
        if not isinstance(status_code, int):
            status_code = None

        reason_category = _safe_provider_reason(current)
        if reason_category:
            return reason_category, status_code
        # Some Gemini SDK / AI Studio responses identify throttling as a
        # TooManyRequests exception with HTTP 409 instead of the usual 429.
        # Treat that named response as a quota failure so the model fallback
        # chain can continue, while leaving unrelated 409 conflicts untouched.
        exception_name = type(current).__name__.casefold()
        try:
            exception_summary = str(current).casefold()
        except Exception:
            exception_summary = ""
        if ("toomanyrequests" in exception_name
                or "too many requests" in exception_summary
                or "toomanyrequests" in exception_summary.replace("_", "").replace(" ", "")):
            return "quota_or_rate_limited", status_code or 409
        if getattr(current, "winerror", None) == 10013:
            return "network_access_denied", status_code

        name = type(current).__name__.casefold()
        if status_code == 401:
            return "unauthenticated", status_code
        if status_code == 403:
            return "permission_denied", status_code
        if status_code == 404:
            return "model_or_endpoint_not_found", status_code
        if status_code == 429:
            return "quota_or_rate_limited", status_code
        if status_code == 400:
            return "invalid_request_or_model", status_code
        if status_code is not None and status_code >= 500:
            return "provider_server_error", status_code
        if "connect" in name or "timeout" in name or isinstance(current, ConnectionError):
            return "network_connectivity", status_code

        fallback = ("provider_or_sdk_error", status_code)
        for linked in (getattr(current, "__cause__", None), getattr(current, "__context__", None)):
            if isinstance(linked, Exception) and id(linked) not in seen:
                pending.append(linked)
    return fallback


def _create_client(api_key: str):
    from google import genai
    # Keep the SDK from adding another hidden retry layer. Resume generation
    # owns the bounded model fallback and retry policy below.
    return genai.Client(api_key=api_key, http_options={
        # Resume reviews include structured sections and role guidance in one
        # response; allow a little more generation time while keeping calls bounded.
        "timeout": 30_000,
        "retry_options": {"attempts": 1},
    })


def _close_client(client) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.debug("Gemini SDK client close failed")


def _gemini_model_candidates() -> list[str]:
    """Return the configured model followed by distinct free-tier fallbacks."""
    configured = [settings.gemini_model]
    configured.extend(
        value.strip()
        for value in settings.gemini_fallback_models.split(",")
        if value.strip()
    )
    result, seen = [], set()
    for model in configured:
        if model not in seen:
            result.append(model)
            seen.add(model)
    return result


def generate_content_with_fallback(client, *, contents, config=None, require_json: bool = False,
                                  max_models: int | None = None, retry_transient_errors: bool = True):
    """Generate with the primary model, then free-tier fallbacks on quota or availability errors.

    Resume and skill requests retry transient 503/504 responses with bounded
    exponential backoff before moving to the next configured model. Key,
    permission, and invalid-request errors are surfaced unchanged.
    Returns the SDK response and the model that produced it.
    """
    candidates = _gemini_model_candidates()
    if max_models is not None:
        candidates = candidates[:max(1, max_models)]
    for model_index, model in enumerate(candidates):
        # One retry per model limits a two-model request to four provider calls.
        # The prior four attempts per model could hold a web request open for
        # two minutes (30s per request plus backoff), especially when both
        # approved models were overloaded.
        for attempt in range(2):
            started_at = time.monotonic()
            try:
                request = {"model": model, "contents": contents}
                if config is not None:
                    request["config"] = config
                response = client.models.generate_content(**request)
                if require_json:
                    parsed = json.loads(response.text or "{}")
                    if not isinstance(parsed, dict):
                        raise ValueError("structured response must be an object")
                if model_index:
                    logger.info("Gemini fallback model succeeded; model=%s", model)
                return response, model
            except Exception as exc:
                category, status_code = _provider_failure_diagnostic(exc)
                malformed_json = isinstance(exc, (json.JSONDecodeError, ValueError))
                retryable = (status_code in {404, 429, 503, 504}
                             or category in {"quota_or_rate_limited", "quota_exhausted", "rate_limited", "network_connectivity"}
                             or malformed_json)
                if not retryable:
                    raise
                retry_same_model = ((status_code in {503, 504} or category == "network_connectivity")
                                    and retry_transient_errors and attempt == 0)
                retry_malformed_json = malformed_json and attempt == 0
                action = ("retry_same_model" if retry_same_model
                          else "retry_malformed_response" if retry_malformed_json
                          else "try_fallback" if model_index + 1 < len(candidates)
                          else "stop")
                logger.warning(
                    "Gemini generation attempt failed; model=%s attempt=%s category=%s status_code=%s elapsed_ms=%s action=%s",
                    model, attempt + 1, category,
                    status_code if status_code is not None else "unknown",
                    round((time.monotonic() - started_at) * 1000), action,
                )
                # Retry transient provider/network failures once per model.
                # Give the fallback a longer wait to avoid repeating a request
                # immediately during the same overload.
                if retry_same_model:
                    time.sleep(min(2.0 * (2 ** model_index), 8.0))
                    continue
                if retry_malformed_json:
                    time.sleep(0.5)
                    continue
                if model_index + 1 < len(candidates):
                    logger.warning(
                        "Gemini model unavailable for generation; category=%s status_code=%s fallback_model=%s",
                        category, status_code if status_code is not None else "unknown", candidates[model_index + 1],
                    )
                    break
                if category in {"quota_or_rate_limited", "quota_exhausted", "rate_limited"} or status_code == 429:
                    raise GeminiQuotaExhausted(
                        "Gemini rate limits are exhausted for all configured models. Check the Google AI Studio project limits or retry after they reset.",
                        status_code=status_code or 429,
                    ) from exc
                raise
    raise RuntimeError("No configured Gemini model is available.")


def inspect_model_catalog(model_name: str | None = None, service: str = "chat") -> dict:
    """Check model metadata only; catalog visibility cannot prove project generation access."""
    if service not in {"chat", "resume"}:
        raise ValueError("Gemini service must be chat or resume.")
    api_key = {
        "chat": settings.gemini_chat_api_key,
        "resume": settings.gemini_api_key,
    }[service]
    if not api_key:
        env_name = {"chat": "GEMINI_CHAT_API_KEY", "resume": "GEMINI_API_KEY"}[service]
        raise RuntimeError(f"Gemini {service} is not configured. Set {env_name} in backend/.env.")
    requested_model = model_name or settings.gemini_model
    client = None
    try:
        client = _create_client(api_key)
        model = client.models.get(model=requested_model)
        name = str(getattr(model, "name", requested_model)).removeprefix("models/")
        actions = getattr(model, "supported_actions", None)
        return {
            "model": name,
            "catalog_available": True,
            "supports_generate_content": ("generateContent" in actions) if actions is not None else None,
            "project_generation_access": "not_verified_by_read_only_catalog_check",
        }
    except Exception as exc:
        category, status_code = _provider_failure_diagnostic(exc)
        logger.warning(
            "Gemini read-only model check failed; category=%s status_code=%s exception_type=%s",
            category,
            status_code if status_code is not None else "unknown",
            type(exc).__name__,
        )
        raise RuntimeError("Gemini model catalog could not be checked.") from None
    finally:
        if client is not None:
            _close_client(client)
