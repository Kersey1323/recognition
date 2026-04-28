import asyncio
import sys
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


def test_finalize_reconstruction_result_calls_persistence_helper():
    from csrcqsf.biz.railwayparts.reconstruction_server import tasks

    calls = []

    def fake_persist(task_id, task_result):
        calls.append((task_id, task_result))
        return True

    task_result = {
        "ply_path": "/tmp/point_cloud.ply",
        "output_dir": "/tmp/output",
    }

    with patch.object(tasks, "_persist_reconstruction_result_by_task_id", fake_persist):
        assert tasks._finalize_reconstruction_result("task-id", task_result) is True
    assert calls == [("task-id", task_result)]


def test_finalize_reconstruction_result_skips_when_no_ply_path():
    from csrcqsf.biz.railwayparts.reconstruction_server import tasks

    calls = []

    def fake_persist(task_id, task_result):
        calls.append((task_id, task_result))
        return True

    with patch.object(tasks, "_persist_reconstruction_result_by_task_id", fake_persist):
        assert tasks._finalize_reconstruction_result("task-id", {"status": "success"}) is False
    assert calls == []


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_persist_task_result_marks_record_success_and_commits():
    from csrcqsf.biz.railwayparts.reconstruction_manager import ReconstructionManager

    session = AsyncMock()
    record = SimpleNamespace(
        task_id="task-id",
        item_id=1935558010375340032,
        ply_url=None,
    )

    with patch("csrcqsf.biz.railwayparts.reconstruction_manager.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch.object(ReconstructionManager, "_persist_success_result", AsyncMock(return_value=True)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.ReconstructionRecord.update_status", AsyncMock()) as update_status:
        changed = asyncio.run(
            ReconstructionManager.persist_task_result_by_task_id(
                task_id="task-id",
                task_result={"ply_path": "/tmp/point_cloud.ply", "output_dir": "/tmp/output"},
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
    )
    session.commit.assert_awaited_once()


def test_persist_task_result_marks_failed_payload_as_failed_without_persisting_success_result():
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
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.ReconstructionRecord.update_status", AsyncMock()) as update_status:
        changed = asyncio.run(
            ReconstructionManager.persist_task_result_by_task_id(
                task_id="task-id",
                task_result={
                    "status": "failed",
                    "error": "视频重建失败，退出码: 1",
                    "log_file": "/tmp/reconstruction.log",
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
    )
    session.commit.assert_awaited_once()
