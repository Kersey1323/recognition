import importlib
import asyncio
import sys
from unittest.mock import AsyncMock, patch

import dotenv
import pytest


SGO_ENV_KEYS = (
    "SGO_DATABASE_TYPE",
    "SGO_MYSQL_HOST",
    "SGO_MYSQL_PORT",
    "SGO_MYSQL_USER",
    "SGO_MYSQL_PASSWORD",
    "SGO_MYSQL_DATABASE",
    "SGO_KINGBASE_HOST",
    "SGO_KINGBASE_PORT",
    "SGO_KINGBASE_USER",
    "SGO_KINGBASE_PASSWORD",
    "SGO_KINGBASE_DATABASE",
)


def _reload_settings(monkeypatch, **env):
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    for key in SGO_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("csrcqsf.core.settings", None)
    return importlib.import_module("csrcqsf.core.settings")


def test_sgo_database_defaults_to_legacy_mysql(monkeypatch):
    settings = _reload_settings(
        monkeypatch,
        SGO_MYSQL_HOST="10.0.0.12",
        SGO_MYSQL_PORT="3307",
        SGO_MYSQL_USER="sgo_user",
        SGO_MYSQL_PASSWORD="mysql@password",
        SGO_MYSQL_DATABASE="sgo_db",
    )

    assert settings.sgo_database_type == "mysql"
    assert settings.sgo_env_configured() is True
    assert settings.ai_settings.sgo_host == "10.0.0.12"
    assert settings.ai_settings.sgo_port == "3307"
    assert settings.sgo_database_name == "sgo_db"
    assert settings.ai_settings.get_sgo_dsn() == (
        "mysql+asyncmy://sgo_user:mysql%40password@10.0.0.12:3307/sgo_db"
    )


def test_sgo_database_switches_to_kingbase(monkeypatch):
    settings = _reload_settings(
        monkeypatch,
        SGO_DATABASE_TYPE="kingbase",
        SGO_KINGBASE_HOST="127.0.0.1",
        SGO_KINGBASE_PORT="54321",
        SGO_KINGBASE_USER="system",
        SGO_KINGBASE_PASSWORD="kingbase@password",
        SGO_KINGBASE_DATABASE="mdpdb",
    )

    assert settings.sgo_database_type == "kingbase"
    assert settings.sgo_env_configured() is True
    assert settings.ai_settings.sgo_host == "127.0.0.1"
    assert settings.ai_settings.sgo_port == "54321"
    assert settings.sgo_database_name == "mdpdb"
    assert settings.ai_settings.get_sgo_dsn() == (
        "kingbase+asyncpg://system:kingbase%40password@127.0.0.1:54321/mdpdb"
    )


def test_sgo_database_rejects_unknown_type(monkeypatch):
    with pytest.raises(ValueError, match="SGO_DATABASE_TYPE"):
        _reload_settings(monkeypatch, SGO_DATABASE_TYPE="oracle")


def test_kingbase_dialect_reads_postgresql_compatible_server_version():
    from csrcqsf.infra.db.kingbase_dialect import KingbaseAsyncpgDialect

    class Result:
        @staticmethod
        def scalar():
            return "12.1"

    class Connection:
        @staticmethod
        def exec_driver_sql(statement):
            assert statement == "SHOW server_version"
            return Result()

    dialect = KingbaseAsyncpgDialect()

    assert dialect._get_server_version_info(Connection()) == (12, 1)


def test_kingbase_introspection_casts_recursive_depth_anchors_to_bigint():
    from csrcqsf.infra.db.kingbase_dialect import _patch_asyncpg_introspection_query

    query = """
        WITH RECURSIVE typebases(oid, depth) AS (
            SELECT t2.typbasetype AS oid, 0 AS depth
            UNION ALL
            SELECT t2.typbasetype AS oid, tb.depth + 1 AS depth
        ),
        typeinfo_tree(attrnames, depth) AS (
            SELECT ti.attrnames, 0
            UNION ALL
            SELECT ti.attrnames, tt.depth + 1
        )
    """

    patched = _patch_asyncpg_introspection_query(query)

    assert "CAST(0 AS BIGINT) AS depth" in patched
    assert "SELECT ti.attrnames, CAST(0 AS BIGINT)" in patched


def test_kingbase_dialect_uses_patched_asyncpg_connection():
    from sqlalchemy.engine import make_url

    from csrcqsf.infra.db.kingbase_dialect import (
        KingbaseAsyncpgConnection,
        KingbaseAsyncpgDialect,
    )

    dialect = KingbaseAsyncpgDialect()
    _, connect_args = dialect.create_connect_args(
        make_url("kingbase+asyncpg://system:password@127.0.0.1:54321/mdpdb")
    )

    assert connect_args["connection_class"] is KingbaseAsyncpgConnection


def test_inquiry_list_casts_submission_date_to_driver_safe_string():
    from csrcqsf.infra.db.kingbase_dialect import KingbaseAsyncpgDialect
    from csrcqsf.models.orm.sgo_external import SgoCodeInquiry

    class EmptyRows:
        @staticmethod
        def all():
            return []

    class Session:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return EmptyRows()

    session = Session()
    with patch(
        "csrcqsf.models.orm.sgo_external.async_get_count",
        AsyncMock(return_value=0),
    ):
        result = asyncio.run(
            SgoCodeInquiry.list_code_inquiry(
                session,
                page=1,
                per_page=10,
                status="FINISH",
            )
        )

    assert result.total == 0
    compiled = str(
        session.statement.compile(
            dialect=KingbaseAsyncpgDialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "CAST(sgo_code_inquiry.submission_date AS VARCHAR) AS submission_date" in compiled
