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
        "PG_HOST",
        "PG_PORT",
        "PG_USER",
        "PG_PASSWORD",
        "PG_DATABASE",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("csrcqsf.settings", None)
    return importlib.import_module("csrcqsf.settings")


def test_main_db_mysql_dsn_uses_new_env_names(monkeypatch):
    settings = _reload_settings(
        monkeypatch,
        MAIN_DB_HOST="192.168.100.2",
        MAIN_DB_PORT="3307",
        MAIN_DB_USER="root",
        MAIN_DB_PASSWORD="REMOVED_CREDENTIAL",
        MAIN_DB_DATABASE="coronavirusdb",
    )

    assert settings.ai_settings.get_async_main_db_dsn() == (
        "mysql+asyncmy://root:REMOVED_CREDENTIAL@192.168.100.2:3307/coronavirusdb"
    )


def test_main_db_mysql_dsn_falls_back_to_pg_env_compat(monkeypatch):
    settings = _reload_settings(
        monkeypatch,
        PG_HOST="192.168.100.9",
        PG_PORT="3309",
        PG_USER="legacy_user",
        PG_PASSWORD="legacy_pass",
        PG_DATABASE="legacy_db",
    )

    assert settings.ai_settings.get_async_main_db_dsn() == (
        "mysql+asyncmy://legacy_user:legacy_pass@192.168.100.9:3309/legacy_db"
    )


def test_main_db_infra_uses_mysql_engine_contract():
    text = Path("csrcqsf/data/pg.py").read_text(encoding="utf-8")

    assert "get_async_main_db_dsn()" in text
    assert "CREATE SCHEMA IF NOT EXISTS" not in text
    assert "with_schema(schema_name='parts')" not in text
