from sqlalchemy.engine import make_url

from app.core.config import Settings


def test_postgres_environment_settings_build_escaped_psycopg_url():
    secret = "pw:/@ with spaces"
    configured = Settings(
        _env_file=None,
        database_url=None,
        postgres_host="127.0.0.1",
        postgres_port=5432,
        postgres_db="campusai",
        postgres_user="campus user",
        postgres_password=secret,
    )

    parsed = make_url(configured.database_url)
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.host == "127.0.0.1"
    assert parsed.port == 5432
    assert parsed.database == "campusai"
    assert parsed.username == "campus user"
    assert parsed.password == secret


def test_explicit_database_url_overrides_postgres_components():
    configured = Settings(
        _env_file=None,
        database_url="sqlite:///./isolated-test.db",
        postgres_host="127.0.0.1",
        postgres_db="campusai",
        postgres_user="campusai_user",
        postgres_password="test-only",
    )
    assert configured.database_url == "sqlite:///./isolated-test.db"


def test_sqlite_remains_default_without_complete_postgres_credentials():
    configured = Settings(_env_file=None)
    assert configured.database_url == "sqlite:///./campusai.db"


def test_postgres_credentials_are_loaded_from_environment_without_repr_leak(monkeypatch):
    secret = "environment-only-password"
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "campusai")
    monkeypatch.setenv("POSTGRES_USER", "campusai_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", secret)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    configured = Settings(_env_file=None)

    assert make_url(configured.database_url).drivername == "postgresql+psycopg"
    assert make_url(configured.database_url).password == secret
    assert secret not in repr(configured)
