from sqlalchemy.dialects import mysql

from csrcqsf.modules.railway_parts.repositories.auto_index_repository import (
    build_auto_index_candidate_stmt,
)


def _compile_sql(stmt) -> str:
    return str(
        stmt.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_candidate_query_selects_unindexed_active_images_from_all_sources():
    sql = _compile_sql(
        build_auto_index_candidate_stmt(limit=16, excluded_item_ids=(101, 102))
    )

    assert "sgo_item_image_info.image_source" not in sql
    assert "sgo_item_image_info.is_indexed != 1" in sql
    assert "sgo_item_image_info.is_deleted = 0" in sql
    assert "sgo_item_image_info.item_id NOT IN (101, 102)" in sql
    assert "GROUP BY sgo_item_image_info.item_id" in sql
    assert "LIMIT 16" in sql


def test_candidate_query_blocks_terminal_attempts_but_retries_interrupted_tasks():
    sql = _compile_sql(build_auto_index_candidate_stmt(limit=4))

    assert "index_rebuild_task.task_scope = 'single'" in sql
    assert "index_rebuild_task.item_id = sgo_item_image_info.item_id" in sql
    assert "index_rebuild_task.time_created >= sgo_item_image_info.time_created" in sql
    assert "success" in sql
    assert "failed" in sql
    assert "cancelled" in sql
    assert "interrupted" not in sql
