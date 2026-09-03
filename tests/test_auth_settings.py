import pytest

from csrcqsf.core.settings import load_auth_settings


def _clear_auth_env(monkeypatch):
    for name in (
        "APP_ENV",
        "AUTH_ENABLED",
        "AUTH_PROVIDER",
        "AUTH_MOCK_TOKEN",
        "AUTH_DOCS_PUBLIC",
        "AUTH_ALLOWED_ORIGINS",
        "AUTH_REDIS_URL",
        "SGO_SSO_AUTH_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_development_can_disable_authentication(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_ENABLED", "false")

    settings = load_auth_settings()

    assert settings.enabled is False
    assert settings.allowed_origins == ("*",)


def test_development_mock_provider_requires_configured_token(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_PROVIDER", "mock")

    with pytest.raises(ValueError, match="AUTH_MOCK_TOKEN"):
        load_auth_settings()

    monkeypatch.setenv("AUTH_MOCK_TOKEN", "recognition-dev-token")
    assert load_auth_settings().provider == "mock"


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("AUTH_ENABLED", "false", "AUTH_ENABLED"),
        ("AUTH_PROVIDER", "mock", "AUTH_PROVIDER"),
        ("AUTH_DOCS_PUBLIC", "true", "AUTH_DOCS_PUBLIC"),
        ("AUTH_ALLOWED_ORIGINS", "*", "AUTH_ALLOWED_ORIGINS"),
        ("AUTH_REDIS_URL", "", "AUTH_REDIS_URL"),
        ("SGO_SSO_AUTH_URL", "", "SGO_SSO_AUTH_URL"),
    ],
)
def test_production_rejects_unsafe_auth_configuration(
    monkeypatch,
    name,
    value,
    message,
):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_PROVIDER", "sgo")
    monkeypatch.setenv("AUTH_DOCS_PUBLIC", "false")
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "https://recognition.example.com")
    monkeypatch.setenv("AUTH_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("SGO_SSO_AUTH_URL", "https://sgo.example.com/uc/sso/auth")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        load_auth_settings()


def test_production_accepts_explicit_sgo_configuration(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_PROVIDER", "sgo")
    monkeypatch.setenv("AUTH_DOCS_PUBLIC", "false")
    monkeypatch.setenv(
        "AUTH_ALLOWED_ORIGINS",
        "https://recognition.example.com,https://sgo.example.com",
    )
    monkeypatch.setenv("AUTH_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("SGO_SSO_AUTH_URL", "https://sgo.example.com/uc/sso/auth")

    settings = load_auth_settings()

    assert settings.app_env == "production"
    assert settings.provider == "sgo"
    assert settings.allowed_origins == (
        "https://recognition.example.com",
        "https://sgo.example.com",
    )
