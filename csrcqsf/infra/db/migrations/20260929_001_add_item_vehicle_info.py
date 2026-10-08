from __future__ import annotations


VERSION = "20260929_001"
NAME = "add_item_vehicle_info"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _ensure_column

    await _ensure_column(conn, "item_info", "vehicle_info", "`vehicle_info` JSON NULL")
