import asyncio
import json
import io
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bfrcommon.middlewares.response import catch_exceptions_middleware
from starlette.requests import Request

from csrcqsf.modules.railway_parts.services.reconstruction_service import (
    ReconstructionBusinessError,
    ReconstructionManager,
)
from csrcqsf.models.orm.reconstruction import ReconstructionStatus


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_build_result_object_name_uses_item_id_and_task_id():
    object_name = ReconstructionManager._build_result_object_name(
        item_id=1935558010375340032,
        task_id="task-id",
    )

    assert object_name == "results/1935558010375340032/task-id/point_cloud.ply"


def test_format_reconstruction_result_path_uses_bucket_and_object_name():
    result_path = ReconstructionManager._format_reconstruction_result_path(
        "results/1935558010375340032/task-id/point_cloud.ply"
    )

    assert result_path == "bfr-reconstruction-files/results/1935558010375340032/task-id/point_cloud.ply"


def test_reconstruction_manager_does_not_expose_remote_sam2_model_path_resolver():
    assert not hasattr(ReconstructionManager, "_resolve_reconstruction_sam2_model_path")


def test_resolve_record_ply_path_prefers_local_ply_url():
    record = SimpleNamespace(
        ply_url="/tmp/local-point-cloud.ply",
        output_path="/tmp/output",
        iterations=10000,
    )

    with patch(
        "csrcqsf.modules.railway_parts.services.reconstruction_service._get_minio_helpers",
        return_value=(MagicMock(), MagicMock(return_value=False), MagicMock(), MagicMock(), Exception),
    ):
        assert ReconstructionManager._resolve_record_ply_path(record) == "/tmp/local-point-cloud.ply"


def test_resolve_record_ply_path_builds_path_from_output_dir():
    record = SimpleNamespace(
        ply_url=None,
        output_path="/tmp/output",
        iterations=10000,
    )

    with patch(
        "csrcqsf.modules.railway_parts.services.reconstruction_service._get_minio_helpers",
        return_value=(MagicMock(), MagicMock(return_value=False), MagicMock(), MagicMock(), Exception),
    ):
        assert ReconstructionManager._resolve_record_ply_path(record) == "/tmp/output/point_cloud/iteration_10000/point_cloud.ply"


def test_resolve_video_task_inputs_reads_source_video_path_and_item_name():
    record = SimpleNamespace(
        id=1935558010375340032,
        item_name="螺栓M8X22",
        source_video_path="bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
    )

    assert ReconstructionManager._resolve_video_task_inputs(record) == (
        "bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
        "螺栓M8X22",
    )


def test_resolve_video_task_inputs_rejects_missing_source_video():
    record = SimpleNamespace(
        id=1935558010375340032,
        item_name="螺栓M8X22",
        source_video_path=None,
    )

    try:
        ReconstructionManager._resolve_video_task_inputs(record)
    except ReconstructionBusinessError as exc:
        assert "原始视频" in str(exc)
    else:
        raise AssertionError("missing source video should raise ReconstructionBusinessError")


def test_require_item_exists_rejects_missing_item_with_business_error():
    session = AsyncMock()

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.Items.get_item_by_id", AsyncMock(return_value=None)):
        try:
            asyncio.run(ReconstructionManager._require_item_exists(1935558010375340032))
        except ReconstructionBusinessError as exc:
            assert "配件不存在" in str(exc)
        else:
            raise AssertionError("missing item should raise ReconstructionBusinessError")


def test_upload_source_video_rejects_duplicate_binding_with_business_error():
    item = SimpleNamespace(
        id=2023080809420000001,
        source_video_path="bfr-3d-videos/raw-videos/2023080809420000001/demo.mp4",
    )

    with patch.object(ReconstructionManager, "_require_item_exists", AsyncMock(return_value=item)):
        try:
            asyncio.run(
                ReconstructionManager.upload_source_video(
                    item_id=item.id,
                    file=SimpleNamespace(),
                )
            )
        except ReconstructionBusinessError as exc:
            assert "请使用更新接口替换" in str(exc)
        else:
            raise AssertionError("duplicate source video should raise ReconstructionBusinessError")


