"""将分割结果或兜底原图整理为前端可直接加载的 Viewer360 图片 Grid。"""

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
        original_paths = _sequence(row.original_dir, ".jpg")
        mask_paths = _sequence(row.mask_dir, ".png")
        if frame_count is None:
            frame_count = len(original_paths)
        if (
            not original_paths
            or len(original_paths) != frame_count
            or len(mask_paths) != frame_count
        ):
            failures.append(f"{row.row_id} frame sequence is incomplete")
            continue
        expected_original_names = [
            f"frame_{index:04d}.jpg" for index in range(1, frame_count + 1)
        ]
        expected_mask_names = [
            f"frame_{index:04d}.png" for index in range(1, frame_count + 1)
        ]
        if (
            [path.name for path in original_paths] != expected_original_names
            or [path.name for path in mask_paths] != expected_mask_names
        ):
            failures.append(f"{row.row_id} frame sequence is not contiguous")
        for original_path, mask_path in zip(original_paths, mask_paths):
            with Image.open(original_path) as original_image:
                original_size = original_image.size
            mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
            if mask is None:
                failures.append(f"unreadable mask: {mask_path}")
                continue
            if not np.any(mask):
                failures.append(f"empty mask: {mask_path}")
                empty_mask_counts[row.row_index] = (
                    empty_mask_counts.get(row.row_index, 0) + 1
                )
            if original_size != (mask.shape[1], mask.shape[0]):
                failures.append(f"original/mask dimensions differ: {original_path}")
            if image_size is None:
                image_size = original_size
            elif original_size != image_size:
                failures.append(f"Viewer image dimensions differ: {original_path}")
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


def _preflight_original_rows(
    rows: Sequence[ViewerRow],
) -> tuple[list[ViewerRow], int, tuple[int, int]]:
    failures: list[str] = []
    ordered = sorted(rows, key=lambda item: item.row_index)
    if not ordered:
        failures.append("Viewer original Grid requires at least one row")
    row_indexes = [item.row_index for item in ordered]
    if len(row_indexes) != len(set(row_indexes)):
        failures.append("Viewer original row indexes must be unique")

    frame_count: int | None = None
    image_size: tuple[int, int] | None = None
    for row in ordered:
        original_paths = (
            _sequence(row.original_dir, ".jpg") if row.original_dir is not None else []
        )
        if frame_count is None:
            frame_count = len(original_paths)
        if not original_paths or len(original_paths) != frame_count:
            failures.append(f"{row.row_id} original frame sequence is incomplete")
            continue
        expected_names = [
            f"frame_{index:04d}.jpg" for index in range(1, frame_count + 1)
        ]
        if [path.name for path in original_paths] != expected_names:
            failures.append(f"{row.row_id} original frame sequence is not contiguous")
        for path in original_paths:
            try:
                with Image.open(path) as image:
                    size = image.size
                    image.verify()
            except Exception:
                failures.append(f"unreadable original frame: {path}")
                continue
            if image_size is None:
                image_size = size
            elif size != image_size:
                failures.append(f"Viewer original image dimensions differ: {path}")
    if failures:
        raise ValueError("; ".join(failures))
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
            original_paths = _sequence(row.original_dir, ".jpg")
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
                # 模型服务只返回 Mask；源帧保留在主服务本地，用于合成最终透明图。
                rgba = np.asarray(
                    Image.open(original_paths[source_index]).convert("RGBA")
                ).copy()
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

        # 中轴偏差可能来自正常视角变化，透明分割图仍可用于展示；超限结果带上
        # fallback 标记供后续质量重建，不因这一项单独切换为原始帧。
        alignment_within_limit = p95_ratio <= config.center_p95_ratio
        fallback_reason = None
        if not alignment_within_limit:
            fallback_reason = (
                f"分割图中心对齐偏差较大：P95={p95_ratio:.6f}，"
                f"阈值={config.center_p95_ratio:.6f}；已继续发布分割结果"
            )
        manifest = {
            "schema_version": 1,
            "pipeline": "viewer360",
            "render_mode": "segmented",
            "fallback_reason": fallback_reason,
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
            "fallback_reason": fallback_reason,
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
                "within_limit": alignment_within_limit,
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


def export_original_viewer_grid(
    rows: Sequence[ViewerRow],
    output_dir: Path,
    config: Viewer360Config,
    *,
    fingerprint: str,
    fallback_reason: str,
) -> ViewerGridResult:
    """分割结果不可用时，将全部角度的原始帧作为一套完整结果发布。"""
    ordered, frame_count, image_size = _preflight_original_rows(rows)
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f"Viewer output already exists: {output}")
    output.mkdir(parents=True)

    row_payloads: list[dict[str, object]] = []
    image_paths: list[str] = []
    try:
        for row in ordered:
            original_paths = _sequence(row.original_dir, ".jpg")
            source_indices = build_source_indices(
                frame_count, phase_direction=row.phase_direction
            )
            row_output = output / "images" / row.row_id
            row_output.mkdir(parents=True)
            for grid_index, source_index in enumerate(source_indices, start=1):
                target = row_output / f"frame_{grid_index:04d}.webp"
                with Image.open(original_paths[source_index]) as source:
                    source.convert("RGB").save(
                        target,
                        format="WEBP",
                        quality=config.webp_quality,
                        method=6,
                    )
                relative = f"images/{row.row_id}/{target.name}"
                image_paths.append(relative)
            row_payloads.append(
                {
                    "id": row.row_id,
                    "row_index": row.row_index,
                    "start_seconds": row.start_seconds,
                    "end_seconds": row.end_seconds,
                    "phase_direction": row.phase_direction,
                    "source_indices": source_indices,
                }
            )

        manifest = {
            "schema_version": 1,
            "pipeline": "viewer360",
            "render_mode": "original",
            "fallback_reason": fallback_reason,
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
        target_center = (image_size[0] / 2.0, image_size[1] / 2.0)
        return ViewerGridResult(
            output_dir=output,
            manifest_path=manifest_path,
            amount_x=frame_count,
            amount_y=len(ordered),
            target_center=target_center,
            validation={
                "passed": True,
                "render_mode": "original",
                "fallback_reason": fallback_reason,
                "amount_x": frame_count,
                "amount_y": len(ordered),
                "image_count": len(image_paths),
                "image_size": {"width": image_size[0], "height": image_size[1]},
                "rows": row_payloads,
            },
        )
    except Exception:
        # 原图兜底也必须整套生成成功，残缺目录不能进入 OSS 发布阶段。
        shutil.rmtree(output, ignore_errors=True)
        raise
