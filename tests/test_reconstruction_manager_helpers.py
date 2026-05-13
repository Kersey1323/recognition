import asyncio
import json
import io
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bfrcommon.middlewares.response import catch_exceptions_middleware
from starlette.requests import Request

from csrcqsf.biz.railwayparts.reconstruction_manager import (
    ReconstructionBusinessError,
    ReconstructionManager,
)
from csrcqsf.models.reconstruction import ReconstructionStatus


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


def test_resolve_sam3_model_path_returns_empty_when_disabled():
    assert ReconstructionManager._resolve_sam3_model_path(
        is_sam3=False,
        configured_path="/path/does/not/matter",
    ) == ""


def test_resolve_sam3_model_path_returns_configured_existing_path_when_enabled():
    path = ReconstructionManager._resolve_sam3_model_path(
        is_sam3=True,
        configured_path=str(Path("/tmp")),
    )

    assert path == "/tmp"


def test_resolve_sam3_model_path_rejects_missing_path_when_enabled():
    try:
        ReconstructionManager._resolve_sam3_model_path(
            is_sam3=True,
            configured_path="/path/that/does/not/exist",
        )
    except ReconstructionBusinessError as exc:
        assert "SAM3_MODEL_PATH" in str(exc)
    else:
        raise AssertionError("missing SAM3_MODEL_PATH should raise ReconstructionBusinessError")


def test_resolve_record_ply_path_prefers_local_ply_url():
    record = SimpleNamespace(
        ply_url="/tmp/local-point-cloud.ply",
        output_path="/tmp/output",
        iterations=10000,
    )

    with patch(
        "csrcqsf.biz.railwayparts.reconstruction_manager._get_minio_helpers",
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
        "csrcqsf.biz.railwayparts.reconstruction_manager._get_minio_helpers",
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

    with patch("csrcqsf.biz.railwayparts.reconstruction_manager.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.Items.get_item_by_id", AsyncMock(return_value=None)):
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
    item = SimpleNamespace(
        id=2023080809420000001,
        obj_url=None,
    )

    with patch.object(ReconstructionManager, "_require_item_exists", AsyncMock(return_value=item)):
        try:
            asyncio.run(ReconstructionManager.delete_reconstruction_result(item.id))
        except ReconstructionBusinessError as exc:
            assert "三维重构结果" in str(exc)
        else:
            raise AssertionError("missing reconstruction result should raise ReconstructionBusinessError")


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


def test_build_video_run_name_uses_timestamp_and_item_name():
    run_name = ReconstructionManager._build_video_run_name("橡胶套")

    assert run_name.endswith("_橡胶套")
    assert len(run_name.split("_", 1)[0]) == 14


def test_get_task_status_treats_celery_success_with_failed_payload_as_failed():
    session = AsyncMock()
    task_result = {
        "status": "failed",
        "error": "视频重建失败，退出码: 1",
        "log_file": "/tmp/reconstruction.log",
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
    celery_result = SimpleNamespace(
        state="SUCCESS",
        result=task_result,
        info=None,
    )

    with patch("csrcqsf.biz.railwayparts.reconstruction_manager._get_celery_modules", return_value=(MagicMock(), None, None)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.AsyncResult", return_value=celery_result), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch.object(ReconstructionManager, "_persist_success_result", AsyncMock(return_value=True)) as persist_success_result, \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.ReconstructionRecord.update_status", AsyncMock()) as update_status, \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.datetime") as datetime_mock:
        datetime_mock.utcnow.return_value = datetime(2026, 4, 28, 16, 27, 53)
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
    celery_result = SimpleNamespace(
        state="SUCCESS",
        result={
            "status": "success",
            "ply_path": "/tmp/point_cloud.ply",
            "output_dir": "/tmp/output",
            "elapsed_sec": 493.4,
        },
        info=None,
        date_done=completed_at,
    )

    with patch("csrcqsf.biz.railwayparts.reconstruction_manager._get_celery_modules", return_value=(MagicMock(), None, None)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.AsyncResult", return_value=celery_result), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch.object(ReconstructionManager, "_persist_success_result", AsyncMock(return_value=False)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.ReconstructionRecord.update_status", AsyncMock()) as update_status:
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
    celery_result = SimpleNamespace(
        state="PENDING",
        result=None,
        info=None,
        date_done=None,
    )

    with patch("csrcqsf.biz.railwayparts.reconstruction_manager._get_celery_modules", return_value=(MagicMock(), None, None)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.AsyncResult", return_value=celery_result), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.ReconstructionRecord.get_by_task_id", AsyncMock(return_value=record)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.ReconstructionRecord.update_status", AsyncMock()) as update_status:
        result = asyncio.run(ReconstructionManager.get_task_status("task-id"))

    assert result["status"] == ReconstructionStatus.SUCCESS
    assert result["progress"] == 100
    assert result["current_stage"] == "完成"
    assert result["time_updated"] == completed_at.isoformat()
    update_status.assert_not_awaited()


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
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.run_sync", AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs))), \
         patch("csrcqsf.biz.railwayparts.reconstruction_manager.Items.update_obj_url", AsyncMock(side_effect=RuntimeError("pg failed"))), \
         patch(
             "csrcqsf.biz.railwayparts.reconstruction_manager._get_minio_helpers",
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
