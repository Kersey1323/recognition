from __future__ import annotations


VERSION = "20260915_003"
NAME = "add_parts_metadata_sync_counts"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _ensure_column

    columns = (
        ("updated_metadata_count", "配件规格/材质更新数"),
        ("synced_supplier_count", "供应商关系新增或更新数"),
        ("deleted_supplier_count", "供应商关系清理数"),
        ("unmatched_supplier_count", "尚未关联配件的供应商关系数"),
    )
    for column_name, _description in columns:
        await _ensure_column(
            conn,
            "sgo_sync_task",
            column_name,
            f"`{column_name}` INT NOT NULL DEFAULT 0",
        )
