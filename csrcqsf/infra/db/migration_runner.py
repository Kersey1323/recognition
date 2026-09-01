from __future__ import annotations

import hashlib
import importlib
import inspect
import pkgutil
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy import text


MigrationFunc = Callable[[object], Awaitable[None]]


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    checksum: str
    upgrade: MigrationFunc


async def ensure_schema_migrations_table(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version VARCHAR(100) PRIMARY KEY,
              name VARCHAR(200) NOT NULL,
              checksum VARCHAR(64) NOT NULL,
              applied_at DATETIME NOT NULL,
              execution_ms INT NOT NULL DEFAULT 0
            )
            """
        )
    )


def _checksum_module(module) -> str:
    source = inspect.getsource(module)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def discover_migrations() -> list[Migration]:
    """按版本号发现迁移模块，并以源码摘要固定每个已发布版本。"""
    package = importlib.import_module("csrcqsf.infra.db.migrations")
    migrations: list[Migration] = []
    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.ispkg or module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        migrations.append(
            Migration(
                version=getattr(module, "VERSION"),
                name=getattr(module, "NAME"),
                checksum=_checksum_module(module),
                upgrade=getattr(module, "upgrade"),
            )
        )
    return sorted(migrations, key=lambda item: item.version)


async def _load_applied_migrations(conn) -> dict[str, str]:
    result = await conn.execute(text("SELECT version, checksum FROM schema_migrations"))
    rows = result.mappings().all()
    return {row["version"]: row["checksum"] for row in rows}


async def _record_migration(conn, migration: Migration, execution_ms: int) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at, execution_ms)
            VALUES (:version, :name, :checksum, :applied_at, :execution_ms)
            """
        ),
        {
            "version": migration.version,
            "name": migration.name,
            "checksum": migration.checksum,
            "applied_at": datetime.now(),
            "execution_ms": execution_ms,
        },
    )


async def run_pending_migrations(conn) -> None:
    """顺序执行未登记的迁移，并拒绝运行被事后修改的历史迁移。"""
    await ensure_schema_migrations_table(conn)
    applied_migrations = await _load_applied_migrations(conn)

    for migration in sorted(discover_migrations(), key=lambda item: item.version):
        applied_checksum = applied_migrations.get(migration.version)
        if applied_checksum is not None:
            # 历史迁移必须不可变，否则不同部署环境可能拥有同版本、不同结构的数据库。
            if applied_checksum != migration.checksum:
                raise RuntimeError(
                    "已执行迁移脚本内容发生变化: "
                    f"version={migration.version}, name={migration.name}"
                )
            continue
        started = time.monotonic()
        await migration.upgrade(conn)
        execution_ms = int((time.monotonic() - started) * 1000)
        await _record_migration(conn, migration, execution_ms)
