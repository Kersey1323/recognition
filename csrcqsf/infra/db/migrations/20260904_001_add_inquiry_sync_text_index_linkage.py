from __future__ import annotations

from sqlalchemy import text


VERSION = "20260904_001"
NAME = "add_inquiry_sync_text_index_linkage"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _ensure_column

    await _ensure_column(
        conn,
        "sgo_sync_task",
        "semantic_index_triggered",
        "`semantic_index_triggered` TINYINT(1) NOT NULL DEFAULT 0",
    )
    await _ensure_column(
        conn,
        "inquiry_text_index_task",
        "trigger_source",
        "`trigger_source` VARCHAR(30) NOT NULL DEFAULT 'manual'",
    )
    await _ensure_column(
        conn,
        "inquiry_text_index_task",
        "source_sync_task_ids_json",
        "`source_sync_task_ids_json` JSON NULL",
    )

    # 旧任务按已有单值来源回填数组，新接口可以无损展示历史任务链路。
    await conn.execute(
        text(
            """
            UPDATE `inquiry_text_index_task`
            SET `trigger_source` = CASE
                    WHEN `source_sync_task_id` IS NULL THEN 'manual'
                    ELSE 'sgo_inquiry_sync'
                END,
                `source_sync_task_ids_json` = CASE
                    WHEN `source_sync_task_id` IS NULL THEN JSON_ARRAY()
                    ELSE JSON_ARRAY(`source_sync_task_id`)
                END
            WHERE `source_sync_task_ids_json` IS NULL
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE `inquiry_text_index_task`
            MODIFY COLUMN `source_sync_task_ids_json` JSON NOT NULL
            """
        )
    )
    await conn.execute(
        text(
            """
            UPDATE `sgo_sync_task`
            SET `semantic_index_triggered` = 1
            WHERE `semantic_index_task_id` IS NOT NULL
            """
        )
    )
