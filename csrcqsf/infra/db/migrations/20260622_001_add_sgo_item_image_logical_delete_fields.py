from __future__ import annotations

VERSION = "20260622_001"
NAME = "add_sgo_item_image_logical_delete_fields"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _ensure_column

    await _ensure_column(
        conn,
        "sgo_item_image_info",
        "is_deleted",
        "`is_deleted` TINYINT NOT NULL DEFAULT 0",
    )
    await _ensure_column(
        conn,
        "sgo_item_image_info",
        "deleted_at",
        "`deleted_at` DATETIME NULL",
    )
    await _ensure_column(
        conn,
        "sgo_item_image_info",
        "delete_reason",
        "`delete_reason` VARCHAR(500) NULL",
    )
