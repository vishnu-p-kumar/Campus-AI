from fastapi.testclient import TestClient
from app.main import app
from app.core.config import Settings
from app.main import validate_production_configuration
from app.upload_scan import ScannerUnavailable

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_production_configuration_rejects_insecure_defaults():
    config = Settings(
        environment="production", jwt_secret_key="s" * 48,
        database_url="postgresql+psycopg://campusai:secret@db.example/campusai",
        cors_origins="https://campus.example.edu", password_reset_url="https://campus.example.edu/reset-password",
        upload_scan_required=True, clamav_host="clamav.internal",
        qdrant_url="https://qdrant.example", qdrant_api_key="qdrant-test-key",
    )
    validate_production_configuration(config)

    invalid_values = [
        {"database_url": "sqlite:///./campusai.db"},
        {"cors_origins": "*"},
        {"cors_origins": "http://campus.example.edu"},
        {"cors_origins": "https://campus.example.edu/admin"},
        {"password_reset_url": "http://campus.example.edu/reset-password"},
        {"upload_scan_required": False},
        {"clamav_host": None},
    ]
    for overrides in invalid_values:
        candidate = config.model_copy(update=overrides)
        try:
            validate_production_configuration(candidate)
        except RuntimeError:
            continue
        raise AssertionError(f"Production config accepted unsafe values: {overrides}")



def test_free_production_configuration_allows_bm25_and_disables_uploads():
    config = Settings(
        environment="production", jwt_secret_key="s" * 48,
        database_url="postgresql+psycopg://campusai:secret@db.example/campusai",
        cors_origins="https://campus.example.edu",
        password_reset_url="https://campus.example.edu/reset-password",
        file_uploads_enabled=False, upload_scan_required=False, clamav_host=None,
        qdrant_url=None, qdrant_api_key=None,
    )
    validate_production_configuration(config)



def test_development_configuration_keeps_local_defaults():
    config = Settings(_env_file=None)
    validate_production_configuration(config)
    assert config.allowed_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_readiness_reports_optional_vector_and_scanner_services(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "qdrant_url", None)
    monkeypatch.setattr(settings, "clamav_host", None)
    monkeypatch.setattr(settings, "upload_scan_required", False)
    monkeypatch.setattr(settings, "file_uploads_enabled", False)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "connected",
        "vector_store": "not_configured",
        "file_uploads": "disabled",
        "upload_scanner": "not_required",
    }


def test_readiness_fails_when_configured_qdrant_is_unreachable(client, monkeypatch):
    from app.ai import retrieval
    from app.core.config import settings

    monkeypatch.setattr(settings, "qdrant_url", "https://qdrant.example")
    monkeypatch.setattr(retrieval, "qdrant_client", lambda: type("OfflineClient", (), {
        "get_collections": lambda self: (_ for _ in ()).throw(ConnectionError("private network details"))
    })())
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["detail"]["vector_store"] == "unavailable"
    assert "private network details" not in response.text


def test_readiness_fails_when_required_scanner_is_unavailable(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "qdrant_url", None)
    monkeypatch.setattr(settings, "clamav_host", "clamav.internal")
    monkeypatch.setattr(settings, "upload_scan_required", True)
    monkeypatch.setattr("app.main.check_scanner", lambda: (_ for _ in ()).throw(ScannerUnavailable("private scanner detail")))
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["detail"]["upload_scanner"] == "unavailable"
    assert "private scanner detail" not in response.text
