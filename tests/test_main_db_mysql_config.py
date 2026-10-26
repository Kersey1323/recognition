import importlib
import sys
from pathlib import Path


def _reload_settings(monkeypatch, **env):
    for key in (
        "MAIN_DB_HOST",
        "MAIN_DB_PORT",
        "MAIN_DB_USER",
        "MAIN_DB_PASSWORD",
        "MAIN_DB_DATABASE",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("csrcqsf.core.settings", None)
    return importlib.import_module("csrcqsf.core.settings")


def test_main_db_mysql_dsn_uses_new_env_names(monkeypatch):
    settings = _reload_settings(
        monkeypatch,
        MAIN_DB_HOST="192.168.100.2",
        MAIN_DB_PORT="3307",
        MAIN_DB_USER="root",
        MAIN_DB_PASSWORD="unit-test-db-password",
        MAIN_DB_DATABASE="coronavirusdb",
    )

    assert settings.ai_settings.mysql.url == "192.168.100.2"
    assert settings.ai_settings.mysql.port == "3307"
    assert settings.ai_settings.mysql.user_name == "root"
    assert settings.ai_settings.mysql.password == "unit-test-db-password"
    assert settings.ai_settings.get_mysql_dsn() == (
        "mysql+pymysql://root:unit-test-db-password@192.168.100.2:3307/coronavirusdb"
    )
    assert settings.ai_settings.get_async_mysql_dsn() == (
        "mysql+asyncmy://root:unit-test-db-password@192.168.100.2:3307/coronavirusdb"
    )
    assert settings.ai_settings.get_async_main_db_dsn() == (
        "mysql+asyncmy://root:unit-test-db-password@192.168.100.2:3307/coronavirusdb"
    )
    assert settings.ai_settings.get_pg_dsn() == settings.ai_settings.get_mysql_dsn()
    assert (
        settings.ai_settings.get_async_pg_dsn()
        == settings.ai_settings.get_async_mysql_dsn()
    )


def test_main_db_mysql_config_does_not_fall_back_to_pg_env(monkeypatch):
    settings = _reload_settings(
        monkeypatch,
        PG_HOST="192.168.100.9",
        PG_PORT="3309",
        PG_USER="legacy_user",
        PG_PASSWORD="legacy_pass",
        PG_DATABASE="legacy_db",
    )

    assert settings.ai_settings.mysql.url != "192.168.100.9"


def test_main_db_env_configured_requires_database(monkeypatch):
    settings = _reload_settings(
        monkeypatch,
        MAIN_DB_HOST="10.0.0.8",
        MAIN_DB_PORT="3307",
        MAIN_DB_USER="docker_user",
        MAIN_DB_PASSWORD="docker_password",
    )

    assert settings.main_db_env_configured() is False


def test_main_db_infra_uses_mysql_engine_contract():
    text = Path("csrcqsf/infra/db/main_db.py").read_text(encoding="utf-8")

    assert "get_async_main_db_dsn()" in text
    assert "CREATE SCHEMA IF NOT EXISTS" not in text
    assert "with_schema(schema_name='parts')" not in text
