import asyncio
import importlib
from unittest.mock import ANY, AsyncMock, patch

from csrcqsf.models.orm.viewer360_task import (
    Viewer360TaskStatus,
    classify_viewer360_startup_recovery,
)


class FakeConn:
    def __init__(self):
        self.sql = []

    async def execute(self, statement, params=None):
        self.sql.append(str(statement))


def test_viewer360_migration_explicitly_creates_all_tables():
    migration = importlib.import_module(
        "csrcqsf.infra.db.migrations.20260902_001_add_viewer360_tasks"
    )
    conn = FakeConn()

    asyncio.run(migration.upgrade(conn))

    ddl = "\n".join(conn.sql).lower()
    assert "create table if not exists viewer360_task" in ddl
    assert "create table if not exists item_viewer360_current" in ddl
    assert "create table if not exists viewer360_task_failure" in ddl
    assert "retry_rows_json" in ddl
    assert "retry_reason" in ddl
    assert "pipeline_metadata_json" in ddl
    assert "manifest_object" in ddl


def test_viewer360_retry_reason_compatibility_migration_adds_column():
    migration = importlib.import_module(
        "csrcqsf.infra.db.migrations.20260902_002_add_viewer360_retry_reason"
    )
    ensure_column = AsyncMock()

    with patch(
        "csrcqsf.infra.db.main_db._ensure_column",
        ensure_column,
    ):
        asyncio.run(migration.upgrade(object()))

    ensure_column.assert_awaited_once_with(
        ANY,
        "viewer360_task",
        "retry_reason",
        "`retry_reason` VARCHAR(500) NULL",
    )


def test_active_viewer360_tasks_become_interrupted_after_restart():
    for status in ("pending", "running", "cancelling"):
        assert classify_viewer360_startup_recovery(status) == Viewer360TaskStatus.INTERRUPTED


def test_terminal_viewer360_tasks_keep_their_status_after_restart():
    for status in ("success", "failed", "cancelled", "interrupted"):
        assert classify_viewer360_startup_recovery(status).value == status
