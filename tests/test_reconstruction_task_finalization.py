import asyncio
import importlib
import sys
from datetime import datetime
from pathlib import Path
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


def _import_reconstruction_service_module():
    module_name = "csrcqsf.modules.railway_parts.services.reconstruction_service"
    sys.modules.pop(module_name, None)

    import csrcqsf.modules.railway_parts.services as services_pkg

    if hasattr(services_pkg, "reconstruction_service"):
        delattr(services_pkg, "reconstruction_service")

    return importlib.import_module(module_name)


def test_persist_task_result_marks_record_success_with_completed_at_and_elapsed_sec():
    service_module = _import_reconstruction_service_module()
    ReconstructionManager = service_module.ReconstructionManager

    session = AsyncMock()
    record = SimpleNamespace(
        task_id="task-id",
        item_id=1935558010375340032,
        ply_url=None,
        progress=98,
    )

    with patch.object(service_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(service_module.ReconstructionRecord, "get_by_task_id", AsyncMock(return_value=record)), \
         patch.object(ReconstructionManager, "_persist_success_result", AsyncMock(return_value=True)), \
         patch.object(service_module.ReconstructionRecord, "update_status", AsyncMock()) as update_status, \
         patch.object(service_module, "datetime") as datetime_mock:
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
    service_module = _import_reconstruction_service_module()
    ReconstructionManager = service_module.ReconstructionManager

    session = AsyncMock()
    record = SimpleNamespace(
        task_id="task-id",
        item_id=1935558010375340032,
        ply_url=None,
        progress=65,
    )

    with patch.object(service_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(service_module.ReconstructionRecord, "get_by_task_id", AsyncMock(return_value=record)), \
         patch.object(ReconstructionManager, "_persist_success_result", AsyncMock(return_value=True)) as persist_success_result, \
         patch.object(service_module.ReconstructionRecord, "update_status", AsyncMock()) as update_status, \
         patch.object(service_module, "datetime") as datetime_mock:
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

