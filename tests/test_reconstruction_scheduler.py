import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from csrcqsf.models.reconstruction import ReconstructionStatus


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_sync_manager_updates_running_records_from_remote_batch_status():
    from csrcqsf.biz.railwayparts.reconstruction_sync_manager import ReconstructionSyncManager

    session = AsyncMock()
    record = SimpleNamespace(
        task_id="task-id",
        item_id=1001,
        status=ReconstructionStatus.TRAINING,
        progress=40,
        current_stage="训练中",
        error_message=None,
        ply_url=None,
        completed_at=None,
        elapsed_sec=None,
    )
    fake_client = SimpleNamespace(
        get_task_status_batch=AsyncMock(
            return_value={
                "items": [
                    {
                        "task_id": "task-id",
                        "status": "SUCCESS",
                        "progress": 100,
                        "current_stage": "完成",
                        "error_message": None,
                        "ply_path": "bfr-reconstruction-files/results/task-id/point_cloud.ply",
                    }
                ]
            }
        )
    )
    fake_scalars = MagicMock()
    fake_scalars.all.return_value = [record]
    session.scalars.return_value = fake_scalars

    with patch(
        "csrcqsf.biz.railwayparts.reconstruction_sync_manager.SessionLocal",
        return_value=_AsyncSessionContext(session),
    ), patch(
        "csrcqsf.biz.railwayparts.reconstruction_sync_manager.ReconstructionServiceClient",
        return_value=fake_client,
    ), patch(
        "csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionManager._persist_success_result",
        AsyncMock(return_value=True),
    ):
        result = asyncio.run(ReconstructionSyncManager.sync_running_tasks())

    assert result["synced_count"] == 1
    assert record.status == ReconstructionStatus.SUCCESS
    assert record.current_stage == "完成"


def test_scheduler_returns_early_without_remote_service_env():
    with patch("csrcqsf.scheduler.main_db_env_configured", return_value=True), \
         patch("csrcqsf.scheduler.reconstruction_server_env_configured", return_value=False), \
         patch("csrcqsf.scheduler.asyncio.run_coroutine_threadsafe") as run_mock:
        from csrcqsf.scheduler import sync_reconstruction_tasks_sync

        sync_reconstruction_tasks_sync()

    run_mock.assert_not_called()


def test_scheduler_skips_when_main_loop_not_registered():
    with patch("csrcqsf.scheduler.main_db_env_configured", return_value=True), \
         patch("csrcqsf.scheduler.reconstruction_server_env_configured", return_value=True), \
         patch("csrcqsf.scheduler._main_async_loop", None), \
         patch("csrcqsf.scheduler.asyncio.run_coroutine_threadsafe") as submit_mock:
        from csrcqsf.scheduler import sync_reconstruction_tasks_sync

        sync_reconstruction_tasks_sync()

    submit_mock.assert_not_called()


def test_scheduler_submits_sync_task_to_registered_main_loop():
    future = MagicMock()
    future.result.return_value = {"total": 1, "synced_count": 0}
    fake_loop = MagicMock()
    fake_loop.is_running.return_value = True

    def _submit(coro, loop):
        coro.close()
        return future

    with patch("csrcqsf.scheduler.main_db_env_configured", return_value=True), \
         patch("csrcqsf.scheduler.reconstruction_server_env_configured", return_value=True), \
         patch("csrcqsf.scheduler._main_async_loop", fake_loop), \
         patch("csrcqsf.scheduler.asyncio.run_coroutine_threadsafe", side_effect=_submit) as submit_mock:
        from csrcqsf.scheduler import sync_reconstruction_tasks_sync

        sync_reconstruction_tasks_sync()

    submit_mock.assert_called_once()
    future.result.assert_called_once()


def test_reconstruction_manager_no_longer_imports_local_celery_execution_chain():
    text = Path("csrcqsf/modules/railway_parts/services/reconstruction_service.py").read_text(encoding="utf-8")

    assert "_get_celery_modules" not in text
    assert "from celery.result import AsyncResult" not in text
    assert 'Path(__file__).parent / "reconstruction_server"' not in text
