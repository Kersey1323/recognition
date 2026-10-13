from __future__ import annotations

VERSION = "20261013_001"
NAME = "add_item_stock_locations"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _ensure_column

    for name in ("LGORT", "LGORTD", "GRARD"):
        await _ensure_column(conn, "item_info", name, f"`{name}` TEXT NULL")
    await _ensure_column(conn, "item_info", "stock_locations", "`stock_locations` JSON NULL")
