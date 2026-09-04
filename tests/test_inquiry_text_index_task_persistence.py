import asyncio
from types import SimpleNamespace


def test_inquiry_text_index_models_define_task_contract():
    from csrcqsf.models.orm.inquiry_text_index_task import (
        InquiryTextIndexFailure,
        InquiryTextIndexTask,
    )

    assert {
        "task_id",
        "root_task_id",
        "retry_from_task_id",
        "source_sync_task_id",
        "source_sync_task_ids_json",
        "trigger_source",
        "task_scope",
        "history_ids_json",
        "status",
        "progress",
        "total_items",
        "processed_items",
        "indexed_count",
        "skipped_count",
        "fail_count",
        "deleted_count",
        "current_inquiry_id",
        "heartbeat_at",
        "started_at",
        "completed_at",
        "error_message",
        "cancel_reason",
    }.issubset(set(InquiryTextIndexTask.__table__.columns.keys()))
    assert {
        "task_id",
        "history_id",
        "inquiry_id",
        "item_id",
        "stage",
        "error_type",
        "error_message",
    }.issubset(set(InquiryTextIndexFailure.__table__.columns.keys()))


def test_inquiry_text_index_startup_recovery_classification():
    from csrcqsf.models.orm.inquiry_text_index_task import (
        classify_inquiry_text_index_startup_recovery,
    )

    for status in ("pending", "running", "cancelling"):
        assert classify_inquiry_text_index_startup_recovery(status) == "interrupted"
    for status in ("success", "failed", "cancelled", "interrupted"):
        assert classify_inquiry_text_index_startup_recovery(status) == status


def test_inquiry_text_index_startup_recovery_updates_active_records():
    from csrcqsf.models.orm.inquiry_text_index_task import InquiryTextIndexTask

    records = [
        SimpleNamespace(
            status="running",
            current_inquiry_id="1001",
            completed_at=None,
            heartbeat_at=None,
            error_message=None,
        ),
        SimpleNamespace(
            status="success",
            current_inquiry_id=None,
            completed_at=None,
            heartbeat_at=None,
            error_message=None,
        ),
    ]

    class Session:
        flushed = False

        async def scalars(self, _statement):
            return records

        async def flush(self):
            self.flushed = True

    session = Session()
    result = asyncio.run(InquiryTextIndexTask.recover_active_tasks(session))

    assert result == {"interrupted": 1}
    assert records[0].status == "interrupted"
    assert records[0].current_inquiry_id is None
    assert records[0].completed_at is not None
    assert "服务重启" in records[0].error_message
    assert records[1].status == "success"
    assert session.flushed is True


def test_main_db_registers_inquiry_text_index_models():
    from csrcqsf.infra.db.main_db import MAIN_DB_MODEL_MODULES

    assert "csrcqsf.models.orm.inquiry_text_index_task" in MAIN_DB_MODEL_MODULES


def test_sgo_sync_task_exposes_semantic_follow_up_fields():
    from csrcqsf.models.orm.sgo_sync_task import SgoSyncTask

    columns = set(SgoSyncTask.__table__.columns.keys())
    assert {
        "semantic_index_task_id",
        "semantic_index_triggered",
        "semantic_index_warning",
    }.issubset(columns)
