from pathlib import Path

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
