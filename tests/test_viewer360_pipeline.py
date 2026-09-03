import asyncio
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from PIL import Image
import pytest

from csrcqsf.modules.railway_parts.services.viewer360_models import (
    Viewer360Config,
    ViewerSegment,
)
from csrcqsf.modules.railway_parts.services.viewer360_grid import (
    ViewerGridValidationError,
)
from csrcqsf.modules.railway_parts.services.viewer360_pipeline import (
    Viewer360Pipeline,
    Viewer360PipelineError,
)


class FakeStorage:
    def __init__(self):
        self.copied_rows = []
        self.published = []
        self.source_manifest = None

    async def download_source_video(self, source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"video")
        return destination

    async def copy_row(self, **kwargs):
        self.copied_rows.append(kwargs)
        return kwargs["frame_count"]

    async def read_json(self, object_name):
        return self.source_manifest

    async def publish(self, publish_dir, *, item_id, task_id):
        self.published.append((Path(publish_dir), item_id, task_id))
        return f"viewer360/{item_id}/{task_id}/manifest.json"

    async def verify_manifest_objects(self, manifest_object, manifest):
        return len(manifest["image_list_grid"])


class FakeModelClient:
    def __init__(self):
        self.calls = []

    async def segment_video_frames(
        self,
        frame_paths,
        *,
        request_id,
        angle_id,
        destination,
        timeout_seconds,
    ):
        self.calls.append((request_id, angle_id, len(frame_paths)))
        payload = np.zeros((20, 30, 4), dtype=np.uint8)
        row_number = int(angle_id[-2:])
        left = 5 if row_number == 1 else 17
        payload[7:12, left : left + 5, :] = 255
        png = destination.parent / f"{angle_id}.png"
        Image.fromarray(payload).save(png)
        with ZipFile(destination, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"frame_count": len(frame_paths)}))
            for index in range(1, len(frame_paths) + 1):
                archive.write(png, f"masks/frame_{index:04d}.png")
                archive.write(png, f"rgba/frame_{index:04d}.png")
        return destination


def _config(tmp_path):
    return Viewer360Config(
        work_root=tmp_path / "work",
        rotation_seconds=1,
        transition_seconds=0,
        row_count=2,
        row_directions=(1, -1),
        fps=1,
        image_size=30,
        webp_quality=90,
        center_p95_ratio=0.05,
    )


def _extract(_video, segment, row_dir, _config):
    original = row_dir / "original"
    original.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(1, segment.expected_frames + 1):
        path = original / f"frame_{index:04d}.jpg"
        Image.fromarray(np.zeros((20, 30, 3), dtype=np.uint8)).save(path, "JPEG")
        paths.append(path)
    return tuple(paths)


def _task(task_id="task-new", retry_mode="none", rows=None):
    return {
        "task_id": task_id,
        "item_id": 12,
        "source_video_object": "videos/source.mp4",
        "source_video_updated_at": None,
        "retry_mode": retry_mode,
        "retry_rows_json": rows,
    }


def test_resume_reuses_checkpoint_from_same_task_directory(tmp_path: Path):
    pipeline = Viewer360Pipeline(_config(tmp_path))
    row_dir = tmp_path / "work" / "task-new" / "rows" / "row_01"
    for directory in ("masks", "rgba"):
        target = row_dir / "segmentation" / directory
        target.mkdir(parents=True)
        for index in range(1, 3):
            (target / f"frame_{index:04d}.png").write_bytes(b"checkpoint")
    segment = ViewerSegment(
        row_index=1,
        start_seconds=0.0,
        end_seconds=1.0,
        expected_frames=2,
        phase_direction=1,
    )

    assert pipeline._reuse_resume_row("task-new", row_dir, segment) is True


def test_pipeline_builds_and_publishes_complete_grid(tmp_path: Path):
    storage = FakeStorage()
    model = FakeModelClient()
    updates = []
    pipeline = Viewer360Pipeline(
        _config(tmp_path),
        storage=storage,
        model_client=model,
        probe_duration=lambda _path: 2.0,
        extract_segment=_extract,
    )

    async def run():
        return await pipeline.run(
            _task(),
            progress_callback=lambda payload: _append(updates, payload),
        )

    result = asyncio.run(run())

    assert [call[1] for call in model.calls] == ["angle_01", "angle_02"]
    assert result.amount_x == 1
    assert result.amount_y == 2
    assert result.manifest_object == "viewer360/12/task-new/manifest.json"
    assert [update["current_stage"] for update in updates][0] == "preparing"
    assert updates[0]["fingerprint"] == result.fingerprint
    assert [update["progress"] for update in updates] == sorted(
        update["progress"] for update in updates
    )


