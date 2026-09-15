from __future__ import annotations


VERSION = "20260915_004"
NAME = "add_sync_failure_item_metadata"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _ensure_column

    # 失败记录同时保留内部 ID 与甲方可识别的配件编码、名称，便于任务详情定位源数据。
    await _ensure_column(
        conn,
        "sgo_sync_task_failure",
        "item_code",
        "`item_code` VARCHAR(100) NULL",
    )
    await _ensure_column(
        conn,
        "sgo_sync_task_failure",
        "item_name",
        "`item_name` VARCHAR(255) NULL",
    )
