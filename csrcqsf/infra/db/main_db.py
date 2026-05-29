"""
主业务数据库访问层
职责：MySQL 连接管理、会话管理、建表和兼容补列
注意：此层不包含具体业务逻辑，仅提供数据库基础设施
"""

# NOTE:
# `pg.py` 是历史命名，当前实际承载的是主业务 MySQL 访问层。
# Phase 0 引入 `main_db.py` 作为更准确的推荐导入路径；
# 在后续结构治理阶段完成前，此文件继续保持兼容实现。

from __future__ import annotations

import importlib
import inspect
from datetime import datetime

from bfrcommon.db import default_id
from csrcqsf.core.settings import ai_settings, main_db_database
from sqlalchemy import BIGINT, DateTime, MetaData, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


engine = create_async_engine(
    ai_settings.get_async_main_db_dsn(),
    echo=False,
    future=True,
)

SessionLocal = async_sessionmaker(
    expire_on_commit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    metadata = MetaData()

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, default=default_id)
    created_by: Mapped[int] = mapped_column(BIGINT, default=0)
    updated_by: Mapped[int] = mapped_column(BIGINT, default=0)
    time_created: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=datetime.now,
    )
    time_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        onupdate=datetime.now,
        insert_default=datetime.now,
    )

    def __hash__(self) -> int:
        return self.id

    def __eq__(self, other):
        return self.id == other.id


class PlainBase(DeclarativeBase):
    metadata = MetaData()


MAIN_DB_MODEL_MODULES = (
    "csrcqsf.models.files",
    "csrcqsf.models.item",
    "csrcqsf.models.reconstruction",
    "csrcqsf.models.reconstruction_upload",
    "csrcqsf.models.search_history",
    "csrcqsf.models.sgo",
)


def load_main_db_models() -> None:
    for module_name in MAIN_DB_MODEL_MODULES:
        importlib.import_module(module_name)


def _quote_mysql_identifier(name: str) -> str:
    return f"`{name.replace('`', '``')}`"


def _get_async_main_db_admin_dsn() -> str:
    url = make_url(ai_settings.get_async_main_db_dsn())
    return url.set(database="mysql").render_as_string(hide_password=False)