def test_delete_reconstruction_result_rejects_missing_result_with_business_error():
    session = AsyncMock()
    record = SimpleNamespace(
        task_id="task-id",
        item_id=2023080809420000001,
        ply_url=None,
        obj_url=None,
        glb_url=None,
    )

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)):
        try:
            asyncio.run(ReconstructionManager.delete_reconstruction_result("task-id"))
        except ReconstructionBusinessError as exc:
            assert "三维重构结果" in str(exc)
        else:
            raise AssertionError("missing reconstruction result should raise ReconstructionBusinessError")


def test_delete_reconstruction_result_deletes_the_requested_task_model():
    session = AsyncMock()
    result_path = "bfr-reconstruction-files/results/1001/task-id/point_cloud.ply"
    record = SimpleNamespace(
        task_id="task-id",
        item_id=1001,
        ply_url=result_path,
        obj_url=None,
        glb_url=None,
    )
    item = SimpleNamespace(id=1001, obj_url=result_path)

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.Items.get_item_by_id", AsyncMock(return_value=item)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.Items.update_obj_url", AsyncMock()) as update_obj_url, \
         patch.object(ReconstructionManager, "_delete_minio_object", AsyncMock(return_value=True)) as delete_object:
        result = asyncio.run(ReconstructionManager.delete_reconstruction_result("task-id"))

    delete_object.assert_awaited_once_with(
        result_path,
        default_bucket="bfr-reconstruction-files",
    )
    update_obj_url.assert_awaited_once_with(session=session, item_id=1001, obj_url=None)
    assert record.ply_url is None
    assert result["task_id"] == "task-id"
    assert result["item_id"] == 1001


def test_delete_historical_task_model_keeps_current_item_binding():
    session = AsyncMock()
    historical_path = "bfr-reconstruction-files/results/1001/old-task/point_cloud.ply"
    record = SimpleNamespace(
        task_id="old-task",
        item_id=1001,
        ply_url=historical_path,
        obj_url=None,
        glb_url=None,
    )
    item = SimpleNamespace(
        id=1001,
        obj_url="bfr-reconstruction-files/results/1001/new-task/point_cloud.ply",
    )

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.Items.get_item_by_id", AsyncMock(return_value=item)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.Items.update_obj_url", AsyncMock()) as update_obj_url, \
         patch.object(ReconstructionManager, "_delete_minio_object", AsyncMock(return_value=True)):
        asyncio.run(ReconstructionManager.delete_reconstruction_result("old-task"))

    update_obj_url.assert_not_awaited()


def test_reconstruction_business_error_is_wrapped_as_fail_response_with_http_200():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/business-error",
            "headers": [],
            "query_string": b"",
            "client": ("testclient", 123),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )
    middleware = catch_exceptions_middleware()

    async def _raise_business_error(_request):
        raise ReconstructionBusinessError("配件已存在原始视频，请使用更新接口替换")

    response = asyncio.run(middleware(request, _raise_business_error))
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "fail"
    assert payload["message"] == "配件已存在原始视频，请使用更新接口替换"


def test_page_to_limit_offset_converts_page_and_page_size():
    assert ReconstructionManager._page_to_limit_offset(page=1, page_size=10) == (10, 0)
    assert ReconstructionManager._page_to_limit_offset(page=3, page_size=10) == (10, 20)


def test_serialize_task_record_marks_deleted_success_result():
    record = SimpleNamespace(
        task_id="task-id",
        item_id=2023080809420000001,
        task_type="video",
        status=ReconstructionStatus.SUCCESS,
        progress=100,
        current_stage="完成",
        scene_name="demo",
        error_message=None,
        ply_url=None,
        glb_url=None,
        total_frames=None,
        filtered_frames=None,
        colmap_points=None,
        completed_at=datetime(2026, 7, 27, 10, 0, 0),
        time_created=datetime(2026, 7, 27, 9, 0, 0),
        time_updated=datetime(2026, 7, 27, 10, 0, 0),
    )

    result = ReconstructionManager._serialize_task_record(record)

    assert result["is_ply_del"] is True


