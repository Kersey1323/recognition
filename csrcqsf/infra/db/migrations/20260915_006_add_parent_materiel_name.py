from __future__ import annotations


VERSION = "20260915_006"
NAME = "add_parent_materiel_name"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _ensure_column

    await _ensure_column(
        conn,
        "item_hierarchy_relation",
        "parent_materiel_name",
        "`parent_materiel_name` VARCHAR(255) NULL",
    )
