from pathlib import Path

from csrcqsf.models.orm.index_rebuild_task import (
    IndexRebuildTask,
    IndexRebuildTaskStatus,
    classify_startup_recovery,
)


def test_index_rebuild_task_model_contains_persistence_fields():
    columns = set(IndexRebuildTask.__table__.columns.keys())

    assert {
        "id",
        "task_id",
        "root_task_id",
        "retry_from_task_id",
        "task_scope",
        "item_id",
        "item_limit",
        "rebuild_existing",
        "status",
        "progress",
        "total_items",
        "completed_item_count",
        "processed_items",
        "success_count",
        "fail_count",
        "segmented_count",
        "fallback_count",
        "current_item_id",
        "last_completed_item_id",
        "last_completed_item_created_at",
        "estimated_remaining_seconds",
        "heartbeat_at",
        "started_at",
        "completed_at",
        "error_message",
        "cancel_reason",
        "time_created",
        "time_updated",
    }.issubset(columns)
    assert IndexRebuildTask.__table__.columns.task_id.unique is True


def test_index_rebuild_task_model_defines_task_lookup_indexes():
    indexed_columns = {
        tuple(column.name for column in index.columns)
        for index in IndexRebuildTask.__table__.indexes
    }

    assert ("status", "time_created") in indexed_columns
    assert ("task_scope", "status") in indexed_columns
    assert ("item_id", "time_created") in indexed_columns
    assert ("root_task_id", "time_created") in indexed_columns


def test_recovery_marks_unfinished_active_task_interrupted():
    state = classify_startup_recovery(
        status=IndexRebuildTaskStatus.RUNNING,
        total_items=10,
        completed_item_count=4,
    )

    assert state == IndexRebuildTaskStatus.INTERRUPTED


def test_recovery_repairs_fully_checkpointed_task_to_success():
    state = classify_startup_recovery(
        status=IndexRebuildTaskStatus.RUNNING,
        total_items=10,
        completed_item_count=10,
    )

    assert state == IndexRebuildTaskStatus.SUCCESS


def test_recovery_keeps_terminal_task_unchanged():
    state = classify_startup_recovery(
        status=IndexRebuildTaskStatus.FAILED,
        total_items=10,
        completed_item_count=4,
    )

    assert state == IndexRebuildTaskStatus.FAILED


def test_startup_recovers_index_tasks_after_database_migration():
    source = Path("csrcqsf/core/app.py").read_text(encoding="utf-8")
    lifespan_source = source[source.index("async def lifespan") : source.index("# 创建FastAPI应用实例")]

    assert lifespan_source.index('"主业务数据库迁移"') < lifespan_source.index(
        '"索引重建任务状态恢复"'
    )