async def _append(target, payload):
    target.append(payload)


def test_pipeline_resegments_selected_rows_in_place_and_reuses_source_center(
    tmp_path: Path,
):
    storage = FakeStorage()
    storage.source_manifest = {
        "schema_version": 1,
        "pipeline": "viewer360",
        "amount_x": 1,
        "amount_y": 2,
        "index_base": 0,
        "rows": [
            {"id": "row_01", "row_index": 1},
            {"id": "row_02", "row_index": 2},
        ],
        "image_list_grid": [
            "images/row_01/frame_0001.webp",
            "images/row_02/frame_0001.webp",
        ],
        "fingerprint": "old",
    }
    model = FakeModelClient()
    pipeline = Viewer360Pipeline(
        _config(tmp_path),
        storage=storage,
        model_client=model,
        probe_duration=lambda _path: 2.0,
        extract_segment=_extract,
    )
    source_task = {
        "task_id": "task-new",
        "item_id": 12,
        "manifest_object": "viewer360/12/task-new/manifest.json",
        "amount_x": 1,
        "amount_y": 2,
        "pipeline_metadata_json": {"target_center": [15.0, 10.0]},
    }

    result = asyncio.run(
        pipeline.run(
            _task(retry_mode="resegment_rows", rows=[2]),
            source_task=source_task,
        )
    )

    assert [call[1] for call in model.calls] == ["angle_02"]
    assert storage.copied_rows == []
    assert result.target_center == (15.0, 10.0)
    assert result.amount_y == 2
    assert result.row_states == [
        {"row_index": 1, "status": "reused"},
        {"row_index": 2, "status": "success"},
    ]


def test_pipeline_reports_extraction_failure_stage(tmp_path: Path):
    def fail_extract(*_args):
        raise RuntimeError("ffmpeg failed")

    pipeline = Viewer360Pipeline(
        _config(tmp_path),
        storage=FakeStorage(),
        model_client=FakeModelClient(),
        probe_duration=lambda _path: 2.0,
        extract_segment=fail_extract,
    )

    with pytest.raises(Viewer360PipelineError) as exc_info:
        asyncio.run(pipeline.run(_task()))

    assert exc_info.value.stage == "extracting"
    assert exc_info.value.row_index == 1


def test_pipeline_exposes_business_message_for_grid_validation(
    tmp_path: Path,
    monkeypatch,
):
    def fail_grid(*_args, **_kwargs):
        raise ViewerGridValidationError(
            ["empty mask: /app/state/viewer360-tasks/task-new/frame_0001.png"],
            user_message="配件分割不完整：第1个角度有1帧未识别到配件，请重新采集对应角度后重试",
        )

    monkeypatch.setattr(
        "csrcqsf.modules.railway_parts.services.viewer360_pipeline.export_viewer_grid",
        fail_grid,
    )
    pipeline = Viewer360Pipeline(
        _config(tmp_path),
        storage=FakeStorage(),
        model_client=FakeModelClient(),
        probe_duration=lambda _path: 2.0,
        extract_segment=_extract,
    )

    with pytest.raises(Viewer360PipelineError) as exc_info:
        asyncio.run(pipeline.run(_task()))

    assert exc_info.value.stage == "postprocess"
    assert str(exc_info.value) == (
        "配件分割不完整：第1个角度有1帧未识别到配件，请重新采集对应角度后重试"
    )
    assert "/app/state" not in str(exc_info.value)


def test_pipeline_rejects_incomplete_source_manifest_for_row_retry(tmp_path: Path):
    storage = FakeStorage()
    storage.source_manifest = {
        "schema_version": 1,
        "pipeline": "viewer360",
        "amount_x": 1,
        "amount_y": 2,
        "rows": [{"id": "row_01", "row_index": 1}],
        "image_list_grid": ["images/row_01/frame_0001.webp"],
    }
    pipeline = Viewer360Pipeline(
        _config(tmp_path),
        storage=storage,
        model_client=FakeModelClient(),
        probe_duration=lambda _path: 2.0,
        extract_segment=_extract,
    )
    source_task = {
        "task_id": "task-old",
        "item_id": 12,
        "manifest_object": "viewer360/12/task-old/manifest.json",
        "amount_x": 1,
        "amount_y": 2,
        "pipeline_metadata_json": {"target_center": [15.0, 10.0]},
    }

    with pytest.raises(Viewer360PipelineError) as exc_info:
        asyncio.run(
            pipeline.run(
                _task(retry_mode="resegment_rows", rows=[2]),
                source_task=source_task,
            )
        )

    assert exc_info.value.stage == "validation"
    assert "Manifest" in str(exc_info.value)
