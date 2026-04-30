from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


SUCCESS_LOG = Path("logs/reconstruction/0bde2757-8912-4c8d-a38f-9dcd2ec8ce1d.log")
TURNTABLE_FPS6_LOG = Path("logs/reconstruction/04dc1193-67a1-458c-84c9-61ec320b2dda.log")
TURNTABLE_FPS1_LOG = Path("logs/reconstruction/c84a9c68-b514-42be-a5c3-3ca6e1588459.log")

SUCCESS_RENDER_ROOT = Path(
    "csrcqsf/biz/railwayparts/reconstruction_server/output/螺栓M8X22/train/ours_5000"
)
TURNTABLE_FPS1_RENDER_ROOT = Path(
    "csrcqsf/biz/railwayparts/reconstruction_server/output/20260430091139_支撑架/train/ours_30000"
)

TURNTABLE_FPS6_INPUT_FRAME = Path(
    "csrcqsf/biz/railwayparts/reconstruction_server/data/20260429174803_支撑架/input/frame_0706.jpg"
)
TURNTABLE_FPS6_UNDISTORTED_FRAME = Path(
    "csrcqsf/biz/railwayparts/reconstruction_server/data/20260429174803_支撑架/images/frame_0706.png"
)


@dataclass
class ReconstructionMetrics:
    raw_frames: int
    selected_frames: int
    registered_images: int
    sparse_points: int
    init_points: int
    colmap_sec: float


@dataclass
class AlignmentStats:
    count: int
    iou_mean: float
    iou_median: float
    area_ratio_mean: float
    area_ratio_median: float


def _require_paths(*paths: Path) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        pytest.skip(f"diagnostic artifacts not available: {missing}")


def _parse_metric(text: str, pattern: str, cast):
    match = re.search(pattern, text)
    assert match is not None, f"pattern not found: {pattern}"
    groups = match.groups()
    if len(groups) == 1:
        return cast(groups[0])
    return tuple(cast(group) for group in groups)


def _read_reconstruction_metrics(log_path: Path) -> ReconstructionMetrics:
    _require_paths(log_path)
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    raw_frames = _parse_metric(text, r"共提取 (\d+) 帧", int)
    selected_frames = _parse_metric(text, r"最终选定 (\d+) 帧", int)
    registered_images, sparse_points = _parse_metric(
        text,
        r"Reconstruction with (\d+) images and (\d+) points",
        int,
    )
    init_points = _parse_metric(text, r"Number of points at initialisation :\s+(\d+)", int)
    colmap_sec = _parse_metric(text, r"COLMAP 处理 .*耗时: ([0-9.]+)s", float)
    return ReconstructionMetrics(
        raw_frames=raw_frames,
        selected_frames=selected_frames,
        registered_images=registered_images,
        sparse_points=sparse_points,
        init_points=init_points,
        colmap_sec=colmap_sec,
    )


def _foreground_mask(image_path: Path) -> np.ndarray:
    arr = np.array(Image.open(image_path).convert("RGB"))
    # Current render/gt diagnostics use black background, so any non-black pixel
    # is treated as foreground.
    return np.any(arr > 16, axis=2)


def _compute_alignment_stats(render_root: Path) -> AlignmentStats:
    _require_paths(render_root / "gt", render_root / "renders")
    ious: list[float] = []
    area_ratios: list[float] = []

    for gt_path in sorted((render_root / "gt").glob("*.png")):
        render_path = render_root / "renders" / gt_path.name
        if not render_path.exists():
            continue

        gt_mask = _foreground_mask(gt_path)
        render_mask = _foreground_mask(render_path)

        inter = np.logical_and(gt_mask, render_mask).sum()
        union = np.logical_or(gt_mask, render_mask).sum()
        iou = inter / union if union else 1.0

        gt_area = gt_mask.sum()
        render_area = render_mask.sum()
        area_ratio = min(gt_area, render_area) / max(gt_area, render_area) if max(gt_area, render_area) else 1.0

        ious.append(float(iou))
        area_ratios.append(float(area_ratio))

    assert ious, f"no gt/render pairs found under {render_root}"
    return AlignmentStats(
        count=len(ious),
        iou_mean=float(np.mean(ious)),
        iou_median=float(np.median(ious)),
        area_ratio_mean=float(np.mean(area_ratios)),
        area_ratio_median=float(np.median(area_ratios)),
    )


def test_turntable_diagnostic_lower_fps_recovers_colmap_registration() -> None:
    fps6 = _read_reconstruction_metrics(TURNTABLE_FPS6_LOG)
    fps1 = _read_reconstruction_metrics(TURNTABLE_FPS1_LOG)

    assert fps1.raw_frames < fps6.raw_frames
    assert fps1.selected_frames < fps6.selected_frames

    # Lowering fps from 6 to 1 should dramatically improve the usable COLMAP
    # reconstruction for this turntable capture.
    assert fps1.registered_images > fps6.registered_images * 10
    assert fps1.sparse_points > fps6.sparse_points * 100
    assert fps1.init_points == fps1.sparse_points
    assert fps1.colmap_sec < fps6.colmap_sec


def test_turntable_diagnostic_fps6_colmap_collapse_produces_tiny_undistorted_views() -> None:
    _require_paths(TURNTABLE_FPS6_INPUT_FRAME, TURNTABLE_FPS6_UNDISTORTED_FRAME)

    input_size = Image.open(TURNTABLE_FPS6_INPUT_FRAME).size
    undistorted_size = Image.open(TURNTABLE_FPS6_UNDISTORTED_FRAME).size

    assert input_size == (1600, 900)
    assert undistorted_size == (320, 344)
    assert undistorted_size[0] < input_size[0] / 3
    assert undistorted_size[1] < input_size[1] / 2


def test_turntable_diagnostic_fps1_still_has_poor_gt_render_alignment_vs_orbit_capture() -> None:
    orbit = _compute_alignment_stats(SUCCESS_RENDER_ROOT)
    turntable = _compute_alignment_stats(TURNTABLE_FPS1_RENDER_ROOT)

    assert orbit.count == 67
    assert orbit.iou_mean > 0.95
    assert orbit.area_ratio_mean > 0.95

    # Even after reducing fps, the current pipeline still learns the turntable
    # object much worse than a normal orbit-style capture.
    assert turntable.count == 226
    assert turntable.iou_mean < 0.8
    assert turntable.area_ratio_mean < 0.8
    assert turntable.iou_mean < orbit.iou_mean - 0.3
