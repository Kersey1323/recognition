"""KingbaseES 的 SQLAlchemy asyncpg 方言适配。"""

import re

import asyncpg
from sqlalchemy.dialects import registry
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg


def _patch_asyncpg_introspection_query(query: str) -> str:
    """统一 Kingbase 递归类型查询中的 depth 类型。"""
    query = re.sub(
        r"\b0\s+AS\s+depth\b",
        "CAST(0 AS BIGINT) AS depth",
        query,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"\bti\.attrnames\s*,\s*0\b",
        "ti.attrnames, CAST(0 AS BIGINT)",
        query,
        flags=re.IGNORECASE,
    )


class KingbaseAsyncpgConnection(asyncpg.Connection):
    """为 Kingbase 修正 asyncpg 内置类型探测 SQL。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Kingbase 会将递归项 depth + 1 推导为 BIGINT，锚点也必须显式使用 BIGINT。
        self._intro_query = _patch_asyncpg_introspection_query(self._intro_query)


class KingbaseAsyncpgDialect(PGDialect_asyncpg):
    name = "kingbase"
    supports_statement_cache = True

    def create_connect_args(self, url):
        args, kwargs = super().create_connect_args(url)
        kwargs["connection_class"] = KingbaseAsyncpgConnection
        return args, kwargs

    def _get_server_version_info(self, connection) -> tuple[int, ...]:
        # Kingbase 的 version() 返回产品版本号，SQLAlchemy 无法按 PostgreSQL 格式解析。
        version = str(connection.exec_driver_sql("SHOW server_version").scalar())
        try:
            return tuple(int(part) for part in version.split("."))
        except ValueError as exc:
            raise AssertionError(f"无法解析 Kingbase server_version: {version}") from exc


def register_kingbase_dialect() -> None:
    registry.register(
        "kingbase.asyncpg",
        "csrcqsf.infra.db.kingbase_dialect",
        "KingbaseAsyncpgDialect",
    )