def test_serialize_task_record_keeps_non_success_task_as_not_deleted():
    record = SimpleNamespace(
        task_id="task-id",
        item_id=2023080809420000001,
        task_type="video",
        status=ReconstructionStatus.FAILED,
        progress=80,
        current_stage="失败",
        scene_name="demo",
        error_message="训练失败",
        ply_url=None,
        glb_url=None,
        total_frames=None,
        filtered_frames=None,
        colmap_points=None,
        completed_at=datetime(2026, 7, 27, 10, 0, 0),
        time_created=datetime(2026, 7, 27, 9, 0, 0),
        time_updated=datetime(2026, 7, 27, 10, 0, 0),
    )

    result = ReconstructionManager._serialize_task_record(record)

    assert result["is_ply_del"] is False


def test_get_task_item_detail_returns_the_requested_task_and_item_metadata():
    session = AsyncMock()
    record = SimpleNamespace(
        task_id="task-id",
        item_id=2023080809420000001,
        task_type="video",
        status=ReconstructionStatus.SUCCESS,
        progress=100,
        current_stage="完成",
        scene_name="demo",
        error_message=None,
        ply_url=None,
        glb_url=None,
        total_frames=80,
        filtered_frames=60,
        colmap_points=1200,
        completed_at=datetime(2026, 7, 27, 10, 0, 0),
        time_created=datetime(2026, 7, 27, 9, 0, 0),
        time_updated=datetime(2026, 7, 27, 10, 0, 0),
    )
    item = SimpleNamespace(
        id=2023080809420000001,
        item_name="配件A",
        item_code="40001082506",
        height=10,
        long=20,
        width=30,
        weight=40,
        source_video_path="bfr-3d-videos/raw-videos/demo.mp4",
        size_str="10x20x30",
        parent_item_id=0,
        time_created=datetime(2026, 7, 1, 9, 0, 0),
        time_updated=datetime(2026, 7, 27, 8, 0, 0),
    )

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.Items.get_item_by_id", AsyncMock(return_value=item)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.reconstruction_server_env_configured", return_value=True), \
         patch.object(ReconstructionManager, "_get_reconstruction_client") as client_mock:
        result = asyncio.run(ReconstructionManager.get_task_item_detail("task-id"))

    client_mock.assert_not_called()
    assert result["task_id"] == "task-id"
    assert result["item_id"] == item.id
    assert result["item_name"] == "配件A"
    assert result["item_code"] == "40001082506"
    assert result["is_ply_del"] is True


def test_get_task_status_does_not_restore_a_deleted_task_result_from_remote():
    session = AsyncMock()
    record = SimpleNamespace(
        task_id="task-id",
        item_id=1001,
        status=ReconstructionStatus.SUCCESS,
        progress=100,
        current_stage="完成",
        error_message=None,
        ply_url=None,
        obj_url=None,
        glb_url=None,
        total_frames=None,
        filtered_frames=None,
        colmap_points=None,
        completed_at=datetime(2026, 7, 27, 10, 0, 0),
        elapsed_sec=600,
        time_created=datetime(2026, 7, 27, 9, 50, 0),
        time_updated=datetime(2026, 7, 27, 10, 0, 0),
    )

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.reconstruction_server_env_configured", return_value=True), \
         patch.object(ReconstructionManager, "_get_reconstruction_client") as client_mock, \
         patch.object(ReconstructionManager, "_persist_success_result", AsyncMock()) as persist_result:
        result = asyncio.run(ReconstructionManager.get_task_status("task-id"))

    client_mock.assert_not_called()
    persist_result.assert_not_awaited()
    assert result["ply_url"] is None
    assert result["is_ply_del"] is True


