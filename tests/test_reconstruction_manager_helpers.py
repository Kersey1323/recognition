from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

from csrcqsf.biz.railwayparts.reconstruction_manager import ReconstructionManager


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
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "SAM3_MODEL_PATH" in str(exc.detail)
    else:
        raise AssertionError("missing SAM3_MODEL_PATH should raise HTTPException")


def test_resolve_record_ply_path_prefers_local_ply_url():
    record = SimpleNamespace(
        ply_url="/tmp/local-point-cloud.ply",
        output_path="/tmp/output",
        iterations=10000,
    )

    assert ReconstructionManager._resolve_record_ply_path(record) == "/tmp/local-point-cloud.ply"


def test_resolve_record_ply_path_builds_path_from_output_dir():
    record = SimpleNamespace(
        ply_url=None,
        output_path="/tmp/output",
        iterations=10000,
    )

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
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "原始视频" in str(exc.detail)
    else:
        raise AssertionError("missing source video should raise HTTPException")


def test_page_to_limit_offset_converts_page_and_page_size():
    assert ReconstructionManager._page_to_limit_offset(page=1, page_size=10) == (10, 0)
    assert ReconstructionManager._page_to_limit_offset(page=3, page_size=10) == (10, 20)


def test_build_video_run_name_uses_timestamp_and_item_name():
    run_name = ReconstructionManager._build_video_run_name("橡胶套")

    assert run_name.endswith("_橡胶套")
    assert len(run_name.split("_", 1)[0]) == 14
