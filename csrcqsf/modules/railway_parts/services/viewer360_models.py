"""Viewer360 Pipeline 的纯业务模型与固定采集协议。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable


Viewer360ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


class Viewer360Cancelled(RuntimeError):
    """任务收到取消信号，Pipeline 应停止后续处理和发布。"""


@dataclass(frozen=True, slots=True)
class Viewer360Config:
    work_root: Path
    rotation_seconds: float
    transition_seconds: float
    row_count: int = 4
    row_directions: tuple[int, ...] = (1, -1, 1, -1)
    fps: float = 2.0
    image_size: int = 1600
    webp_quality: int = 90
    center_p95_ratio: float = 0.015
    ffmpeg_threads: int = 4
    task_timeout_seconds: int = 1800

    def __post_init__(self) -> None:
        if self.rotation_seconds <= 0:
            raise ValueError("rotation_seconds must be positive")
        if self.transition_seconds < 0:
            raise ValueError("transition_seconds must not be negative")
        if self.row_count < 2:
            raise ValueError("row_count must be at least 2")
        if len(self.row_directions) != self.row_count or any(
            direction not in {-1, 1} for direction in self.row_directions
        ):
            raise ValueError("row_directions must contain one -1/1 value per row")
        if self.fps <= 0 or self.image_size <= 0:
            raise ValueError("fps and image_size must be positive")
        if not 1 <= self.webp_quality <= 100:
            raise ValueError("webp_quality must be in [1, 100]")
        if not 0 < self.center_p95_ratio < 1:
            raise ValueError("center_p95_ratio must be in (0, 1)")


@dataclass(frozen=True, slots=True)
class ViewerSegment:
    row_index: int
    start_seconds: float
    end_seconds: float
    expected_frames: int
    phase_direction: int


@dataclass(frozen=True, slots=True)
class ViewerRow:
    row_index: int
    start_seconds: float
    end_seconds: float
    phase_direction: int
    rgba_dir: Path
    mask_dir: Path

    @property
    def row_id(self) -> str:
        return f"row_{self.row_index:02d}"

    def __post_init__(self) -> None:
        if self.row_index < 1:
            raise ValueError("row_index must be 1-based")
        if self.end_seconds <= self.start_seconds:
            raise ValueError("row end_seconds must be greater than start_seconds")
        if self.phase_direction not in {-1, 1}:
            raise ValueError("phase_direction must be -1 or 1")


@dataclass(frozen=True, slots=True)
class ViewerGridResult:
    output_dir: Path
    manifest_path: Path
    amount_x: int
    amount_y: int
    target_center: tuple[float, float]
    validation: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Viewer360PipelineResult:
    publish_dir: Path
    manifest_path: Path
    amount_x: int
    amount_y: int
    fingerprint: str
    target_center: tuple[float, float]
    total_frames: int
    row_states: list[dict[str, Any]]
    manifest_object: str


def resolve_viewer_segments(
    config: Viewer360Config,
    video_duration: float,
) -> tuple[list[ViewerSegment], float]:
    """按 C 端固定节拍把连续视频切成多个完整垂直角度。"""
    if video_duration < 0:
        raise ValueError("video_duration must not be negative")
    required_duration = (
        config.row_count * config.rotation_seconds
        + (config.row_count - 1) * config.transition_seconds
    )
    if video_duration + 0.25 < required_duration:
        raise ValueError(
            f"Video duration {video_duration:.3f}s is shorter than required duration "
            f"{required_duration:.3f}s"
        )
    expected_frames = round(config.rotation_seconds * config.fps)
    if expected_frames < 1:
        raise ValueError("rotation_seconds and fps must produce at least one frame")

    segments = []
    for offset in range(config.row_count):
        start = offset * (config.rotation_seconds + config.transition_seconds)
        segments.append(
            ViewerSegment(
                row_index=offset + 1,
                start_seconds=start,
                end_seconds=start + config.rotation_seconds,
                expected_frames=expected_frames,
                phase_direction=config.row_directions[offset],
            )
        )
    return segments, max(0.0, video_duration - required_duration)