def test_build_video_run_name_uses_timestamp_and_item_name():
    run_name = ReconstructionManager._build_video_run_name("橡胶套")

    assert run_name.endswith("_橡胶套")
    assert len(run_name.split("_", 1)[0]) == 14


def test_get_task_status_treats_celery_success_with_failed_payload_as_failed():
    session = AsyncMock()
    task_result = {
        "task_id": "task-id",
        "status": "FAILURE",
        "progress": 85,
        "current_stage": "失败",
        "error_message": "视频重建失败，退出码: 1",
        "ply_path": None,
    }
    record = SimpleNamespace(
        task_id="task-id",
        item_id=2023080809420000001,
        status=ReconstructionStatus.TRAINING,
        progress=85,
        current_stage="训练中",
        error_message=None,
        ply_url=None,
        glb_url=None,
        total_frames=None,
        filtered_frames=None,
        colmap_points=None,
        time_created=datetime(2026, 4, 28, 14, 49, 2),
        time_updated=datetime(2026, 4, 28, 14, 53, 38),
    )
    fake_client = SimpleNamespace(get_task_status=AsyncMock(return_value=task_result))

    with patch.object(ReconstructionManager, "_get_reconstruction_client", return_value=fake_client), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.reconstruction_server_env_configured", return_value=True), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch.object(ReconstructionManager, "_persist_success_result", AsyncMock(return_value=True)) as persist_success_result, \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.update_status", AsyncMock()) as update_status, \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.datetime") as datetime_mock:
        datetime_mock.now.return_value = datetime(2026, 4, 28, 16, 27, 53)
        result = asyncio.run(ReconstructionManager.get_task_status("task-id"))

    assert result["task_id"] == "task-id"
    assert result["item_id"] == 2023080809420000001
    assert result["status"] == ReconstructionStatus.FAILED
    assert result["progress"] == 85
    assert result["current_stage"] == "失败"
    assert result["error_message"] == "视频重建失败，退出码: 1"
    persist_success_result.assert_not_awaited()
    update_status.assert_awaited_once_with(
        session=session,
        task_id="task-id",
        status=ReconstructionStatus.FAILED,
        progress=85,
        current_stage="失败",
        error_message="视频重建失败，退出码: 1",
        completed_at=datetime(2026, 4, 28, 16, 27, 53),
        elapsed_sec=None,
    )


def test_get_task_status_promotes_success_payload_to_completed_response_and_terminal_time():
    session = AsyncMock()
    completed_at = datetime(2026, 4, 28, 16, 27, 53)
    record = SimpleNamespace(
        task_id="task-id",
        item_id=2023080809420000001,
        status=ReconstructionStatus.SUCCESS,
        progress=98,
        current_stage="提取结果",
        error_message=None,
        ply_url="bfr-reconstruction-files/results/demo/point_cloud.ply",
        glb_url=None,
        total_frames=None,
        filtered_frames=None,
        colmap_points=None,
        completed_at=None,
        elapsed_sec=None,
        time_created=datetime(2026, 4, 28, 16, 19, 27),
        time_updated=datetime(2026, 4, 28, 16, 25, 10),
    )
    fake_client = SimpleNamespace(
        get_task_status=AsyncMock(
            return_value={
                "task_id": "task-id",
                "status": "SUCCESS",
                "progress": 100,
                "current_stage": "完成",
                "error_message": None,
                "ply_path": "bfr-reconstruction-files/results/demo/point_cloud.ply",
                "elapsed_sec": 493.4,
            }
        )
    )

    with patch.object(ReconstructionManager, "_get_reconstruction_client", return_value=fake_client), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.reconstruction_server_env_configured", return_value=True), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch.object(ReconstructionManager, "_persist_success_result", AsyncMock(return_value=False)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.update_status", AsyncMock()) as update_status, \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.datetime") as datetime_mock:
        datetime_mock.now.return_value = completed_at
        result = asyncio.run(ReconstructionManager.get_task_status("task-id"))

    assert result["status"] == ReconstructionStatus.SUCCESS
    assert result["progress"] == 100
    assert result["current_stage"] == "完成"
    assert result["time_updated"] == completed_at.isoformat()
    update_status.assert_awaited_once_with(
        session=session,
        task_id="task-id",
        status=ReconstructionStatus.SUCCESS,
        progress=100,
        current_stage="完成",
        error_message=None,
        completed_at=completed_at,
        elapsed_sec=493.4,
    )


