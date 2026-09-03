import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from csrcqsf.modules.railway_parts.services.viewer360_grid import (
    ViewerGridValidationError,
    build_source_indices,
    export_viewer_grid,
)
from csrcqsf.modules.railway_parts.services.viewer360_models import (
    Viewer360Config,
    ViewerRow,
    resolve_viewer_segments,
)


def _config(tmp_path: Path, **overrides) -> Viewer360Config:
    values = {
        "work_root": tmp_path,
        "rotation_seconds": 25.0,
        "transition_seconds": 2.0,
        "row_count": 4,
        "row_directions": (1, -1, 1, -1),
        "fps": 2.0,
        "image_size": 1600,
        "webp_quality": 90,
        "center_p95_ratio": 0.015,
    }
    values.update(overrides)
    return Viewer360Config(**values)


def _rows(
    root: Path,
    *,
    frame_count: int = 3,
    empty_mask: bool = False,
    mismatched_size: bool = False,
    detached_noise: bool = False,
    varying_frame_center: bool = False,
) -> list[ViewerRow]:
    rows: list[ViewerRow] = []
    for row_index, center in enumerate(((8, 9), (20, 11)), start=1):
        row_root = root / f"row_{row_index:02d}"
        rgba_dir = row_root / "rgba"
        mask_dir = row_root / "masks"
        rgba_dir.mkdir(parents=True)
        mask_dir.mkdir(parents=True)
        for frame_index in range(1, frame_count + 1):
            height = 22 if mismatched_size and row_index == 2 and frame_index == 3 else 20
            width = 30
            mask = np.zeros((height, width), dtype=np.uint8)
            if not (empty_mask and row_index == 1 and frame_index == 1):
                cx, cy = (
                    ((5, 15, 25)[frame_index - 1], 10)
                    if varying_frame_center
                    else center
                )
                mask[cy - 2 : cy + 3, cx - 2 : cx + 3] = 255
                if detached_noise and row_index == 1 and frame_index == 1:
                    mask[9, 27] = 255
            rgba = np.zeros((height, width, 4), dtype=np.uint8)
            rgba[:, :, :3] = (40 * row_index, 100, 180)
            rgba[:, :, 3] = mask
            Image.fromarray(rgba).save(rgba_dir / f"frame_{frame_index:04d}.png")
            assert cv2.imwrite(str(mask_dir / f"frame_{frame_index:04d}.png"), mask)
        rows.append(
            ViewerRow(
                row_index=row_index,
                start_seconds=float((row_index - 1) * 4),
                end_seconds=float((row_index - 1) * 4 + 3),
                phase_direction=1 if row_index == 1 else -1,
                rgba_dir=rgba_dir,
                mask_dir=mask_dir,
            )
        )
    return rows


def test_resolve_viewer_segments_uses_fixed_capture_protocol(tmp_path: Path):
    segments, ignored_tail = resolve_viewer_segments(_config(tmp_path), 106.0)

    assert [(item.start_seconds, item.end_seconds) for item in segments] == [
        (0.0, 25.0),
        (27.0, 52.0),
        (54.0, 79.0),
        (81.0, 106.0),
    ]
    assert [item.expected_frames for item in segments] == [50, 50, 50, 50]
    assert [item.phase_direction for item in segments] == [1, -1, 1, -1]
    assert ignored_tail == 0.0


def test_resolve_viewer_segments_rejects_short_video(tmp_path: Path):
    with pytest.raises(ValueError, match="shorter than required"):
        resolve_viewer_segments(_config(tmp_path), 105.0)


def test_alternating_rows_cover_same_circle_in_opposite_order():
    assert build_source_indices(5, phase_direction=1) == [0, 1, 2, 3, 4]
    assert build_source_indices(5, phase_direction=-1) == [0, 4, 3, 2, 1]


def test_export_writes_only_frontend_assets_and_cleans_mask_noise(tmp_path: Path):
    result = export_viewer_grid(
        _rows(tmp_path / "input", detached_noise=True),
        tmp_path / "publish",
        _config(tmp_path, row_count=2, row_directions=(1, -1), fps=1.0),
        fingerprint="fixture",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["amount_x"] == 3
    assert manifest["amount_y"] == 2
    assert manifest["rows"][1]["source_indices"] == [0, 2, 1]
    assert len(manifest["image_list_grid"]) == 6
    assert sorted(
        path.relative_to(result.output_dir).as_posix()
        for path in result.output_dir.rglob("*")
        if path.is_file()
    ) == ["images/row_01/frame_0001.webp", "images/row_01/frame_0002.webp", "images/row_01/frame_0003.webp", "images/row_02/frame_0001.webp", "images/row_02/frame_0002.webp", "images/row_02/frame_0003.webp", "manifest.json"]
    assert result.validation["frames"][0]["mask_cleanup"]["removed_area"] == 1
    image = Image.open(result.output_dir / manifest["image_list_grid"][0]).convert("RGBA")
    assert image.getchannel("A").getextrema() == (0, 255)


def test_export_reuses_fixed_alignment_center(tmp_path: Path):
    result = export_viewer_grid(
        _rows(tmp_path / "input"),
        tmp_path / "publish",
        _config(tmp_path, row_count=2, row_directions=(1, -1), fps=1.0),
        fingerprint="retry",
        target_center=(15.0, 10.0),
    )

    assert result.target_center == (15.0, 10.0)
    assert result.validation["center"]["target_x"] == 15.0


def test_export_allows_rotation_shape_center_variation_with_aligned_row_axes(
    tmp_path: Path,
):
    result = export_viewer_grid(
        _rows(tmp_path / "input", varying_frame_center=True),
        tmp_path / "publish",
        _config(tmp_path, row_count=2, row_directions=(1, -1), fps=1.0),
        fingerprint="rotating-shape",
    )

    center = result.validation["center"]
    assert center["p95_ratio"] <= 0.015
    assert center["frame_bbox_center_p95_ratio"] > 0.015


def test_export_still_rejects_misaligned_row_axes(tmp_path: Path):
    with pytest.raises(ViewerGridValidationError, match="Normalized center P95 ratio"):
        export_viewer_grid(
            _rows(tmp_path / "input"),
            tmp_path / "publish",
            _config(tmp_path, row_count=2, row_directions=(1, -1), fps=1.0),
            fingerprint="misaligned",
            target_center=(0.0, 0.0),
        )


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"empty_mask": True}, "empty mask"),
        ({"mismatched_size": True}, "dimensions"),
    ],
)
def test_export_rejects_invalid_grid(tmp_path: Path, options: dict, message: str):
    with pytest.raises(ViewerGridValidationError, match=message):
        export_viewer_grid(
            _rows(tmp_path / "input", **options),
            tmp_path / "publish",
            _config(tmp_path, row_count=2, row_directions=(1, -1), fps=1.0),
            fingerprint="invalid",
        )


def test_empty_mask_error_provides_concise_frontend_message(tmp_path: Path):
    with pytest.raises(ViewerGridValidationError) as exc_info:
        export_viewer_grid(
            _rows(tmp_path / "input", empty_mask=True),
            tmp_path / "publish",
            _config(tmp_path, row_count=2, row_directions=(1, -1), fps=1.0),
            fingerprint="invalid",
        )

    assert exc_info.value.user_message == (
        "配件分割不完整：第1个角度有1帧未识别到配件，请重新采集对应角度后重试"
    )
    assert str(tmp_path) not in exc_info.value.user_message
