import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.reconstruction import ReconstructionStatus


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_submit_video_task_persists_local_record_and_calls_remote_client():
    from csrcqsf.modules.railway_parts.services.reconstruction_service import ReconstructionManager

    item = SimpleNamespace(id=1001, item_name="闸片", source_video_path="bfr-3d-videos/raw/demo.mp4")
    session = AsyncMock()
    fake_client = SimpleNamespace(
        submit_video_task=AsyncMock(
            return_value={"task_id": "task-1", "status": "SUBMITTED", "message": "ok"}
        )
    )

    with patch.object(ReconstructionManager, "_require_item_exists", AsyncMock(return_value=item)), \
         patch.object(ReconstructionManager, "_get_reconstruction_client", return_value=fake_client), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.create_record", AsyncMock()) as create_record_mock, \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.update_status", AsyncMock()):
        result = asyncio.run(ReconstructionManager.submit_video_task(item_id=1001))

    assert result == {
        "task_id": result["task_id"],
        "item_id": 1001,
        "mode": "video",
        "message": "视频重建任务已提交",
    }
    payload = fake_client.submit_video_task.await_args.args[0]
    assert payload["task_id"] == result["task_id"]
    assert payload["video_path"] == "bfr-3d-videos/raw/demo.mp4"
    create_record_mock.assert_awaited_once()


def test_get_task_status_maps_remote_payload_to_existing_public_shape():
    from csrcqsf.modules.railway_parts.services.reconstruction_service import ReconstructionManager

    session = AsyncMock()
    record = SimpleNamespace(
        task_id="task-1",
        item_id=1001,
        status=ReconstructionStatus.PENDING,
        progress=0,
        current_stage="已提交",
        error_message=None,
        ply_url=None,
        glb_url=None,
        total_frames=None,
        filtered_frames=None,
        colmap_points=None,
        completed_at=None,
        elapsed_sec=None,
        time_created=datetime(2026, 5, 26, 9, 0, 0),
        time_updated=datetime(2026, 5, 26, 9, 0, 0),
    )
    fake_client = SimpleNamespace(
        get_task_status=AsyncMock(
            return_value={
                "task_id": "task-1",
                "status": "SUCCESS",
                "progress": 100,
                "current_stage": "完成",
                "error_message": None,
                "ply_path": "bfr-reconstruction-files/results/task-1/point_cloud.ply",
            }
        )
    )

    async def _persist_success_result(*args, **kwargs):
        record.ply_url = "bfr-reconstruction-files/results/task-1/point_cloud.ply"
        return True

    with patch.object(ReconstructionManager, "_get_reconstruction_client", return_value=fake_client), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.reconstruction_server_env_configured", return_value=True), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch.object(ReconstructionManager, "_persist_success_result", AsyncMock(side_effect=_persist_success_result)):
        result = asyncio.run(ReconstructionManager.get_task_status("task-1"))

    assert result["task_id"] == "task-1"
    assert result["item_id"] == 1001
    assert result["status"] == ReconstructionStatus.SUCCESS
    assert result["ply_url"].endswith("point_cloud.ply")