async def ensure_main_database_exists() -> None:
    database_name = main_db_database.strip()
    if database_name == "":
        return

    bootstrap_engine = create_async_engine(
        _get_async_main_db_admin_dsn(),
        echo=False,
        future=True,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with bootstrap_engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE DATABASE IF NOT EXISTS "
                    f"{_quote_mysql_identifier(database_name)} "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
    finally:
        await bootstrap_engine.dispose()


async def _column_exists(conn, table_name: str, column_name: str) -> bool:
    result = await conn.execute(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {
            "table_name": table_name,
            "column_name": column_name,
        },
    )
    scalar_value = result.scalar()
    if inspect.isawaitable(scalar_value):
        scalar_value = await scalar_value
    return bool(scalar_value)


async def _ensure_column(conn, table_name: str, column_name: str, ddl: str) -> None:
    if await _column_exists(conn, table_name, column_name):
        return
    await conn.execute(text(f"ALTER TABLE `{table_name}` ADD COLUMN {ddl}"))


async def _ensure_item_info_columns(conn) -> None:
    await _ensure_column(conn, "item_info", "weight", "`weight` DECIMAL NULL")
    await _ensure_column(
        conn,
        "item_info",
        "parent_item_id",
        "`parent_item_id` BIGINT NOT NULL DEFAULT 0",
    )
    await conn.execute(
        text(
            """
            UPDATE `item_info`
            SET `parent_item_id` = 0
            WHERE `parent_item_id` IS NULL
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE `item_info`
            MODIFY COLUMN `parent_item_id` BIGINT NOT NULL DEFAULT 0
            """
        )
    )
    await _ensure_column(
        conn,
        "item_info",
        "source_video_path",
        "`source_video_path` VARCHAR(500) NULL",
    )
    await _ensure_column(
        conn,
        "item_info",
        "source_video_filename",
        "`source_video_filename` VARCHAR(255) NULL",
    )
    await _ensure_column(
        conn,
        "item_info",
        "source_video_size",
        "`source_video_size` BIGINT NULL",
    )
    await _ensure_column(
        conn,
        "item_info",
        "source_video_content_type",
        "`source_video_content_type` VARCHAR(100) NULL",
    )
    await _ensure_column(
        conn,
        "item_info",
        "source_video_updated_at",
        "`source_video_updated_at` DATETIME NULL",
    )


async def _ensure_search_history_columns(conn) -> None:
    await _ensure_column(
        conn,
        "search_history",
        "query_text",
        "`query_text` VARCHAR(1000) NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "query_image",
        "`query_image` VARCHAR(1000) NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "query_images_json",
        "`query_images_json` JSON NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "verify_status",
        "`verify_status` VARCHAR(50) NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "verify_remark",
        "`verify_remark` VARCHAR(500) NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "verified_at",
        "`verified_at` DATETIME NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "search_equipment",
        "`search_equipment` VARCHAR(50) NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "ranking_feedback_type",
        "`ranking_feedback_type` VARCHAR(50) NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "selected_item_id",
        "`selected_item_id` BIGINT NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "selected_item_code",
        "`selected_item_code` VARCHAR(200) NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "selected_item_name",
        "`selected_item_name` VARCHAR(200) NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "selected_rank",
        "`selected_rank` INT NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "selected_image_url",
        "`selected_image_url` VARCHAR(1000) NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "correct_item_id",
        "`correct_item_id` BIGINT NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "correct_image_url",
        "`correct_image_url` VARCHAR(1000) NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "correct_rank",
        "`correct_rank` INT NULL",
    )
    await _ensure_column(
        conn,
        "search_history",
        "correct_source",
        "`correct_source` VARCHAR(50) NULL",
    )
    await conn.execute(
        text(
            """
            UPDATE `search_history`
            SET `verify_status` = 'wrong'
            WHERE `verify_status` = 'partial'
            """
        )
    )


async def _ensure_reconstruction_columns(conn) -> None:
    await _ensure_column(
        conn,
        "reconstruction_records",
        "completed_at",
        "`completed_at` DATETIME NULL",
    )
    await _ensure_column(
        conn,
        "reconstruction_records",
        "elapsed_sec",
        "`elapsed_sec` DOUBLE NULL",
    )


async def _ensure_reconstruction_upload_session_columns(conn) -> None:
    await _ensure_column(
        conn,
        "reconstruction_video_upload_session",
        "storage_mode",
        "`storage_mode` VARCHAR(20) NOT NULL DEFAULT 'remote'",
    )
    await _ensure_column(
        conn,
        "reconstruction_video_upload_session",
        "local_status",
        "`local_status` VARCHAR(50) NOT NULL DEFAULT 'initiated'",
    )
    await _ensure_column(
        conn,
        "reconstruction_video_upload_session",
        "remote_status",
        "`remote_status` VARCHAR(50) NOT NULL DEFAULT 'pending'",
    )
    await _ensure_column(
        conn,
        "reconstruction_video_upload_session",
        "local_dir",
        "`local_dir` VARCHAR(700) NULL",
    )
    await _ensure_column(
        conn,
        "reconstruction_video_upload_session",
        "merged_file_path",
        "`merged_file_path` VARCHAR(700) NULL",
    )
    await _ensure_column(
        conn,
        "reconstruction_video_upload_session",
        "remote_upload_id",
        "`remote_upload_id` VARCHAR(200) NULL",
    )
    await _ensure_column(
        conn,
        "reconstruction_video_upload_session",
        "remote_object_name",
        "`remote_object_name` VARCHAR(500) NULL",
    )
    await _ensure_column(
        conn,
        "reconstruction_video_upload_session",
        "remote_video_path",
        "`remote_video_path` VARCHAR(700) NULL",
    )
    await _ensure_column(
        conn,
        "reconstruction_video_upload_session",
        "sync_attempts",
        "`sync_attempts` INT NOT NULL DEFAULT 0",
    )
    await _ensure_column(
        conn,
        "reconstruction_video_upload_session",
        "last_sync_error",
        "`last_sync_error` VARCHAR(1000) NULL",
    )
    await _ensure_column(
        conn,
        "reconstruction_video_upload_session",
        "synced_at",
        "`synced_at` DATETIME NULL",
    )


async def db_migrate():
    """
    主业务库迁移：自动建库、创建所有业务表，并为历史表补齐 MySQL 兼容字段。

    假设：
    - SGO 独立 MySQL 不在本迁移范围内
    """
    await ensure_main_database_exists()
    load_main_db_models()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(PlainBase.metadata.create_all)
        await _ensure_item_info_columns(conn)
        await _ensure_search_history_columns(conn)
        await _ensure_reconstruction_columns(conn)
        await _ensure_reconstruction_upload_session_columns(conn)
