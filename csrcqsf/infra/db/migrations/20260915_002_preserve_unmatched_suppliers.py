from __future__ import annotations

from sqlalchemy import text


VERSION = "20260915_002"
NAME = "preserve_unmatched_suppliers"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _ensure_column

    await _ensure_column(
        conn,
        "item_supplier_info",
        "source_masterplate_id",
        "`source_masterplate_id` VARCHAR(64) NOT NULL DEFAULT ''",
    )
    # 源供应商快照可能早于配件进入本地业务库，先保留关系，后续同步自动补 item_id。
    await conn.execute(
        text(
            "ALTER TABLE `item_supplier_info` "
            "MODIFY COLUMN `item_id` BIGINT NULL"
        )
    )
