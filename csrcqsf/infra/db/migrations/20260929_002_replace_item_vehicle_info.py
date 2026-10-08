from __future__ import annotations

from sqlalchemy import text


VERSION = "20260929_002"
NAME = "replace_item_vehicle_info"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _column_exists, _ensure_column

    await _ensure_column(conn, "item_info", "vehicle_batch", "`vehicle_batch` TEXT NULL")
    if await _column_exists(conn, "item_info", "vehicle_info"):
        await conn.execute(text("ALTER TABLE `item_info` DROP COLUMN `vehicle_info`"))
