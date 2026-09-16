from __future__ import annotations


VERSION = "20260915_009"
NAME = "add_item_drawing_number"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _ensure_column

    await _ensure_column(
        conn,
        "item_info",
        "drawing_number",
        "`drawing_number` VARCHAR(255) NULL",
    )
