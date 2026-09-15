from __future__ import annotations

from sqlalchemy import text


VERSION = "20260915_005"
NAME = "add_item_hierarchy_relation"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _ensure_column

    # SGO 层级包含虚拟节点、多父节点和车型上下文，不能压缩进 item_info.parent_item_id。
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS `item_hierarchy_relation` (
              `id` BIGINT NOT NULL,
              `created_by` BIGINT NOT NULL DEFAULT 0,
              `updated_by` BIGINT NOT NULL DEFAULT 0,
              `time_created` DATETIME NOT NULL,
              `time_updated` DATETIME NULL,
              `source_relation_id` VARCHAR(64) NOT NULL,
              `item_id` BIGINT NULL,
              `parent_item_id` BIGINT NULL,
              `materiel_code` VARCHAR(100) NULL,
              `materiel_name` VARCHAR(255) NULL,
              `parent_materiel_code` VARCHAR(100) NULL,
              `figure_number` VARCHAR(100) NULL,
              `vehicle_id` VARCHAR(64) NULL,
              `vehicle_batch` VARCHAR(64) NULL,
              `vehicle_name` VARCHAR(100) NULL,
              `vehicle_resolved` TINYINT(1) NOT NULL DEFAULT 0,
              `train_type_group` VARCHAR(64) NULL,
              `column_id` VARCHAR(64) NULL,
              `serial_number` VARCHAR(64) NULL,
              `tenant_id` VARCHAR(64) NULL,
              `is_valid` TINYINT(1) NOT NULL DEFAULT 1,
              `invalid_reason` VARCHAR(255) NULL,
              `source_hash` VARCHAR(64) NOT NULL,
              PRIMARY KEY (`id`),
              UNIQUE KEY `uq_item_hierarchy_source_id` (`source_relation_id`),
              KEY `ix_item_hierarchy_item_id` (`item_id`),
              KEY `ix_item_hierarchy_parent_item_id` (`parent_item_id`),
              KEY `ix_item_hierarchy_materiel_code` (`materiel_code`),
              KEY `ix_item_hierarchy_parent_code` (`parent_materiel_code`),
              KEY `ix_item_hierarchy_vehicle_batch` (`vehicle_batch`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
    )

    task_columns = (
        ("hierarchy_total_count", "层级源记录总数"),
        ("synced_hierarchy_count", "层级关系新增或更新数"),
        ("deleted_hierarchy_count", "层级关系清理数"),
        ("unresolved_vehicle_count", "车型名称未映射关系数"),
        ("invalid_hierarchy_count", "异常层级关系数"),
    )
    for column_name, _description in task_columns:
        await _ensure_column(
            conn,
            "sgo_sync_task",
            column_name,
            f"`{column_name}` INT NOT NULL DEFAULT 0",
        )
