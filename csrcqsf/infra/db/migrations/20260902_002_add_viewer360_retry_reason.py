from __future__ import annotations


VERSION = "20260902_002"
NAME = "add_viewer360_retry_reason"


async def upgrade(conn) -> None:
    """为已执行首版 Viewer360 迁移的环境补充 Retry 原因字段。"""
    from csrcqsf.infra.db.main_db import _ensure_column

    await _ensure_column(
        conn,
        "viewer360_task",
        "retry_reason",
        "`retry_reason` VARCHAR(500) NULL",
    )
