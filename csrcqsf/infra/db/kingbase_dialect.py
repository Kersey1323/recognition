"""KingbaseES 的 SQLAlchemy asyncpg 方言适配。"""

from sqlalchemy.dialects import registry
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg


class KingbaseAsyncpgDialect(PGDialect_asyncpg):
    name = "kingbase"
    supports_statement_cache = True

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