def test_get_task_status_keeps_terminal_success_when_celery_backend_falls_back_to_pending():
    session = AsyncMock()
    completed_at = datetime(2026, 4, 28, 16, 27, 53)
    record = SimpleNamespace(
        task_id="task-id",
        item_id=2023080809420000001,
        status=ReconstructionStatus.SUCCESS,
        progress=100,
        current_stage="完成",
        error_message=None,
        ply_url="bfr-reconstruction-files/results/demo/point_cloud.ply",
        glb_url=None,
        total_frames=None,
        filtered_frames=None,
        colmap_points=None,
        completed_at=completed_at,
        elapsed_sec=493.4,
        time_created=datetime(2026, 4, 28, 16, 19, 27),
        time_updated=datetime(2026, 5, 13, 11, 24, 14),
    )
    fake_client = SimpleNamespace(
        get_task_status=AsyncMock(
            return_value={
                "task_id": "task-id",
                "status": "PENDING",
                "progress": 0,
                "current_stage": "等待中",
                "error_message": None,
                "ply_path": None,
            }
        )
    )

    with patch.object(ReconstructionManager, "_get_reconstruction_client", return_value=fake_client), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.reconstruction_server_env_configured", return_value=True), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.update_status", AsyncMock()) as update_status:
        result = asyncio.run(ReconstructionManager.get_task_status("task-id"))

    assert result["status"] == ReconstructionStatus.SUCCESS
    assert result["progress"] == 100
    assert result["current_stage"] == "完成"
    assert result["time_updated"] == completed_at.isoformat()
    update_status.assert_not_awaited()


@pytest.mark.parametrize("remote_state", ["RECOVERY_QUEUED", "RECOVERING"])
def test_get_task_status_reopens_failed_snapshot_for_explicit_recovery_state(remote_state):
    session = AsyncMock()
    record = SimpleNamespace(
        task_id="task-id",
        item_id=2023080809420000001,
        status=ReconstructionStatus.FAILED,
        progress=55,
        current_stage="失败",
        error_message="COLMAP match database is incomplete",
        ply_url=None,
        obj_url=None,
        glb_url=None,
        total_frames=None,
        filtered_frames=None,
        colmap_points=None,
        completed_at=datetime(2026, 8, 27, 11, 27, 47),
        elapsed_sec=356.0,
        time_created=datetime(2026, 8, 27, 11, 21, 52),
        time_updated=datetime(2026, 8, 27, 13, 42, 0),
    )
    fake_client = SimpleNamespace(
        get_task_status=AsyncMock(
            return_value={
                "task_id": "task-id",
                "status": remote_state,
                "progress": 55,
                "current_stage": "等待人工恢复: colmap",
                "error_message": None,
                "ply_path": None,
            }
        )
    )

    with patch.object(ReconstructionManager, "_get_reconstruction_client", return_value=fake_client), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.reconstruction_server_env_configured", return_value=True), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.update_status", AsyncMock()) as update_status:
        result = asyncio.run(ReconstructionManager.get_task_status("task-id"))

    assert result["status"] == ReconstructionStatus.TRAINING
    assert result["progress"] == 55
    assert result["current_stage"] == "等待人工恢复: colmap"
    assert result["error_message"] is None
    assert record.completed_at is None
    assert record.elapsed_sec is None
    update_status.assert_awaited_once()
    session.commit.assert_awaited_once()


