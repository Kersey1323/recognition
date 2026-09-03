"""将分割结果整理为前端可直接加载的 Viewer360 图片 Grid。"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np
from PIL import Image

from csrcqsf.modules.railway_parts.services.viewer360_models import (
    Viewer360Config,
    ViewerGridResult,
    ViewerRow,
)


class ViewerGridValidationError(ValueError):
    def __init__(
        self,
        failures: Sequence[str],
        *,
        user_message: str | None = None,
    ):
        self.failures = tuple(failures)
        self.user_message = user_message or (
            "Viewer360 图像处理结果未通过校验，请重新采集后重试"
        )
        super().__init__("; ".join(self.failures))


def build_source_indices(frame_count: int, *, phase_direction: int) -> list[int]:
    if frame_count < 1:
        raise ValueError("frame_count must be positive")
    if phase_direction not in {-1, 1}:
        raise ValueError("phase_direction must be -1 or 1")
    # 相邻采集角度的转盘方向相反，统一映射后前端横向拖动方向保持一致。
    return [(phase_direction * index) % frame_count for index in range(frame_count)]


def retain_primary_mask_component(mask: np.ndarray) -> tuple[np.ndarray, dict[str, int]]:
    if mask.ndim != 2 or not np.any(mask):
        raise ValueError("Mask must be a non-empty grayscale image")
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        (mask > 0).astype(np.uint8), connectivity=8
    )
    areas = stats[1:, cv2.CC_STAT_AREA]
    label = int(np.argmax(areas)) + 1
    cleaned = np.where(labels == label, 255, 0).astype(np.uint8)
    return cleaned, {
        "component_count": count - 1,
        "kept_component_count": 1,
        "removed_area": int(areas.sum() - areas[label - 1]),
    }


def _mask_stats(mask: np.ndarray) -> dict[str, object]:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError("Mask must not be empty")
    left, right = int(xs.min()), int(xs.max())
    top, bottom = int(ys.min()), int(ys.max())
    return {
        "bbox": [left, top, right, bottom],
        "center_x": (left + right) / 2.0,
        "center_y": (top + bottom) / 2.0,
    }


def _sequence(directory: Path, suffix: str) -> list[Path]:
    return sorted(directory.glob(f"frame_*{suffix}")) if directory.is_dir() else []


def _preflight(rows: Sequence[ViewerRow]) -> tuple[list[ViewerRow], int, tuple[int, int]]:
    failures: list[str] = []
    empty_mask_counts: dict[int, int] = {}
    ordered = sorted(rows, key=lambda item: item.row_index)
    if not ordered:
        failures.append("Viewer Grid requires at least one row")
    row_indexes = [item.row_index for item in ordered]
    if len(row_indexes) != len(set(row_indexes)):
        failures.append("Viewer row indexes must be unique")

    frame_count: int | None = None
    image_size: tuple[int, int] | None = None
    for row in ordered:
        rgba_paths = _sequence(row.rgba_dir, ".png")
        mask_paths = _sequence(row.mask_dir, ".png")
        if frame_count is None:
            frame_count = len(rgba_paths)
        if not rgba_paths or len(rgba_paths) != frame_count or len(mask_paths) != frame_count:
            failures.append(f"{row.row_id} frame sequence is incomplete")
            continue
        expected_names = [f"frame_{index:04d}.png" for index in range(1, frame_count + 1)]
        if [path.name for path in rgba_paths] != expected_names or [path.name for path in mask_paths] != expected_names:
            failures.append(f"{row.row_id} frame sequence is not contiguous")
        for rgba_path, mask_path in zip(rgba_paths, mask_paths):
            with Image.open(rgba_path) as rgba_image:
                rgba_size = rgba_image.size
            mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
            if mask is None:
                failures.append(f"unreadable mask: {mask_path}")
                continue
            if not np.any(mask):
                failures.append(f"empty mask: {mask_path}")
                empty_mask_counts[row.row_index] = (
                    empty_mask_counts.get(row.row_index, 0) + 1
                )
            if rgba_size != (mask.shape[1], mask.shape[0]):
                failures.append(f"RGBA/mask dimensions differ: {rgba_path}")
            if image_size is None:
                image_size = rgba_size
            elif rgba_size != image_size:
                failures.append(f"Viewer image dimensions differ: {rgba_path}")
    if failures:
        empty_mask_total = sum(empty_mask_counts.values())
        user_message = None
        if empty_mask_total and empty_mask_total == len(failures):
            # 前端只需要知道失败角度和数量；本地文件路径保留在异常明细中供日志排查。
            angle_summary = "、".join(
                f"第{row_index}个角度有{count}帧未识别到配件"
                for row_index, count in sorted(empty_mask_counts.items())
            )
            user_message = (
                f"配件分割不完整：{angle_summary}，请重新采集对应角度后重试"
            )
        raise ViewerGridValidationError(failures, user_message=user_message)
    return ordered, int(frame_count or 0), image_size or (0, 0)


def _shared_center(mask_paths: Sequence[Path]) -> tuple[float, float]:
    centers = []
    for path in mask_paths:
        mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise ValueError(f"unreadable mask: {path}")
        cleaned, _ = retain_primary_mask_component(mask)
        stats = _mask_stats(cleaned)
        centers.append((float(stats["center_x"]), float(stats["center_y"])))
    return (
        float(np.median([value[0] for value in centers])),
        float(np.median([value[1] for value in centers])),
    )


def export_viewer_grid(
    rows: Sequence[ViewerRow],
    output_dir: Path,
    config: Viewer360Config,
    *,
    fingerprint: str,
    target_center: tuple[float, float] | None = None,
) -> ViewerGridResult:
    """生成一套完整版本；任意图片不合格时整套结果都不能发布。"""
    ordered, frame_count, image_size = _preflight(rows)
    row_centers = {
        row.row_id: _shared_center(_sequence(row.mask_dir, ".png")) for row in ordered
    }
    resolved_center = target_center or (
        float(np.median([center[0] for center in row_centers.values()])),
        float(np.median([center[1] for center in row_centers.values()])),
    )
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f"Viewer output already exists: {output}")
    output.mkdir(parents=True)

    row_payloads: list[dict[str, object]] = []
    frame_payloads: list[dict[str, object]] = []
    aligned_centers: list[tuple[float, float]] = []
    aligned_row_axes: list[tuple[float, float]] = []
    image_paths: list[str] = []
    try:
        for row in ordered:
            rgba_paths = _sequence(row.rgba_dir, ".png")
            mask_paths = _sequence(row.mask_dir, ".png")
            source_indices = build_source_indices(
                frame_count, phase_direction=row.phase_direction
            )
            before_center = row_centers[row.row_id]
            translation = (
                resolved_center[0] - before_center[0],
                resolved_center[1] - before_center[1],
            )
            matrix = np.asarray(
                [[1.0, 0.0, translation[0]], [0.0, 1.0, translation[1]]],
                dtype=np.float32,
            )
            row_output = output / "images" / row.row_id
            row_output.mkdir(parents=True)
            row_frame_centers: list[tuple[float, float]] = []
            for grid_index, source_index in enumerate(source_indices, start=1):
                rgba = np.asarray(Image.open(rgba_paths[source_index]).convert("RGBA")).copy()
                mask = cv2.imread(str(mask_paths[source_index]), cv2.IMREAD_GRAYSCALE)
                if mask is None:
                    raise ViewerGridValidationError([f"unreadable mask: {mask_paths[source_index]}"])
                mask, cleanup = retain_primary_mask_component(mask)
                rgba[:, :, 3] = mask
                normalized = cv2.warpAffine(
                    rgba,
                    matrix,
                    image_size,
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=(0, 0, 0, 0),
                )
                normalized_mask = cv2.warpAffine(
                    mask,
                    matrix,
                    image_size,
                    flags=cv2.INTER_NEAREST,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=0,
                )
                normalized[:, :, 3] = normalized_mask
                stats = _mask_stats(normalized_mask)
                center = (float(stats["center_x"]), float(stats["center_y"]))
                aligned_centers.append(center)
                row_frame_centers.append(center)
                target = row_output / f"frame_{grid_index:04d}.webp"
                Image.fromarray(normalized).save(
                    target,
                    format="WEBP",
                    quality=config.webp_quality,
                    method=6,
                    exact=True,
                )
                with Image.open(target) as encoded:
                    decoded = encoded.convert("RGBA")
                    if decoded.size != image_size or decoded.getchannel("A").getextrema()[1] == 0:
                        raise ViewerGridValidationError([f"Invalid WebP alpha or dimensions: {target}"])
                relative = f"images/{row.row_id}/{target.name}"
                image_paths.append(relative)
                frame_payloads.append(
                    {
                        "row_id": row.row_id,
                        "grid_index": grid_index - 1,
                        "source_index": source_index,
                        "output": relative,
                        "mask_cleanup": cleanup,
                    }
                )
            axis_after = (
                float(np.median([center[0] for center in row_frame_centers])),
                float(np.median([center[1] for center in row_frame_centers])),
            )
            aligned_row_axes.append(axis_after)
            row_payloads.append(
                {
                    "id": row.row_id,
                    "row_index": row.row_index,
                    "start_seconds": row.start_seconds,
                    "end_seconds": row.end_seconds,
                    "phase_direction": row.phase_direction,
                    "source_indices": source_indices,
                    "axis_center_before": before_center,
                    "axis_center_after": axis_after,
                    "translation": {"tx": translation[0], "ty": translation[1]},
                }
            )

        diagonal = max(math.hypot(*image_size), 1.0)
        axis_distances = [
            math.hypot(x - resolved_center[0], y - resolved_center[1])
            for x, y in aligned_row_axes
        ]
        frame_bbox_distances = [
            math.hypot(x - resolved_center[0], y - resolved_center[1])
            for x, y in aligned_centers
        ]
        p95_pixels = float(np.quantile(axis_distances, 0.95))
        p95_ratio = p95_pixels / diagonal
        frame_bbox_center_p95_pixels = float(
            np.quantile(frame_bbox_distances, 0.95)
        )
        frame_bbox_center_p95_ratio = frame_bbox_center_p95_pixels / diagonal

        # 旋转时非对称配件的包围框中心会自然变化；发布校验只约束各采集行的
        # 对齐中轴，逐帧中心偏移保留为诊断数据，避免把正常旋转误判为对齐失败。
        if p95_ratio > config.center_p95_ratio:
            raise ViewerGridValidationError(
                [
                    f"Normalized center P95 ratio {p95_ratio:.6f} exceeds "
                    f"{config.center_p95_ratio:.6f}"
                ]
            )
        manifest = {
            "schema_version": 1,
            "pipeline": "viewer360",
            "amount_x": frame_count,
            "amount_y": len(ordered),
            "index_base": 0,
            "rows": row_payloads,
            "image_list_grid": image_paths,
            "fingerprint": fingerprint,
        }
        manifest_path = output / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        validation = {
            "passed": True,
            "amount_x": frame_count,
            "amount_y": len(ordered),
            "image_count": len(image_paths),
            "image_size": {"width": image_size[0], "height": image_size[1]},
            "center": {
                "method": "per_row_median_bbox_center",
                "target_x": resolved_center[0],
                "target_y": resolved_center[1],
                "p95_pixels": p95_pixels,
                "p95_ratio": p95_ratio,
                "limit_ratio": config.center_p95_ratio,
                "frame_bbox_center_p95_pixels": frame_bbox_center_p95_pixels,
                "frame_bbox_center_p95_ratio": frame_bbox_center_p95_ratio,
            },
            "rows": row_payloads,
            "frames": frame_payloads,
        }
        return ViewerGridResult(
            output_dir=output,
            manifest_path=manifest_path,
            amount_x=frame_count,
            amount_y=len(ordered),
            target_center=resolved_center,
            validation=validation,
        )
    except Exception:
        # 未通过完整校验的目录不允许被后续发布阶段误识别为正式结果。
        shutil.rmtree(output, ignore_errors=True)
        raise
