from __future__ import annotations

VERSION = "20260828_001"
NAME = "add_inquiry_text_index_tasks"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _ensure_column

    # 新任务表由 ORM create_all 创建；迁移负责为线上已存在的同步任务表补齐关联字段。
    await _ensure_column(
        conn,
        "sgo_sync_task",
        "semantic_index_task_id",
        "`semantic_index_task_id` VARCHAR(100) NULL",
    )
    await _ensure_column(
        conn,
        "sgo_sync_task",
        "semantic_index_warning",
        "`semantic_index_warning` TEXT NULL",
    )