def test_get_task_status_returns_local_snapshot_when_remote_service_url_missing():
    session = AsyncMock()
    completed_at = datetime(2026, 5, 27, 10, 0, 0)
    record = SimpleNamespace(
        task_id="task-id",
        item_id=2023080809420000001,
        status=ReconstructionStatus.SUCCESS,
        progress=100,
        current_stage="完成",
        error_message=None,
        ply_url="bfr-reconstruction-files/results/demo/point_cloud.ply",
        glb_url=None,
        total_frames=None,
        filtered_frames=None,
        colmap_points=None,
        completed_at=completed_at,
        elapsed_sec=493.4,
        time_created=datetime(2026, 5, 27, 9, 0, 0),
        time_updated=datetime(2026, 5, 27, 9, 30, 0),
    )

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.reconstruction_server_env_configured", return_value=False), \
         patch.object(ReconstructionManager, "_get_reconstruction_client") as client_mock:
        result = asyncio.run(ReconstructionManager.get_task_status("task-id"))

    client_mock.assert_not_called()
    assert result["status"] == ReconstructionStatus.SUCCESS
    assert result["ply_url"].endswith("point_cloud.ply")
    assert result["time_updated"] == completed_at.isoformat()


def _fake_upload_file(filename: str, content_type: str = "application/octet-stream", body: bytes = b"ply"):
    return SimpleNamespace(
        filename=filename,
        content_type=content_type,
        file=io.BytesIO(body),
        close=AsyncMock(),
    )


def test_upload_reconstruction_result_rejects_duplicate_binding():
    item = SimpleNamespace(
        id=2023080809420000001,
        obj_url="bfr-reconstruction-files/results/manual/2023080809420000001/demo.ply",
    )

    with patch.object(ReconstructionManager, "_require_item_exists", AsyncMock(return_value=item)):
        try:
            asyncio.run(
                ReconstructionManager.upload_reconstruction_result(
                    item_id=item.id,
                    file=_fake_upload_file("demo.ply"),
                )
            )
        except ReconstructionBusinessError as exc:
            assert "已经存在重构模型" in str(exc)
        else:
            raise AssertionError("duplicate reconstruction result should raise ReconstructionBusinessError")


def test_upload_reconstruction_result_rejects_non_ply_file():
    item = SimpleNamespace(id=2023080809420000001, obj_url=None)

    with patch.object(ReconstructionManager, "_require_item_exists", AsyncMock(return_value=item)):
        try:
            asyncio.run(
                ReconstructionManager.upload_reconstruction_result(
                    item_id=item.id,
                    file=_fake_upload_file("demo.glb"),
                )
            )
        except ReconstructionBusinessError as exc:
            assert ".ply" in str(exc)
        else:
            raise AssertionError("non-ply upload should raise ReconstructionBusinessError")


def test_upload_reconstruction_result_rolls_back_minio_when_pg_update_fails():
    item = SimpleNamespace(id=2023080809420000001, obj_url=None)
    session = AsyncMock()

    with patch.object(ReconstructionManager, "_require_item_exists", AsyncMock(return_value=item)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.run_sync", AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs))), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.Items.update_obj_url", AsyncMock(side_effect=RuntimeError("pg failed"))), \
         patch(
             "csrcqsf.modules.railway_parts.services.reconstruction_service._get_minio_helpers",
             return_value=(
                 MagicMock(),
                 MagicMock(return_value=True),
                 SimpleNamespace(client=SimpleNamespace(put_object=MagicMock())),
                 MagicMock(),
                 Exception,
             ),
         ), \
         patch.object(ReconstructionManager, "_delete_minio_object", AsyncMock()) as delete_mock:
        try:
            asyncio.run(
                ReconstructionManager.upload_reconstruction_result(
                    item_id=item.id,
                    file=_fake_upload_file("demo.ply"),
                )
            )
        except RuntimeError as exc:
            assert "pg failed" in str(exc)
        else:
            raise AssertionError("PG failure should bubble up")

    session.rollback.assert_awaited()
    delete_mock.assert_awaited()
