from __future__ import annotations

from sqlalchemy import text


VERSION = "20260915_001"
NAME = "add_item_supplier_metadata"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _ensure_column

    await _ensure_column(
        conn,
        "item_info",
        "parts_model",
        "`parts_model` VARCHAR(255) NULL",
    )
    await _ensure_column(
        conn,
        "item_info",
        "material_quality",
        "`material_quality` VARCHAR(255) NULL",
    )

    # 供应商与配件是一对多关系，独立表可保留供应商侧型号、制造商及上下架状态。
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS `item_supplier_info` (
              `id` BIGINT NOT NULL,
              `created_by` BIGINT NOT NULL DEFAULT 0,
              `updated_by` BIGINT NOT NULL DEFAULT 0,
              `time_created` DATETIME NOT NULL,
              `time_updated` DATETIME NULL,
              `source_supplier_id` VARCHAR(64) NOT NULL,
              `item_id` BIGINT NOT NULL,
              `supplier_code` VARCHAR(64) NULL,
              `supplier_name` VARCHAR(255) NULL,
              `supplier_item_code` VARCHAR(100) NULL,
              `supplier_item_name` VARCHAR(255) NULL,
              `supplier_parts_model` VARCHAR(255) NULL,
              `model_number` VARCHAR(255) NULL,
              `manufacturer` VARCHAR(255) NULL,
              `current_status` VARCHAR(50) NULL,
              `enable_status` VARCHAR(50) NULL,
              PRIMARY KEY (`id`),
              UNIQUE KEY `uq_item_supplier_source_id` (`source_supplier_id`),
              KEY `ix_item_supplier_item_id` (`item_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
    )
