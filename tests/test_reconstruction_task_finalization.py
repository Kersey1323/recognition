import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.reconstruction import ReconstructionStatus


RECONSTRUCTION_SERVER_DIR = Path("csrcqsf/biz/railwayparts/reconstruction_server").resolve()
if str(RECONSTRUCTION_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(RECONSTRUCTION_SERVER_DIR))


def test_reconstruction_server_get_task_info_treats_business_failed_payload_as_failure():
    from csrcqsf.biz.railwayparts.reconstruction_server import api

    task_result = {
        "status": "failed",
        "error": "视频重建失败，退出码: 1",
        "log_file": "/tmp/reconstruction.log",
    }
    celery_result = SimpleNamespace(
        state="SUCCESS",
        result=task_result,
        info=None,
    )

    with patch.object(api, "AsyncResult", return_value=celery_result):
        response = api.get_task_info("task-id")

    assert response == {
        "task_id": "task-id",
        "status": "FAILURE",
        "result": task_result,
        "error": "视频重建失败，退出码: 1",
        "stage": "失败",
        "progress": 0,
    }


def test_upload_result_if_needed_returns_input_path_when_item_id_missing():
    from csrcqsf.biz.railwayparts.reconstruction_server import tasks

    assert (
        tasks._upload_result_if_needed("task-id", None, "/tmp/point_cloud.ply")
        == "/tmp/point_cloud.ply"
    )


def test_upload_result_if_needed_reuses_minio_path_without_reupload():
    from csrcqsf.biz.railwayparts.reconstruction_server import tasks

    minio_path = "bfr-reconstruction-files/results/1001/task-id/point_cloud.ply"

    assert tasks._upload_result_if_needed("task-id", "1001", minio_path) == minio_path


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_persist_task_result_marks_record_success_with_completed_at_and_elapsed_sec():
    from csrcqsf.biz.railwayparts.reconstruction_manager import ReconstructionManager

    session = AsyncMock()
    record = SimpleNamespace(
        task_id="task-id",
        item_id=1935558010375340032,
        ply_url=None,
        progress=98,
    )

    with patch("csrcqsf.biz.railwayparts.reconstruction_manager.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch.object(ReconstructionManager, "_persist_success_result", AsyncMock(return_value=True)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.ReconstructionRecord.update_status", AsyncMock()) as update_status, \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.datetime") as datetime_mock:
        datetime_mock.utcnow.return_value = datetime(2026, 4, 28, 16, 27, 53)
        changed = asyncio.run(
            ReconstructionManager.persist_task_result_by_task_id(
                task_id="task-id",
                task_result={
                    "status": "success",
                    "ply_path": "/tmp/point_cloud.ply",
                    "output_dir": "/tmp/output",
                    "elapsed_sec": 493.4,
                },
            )
        )

    assert changed is True
    update_status.assert_awaited_once_with(
        session=session,
        task_id="task-id",
        status=ReconstructionStatus.SUCCESS,
        progress=100,
        current_stage="完成",
        error_message=None,
        completed_at=datetime(2026, 4, 28, 16, 27, 53),
        elapsed_sec=493.4,
    )
    session.commit.assert_awaited_once()


def test_persist_task_result_marks_failed_payload_with_completed_at_and_elapsed_sec():
    from csrcqsf.biz.railwayparts.reconstruction_manager import ReconstructionManager

    session = AsyncMock()
    record = SimpleNamespace(
        task_id="task-id",
        item_id=1935558010375340032,
        ply_url=None,
        progress=65,
    )

    with patch("csrcqsf.biz.railwayparts.reconstruction_manager.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch.object(ReconstructionManager, "_persist_success_result", AsyncMock(return_value=True)) as persist_success_result, \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.ReconstructionRecord.update_status", AsyncMock()) as update_status, \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.datetime") as datetime_mock:
        datetime_mock.utcnow.return_value = datetime(2026, 4, 28, 16, 27, 53)
        changed = asyncio.run(
            ReconstructionManager.persist_task_result_by_task_id(
                task_id="task-id",
                task_result={
                    "status": "failed",
                    "error": "视频重建失败，退出码: 1",
                    "elapsed_sec": 120.5,
                },
            )
        )

    assert changed is False
    persist_success_result.assert_not_awaited()
    update_status.assert_awaited_once_with(
        session=session,
        task_id="task-id",
        status=ReconstructionStatus.FAILED,
        progress=65,
        current_stage="失败",
        error_message="视频重建失败，退出码: 1",
        completed_at=datetime(2026, 4, 28, 16, 27, 53),
        elapsed_sec=120.5,
    )
    session.commit.assert_awaited_once()


def test_video_reconstruction_failure_payload_includes_elapsed_sec():
    from csrcqsf.biz.railwayparts.reconstruction_server import tasks

    fake_self = SimpleNamespace(
        request=SimpleNamespace(id="task-id"),
        update_progress=lambda *args, **kwargs: None,
    )

    with patch.object(tasks.os.path, "exists", return_value=True), \
         patch.object(tasks.subprocess, "Popen", side_effect=RuntimeError("boom")), \
         patch.object(tasks.time, "time", side_effect=[100.0, 101.6]):
        result = tasks.video_reconstruction.run.__func__(
            fake_self,
            video_path="/tmp/demo.mp4",
            name="demo",
            iterations=30000,
            output_name="demo",
        )

    assert result["status"] == "failed"
    assert result["elapsed_sec"] == 1.6
