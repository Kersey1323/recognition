import asyncio
from types import SimpleNamespace
from unittest.mock import patch


def test_sgo_sync_startup_recovery_classification():
    from csrcqsf.models.orm.sgo_sync_task import classify_sgo_sync_startup_recovery

    for status in ("pending", "running", "cancelling"):
        assert classify_sgo_sync_startup_recovery(status) == "interrupted"
    for status in ("success", "failed", "cancelled", "interrupted"):
        assert classify_sgo_sync_startup_recovery(status) == status


def test_sgo_sync_models_define_persistent_task_and_failure_contracts():
    from csrcqsf.models.orm.sgo_sync_task import SgoSyncTask, SgoSyncTaskFailure

    task_columns = set(SgoSyncTask.__table__.columns.keys())
    assert {
        "task_id",
        "root_task_id",
        "retry_from_task_id",
        "task_type",
        "task_params_json",
        "status",
        "progress",
        "total_items",
        "processed_items",
        "success_count",
        "fail_count",
        "created_count",
        "skipped_count",
        "synced_image_count",
        "current_item_id",
        "estimated_remaining_seconds",
        "heartbeat_at",
        "started_at",
        "completed_at",
        "error_message",
        "cancel_reason",
        "semantic_index_task_id",
        "semantic_index_triggered",
        "semantic_index_warning",
    }.issubset(task_columns)
    assert {
        "task_id",
        "item_id",
        "stage",
        "error_type",
        "error_message",
    }.issubset(set(SgoSyncTaskFailure.__table__.columns.keys()))


def test_sgo_sync_startup_recovery_updates_active_records():
    from csrcqsf.models.orm.sgo_sync_task import SgoSyncTask

    records = [
        SimpleNamespace(
            status="running",
            current_item_id="101",
            completed_at=None,
            heartbeat_at=None,
            error_message=None,
            estimated_remaining_seconds=10,
        ),
        SimpleNamespace(
            status="success",
            current_item_id=None,
            completed_at=None,
            heartbeat_at=None,
            error_message=None,
            estimated_remaining_seconds=0,
        ),
    ]

    class Session:
        flushed = False

        async def scalars(self, _statement):
            return records

        async def flush(self):
            self.flushed = True

    session = Session()
    result = asyncio.run(SgoSyncTask.recover_active_tasks(session))

    assert result == {"interrupted": 1}
    assert records[0].status == "interrupted"
    assert records[0].current_item_id is None
    assert "服务重启" in records[0].error_message
    assert records[1].status == "success"
    assert session.flushed is True


def test_main_db_loads_sgo_sync_task_models():
    from csrcqsf.infra.db.main_db import MAIN_DB_MODEL_MODULES

    assert "csrcqsf.models.orm.sgo_sync_task" in MAIN_DB_MODEL_MODULES


def test_sgo_sync_repository_appends_failure_rows_in_one_transaction():
    from csrcqsf.modules.sgo import sync_task_repository as repository_module

    class Session:
        def __init__(self):
            self.records = []
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def add_all(self, records):
            self.records.extend(records)

        async def commit(self):
            self.committed = True

    session = Session()
    failures = [
        {
            "item_id": "101",
            "stage": "sgo_download",
            "error_type": "TimeoutError",
            "error_message": "timeout",
        }
    ]
    with patch.object(repository_module, "SessionLocal", return_value=session):
        asyncio.run(
            repository_module.SgoSyncTaskRepository().append_failures(
                "task-1",
                failures,
            )
        )

    assert session.committed is True
    assert len(session.records) == 1
    assert session.records[0].task_id == "task-1"
    assert session.records[0].item_id == "101"
