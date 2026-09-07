"""Viewer360 从源视频到 OSS 图片 Grid 的后台业务编排。"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from pathlib import Path
import shutil
import subprocess
from typing import Any, Awaitable, Callable

import anyio

from csrcqsf.infra.external.model_client import ModelServiceClient, get_model_client
from csrcqsf.modules.railway_parts.services.viewer360_archive import (
    extract_segmentation_archive,
)
from csrcqsf.modules.railway_parts.services.viewer360_grid import (
    ViewerGridValidationError,
    export_original_viewer_grid,
    export_viewer_grid,
)
from csrcqsf.modules.railway_parts.services.viewer360_models import (
    Viewer360Cancelled,
    Viewer360Config,
    Viewer360PipelineResult,
    ViewerRow,
    ViewerSegment,
    resolve_viewer_segments,
)
from csrcqsf.modules.railway_parts.services.viewer360_storage_service import (
    Viewer360StorageService,
)


ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]
CancelCheck = Callable[[], bool | Awaitable[bool]]
ProbeDuration = Callable[[Path], float]
ExtractSegment = Callable[
    [Path, ViewerSegment, Path, Viewer360Config], tuple[Path, ...]
]

logger = logging.getLogger(__name__)


class Viewer360PipelineError(RuntimeError):
    def __init__(
        self,
        stage: str,
        message: str,
        *,
        row_index: int | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.row_index = row_index


def probe_video_duration(video_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def extract_video_segment(
    video_path: Path,
    segment: ViewerSegment,
    row_dir: Path,
    config: Viewer360Config,
) -> tuple[Path, ...]:
    original = row_dir / "original"
    original.mkdir(parents=True, exist_ok=True)
    expected = tuple(
        original / f"frame_{index:04d}.jpg"
        for index in range(1, segment.expected_frames + 1)
    )
    if all(path.is_file() for path in expected):
        return expected
    if any(original.iterdir()):
        raise RuntimeError(f"Incomplete extraction checkpoint: {original}")
    duration = segment.end_seconds - segment.start_seconds
    effective_fps = segment.expected_frames / duration
    scale = (
        f"scale='min(iw,{config.image_size})':'min(ih,{config.image_size})':"
        "force_original_aspect_ratio=decrease"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-threads",
            str(config.ffmpeg_threads),
            "-ss",
            f"{segment.start_seconds:.6f}",
            "-i",
            str(video_path),
            "-t",
            f"{duration:.6f}",
            "-qscale:v",
            "1",
            "-qmin",
            "1",
            "-vf",
            f"fps={effective_fps:.12g},{scale}",
            str(original / "frame_%04d.jpg"),
        ],
        check=True,
        capture_output=True,
    )
    actual = tuple(sorted(original.glob("frame_*.jpg")))
    if actual != expected:
        raise RuntimeError(
            f"row_{segment.row_index:02d} extracted {len(actual)} frames; "
            f"expected {segment.expected_frames}"
        )
    return expected


def _fingerprint(task: dict[str, Any], config: Viewer360Config) -> str:
    payload = {
        "source_video_object": task["source_video_object"],
        "source_video_updated_at": task.get("source_video_updated_at"),
        "transition_seconds": config.transition_seconds,
        "row_count": config.row_count,
        "row_directions": config.row_directions,
        "frames_per_row": config.frames_per_row,
        "image_size": config.image_size,
        "webp_quality": config.webp_quality,
        "pipeline_version": 2,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_model_request_id(task: dict[str, Any]) -> str:
    """为同一 Viewer360 任务的每次执行生成稳定且互不冲突的模型请求 ID。"""
    task_id = str(task["task_id"])
    started_at = task.get("started_at")
    if started_at is None:
        return task_id
    marker = (
        started_at.isoformat()
        if hasattr(started_at, "isoformat")
        else str(started_at)
    )
    attempt_digest = hashlib.sha256(marker.encode("utf-8")).hexdigest()[:16]
    return f"{task_id}:{attempt_digest}"


def _validate_source_manifest(
    manifest: Any,
    *,
    amount_x: int,
    amount_y: int,
) -> dict[str, Any]:
    """按数据库版本快照校验整套 Grid，防止局部重做继承残缺结果。"""
    if not isinstance(manifest, dict):
        raise ValueError("Viewer360 source Manifest must be an object")
    if manifest.get("pipeline") != "viewer360":
        raise ValueError("Viewer360 source Manifest has an invalid pipeline")
    if manifest.get("amount_x") != amount_x or manifest.get("amount_y") != amount_y:
        raise ValueError("Viewer360 source Manifest dimensions do not match the source task")

    expected_row_ids = [f"row_{index:02d}" for index in range(1, amount_y + 1)]
    rows = manifest.get("rows")
    if not isinstance(rows, list) or [row.get("id") for row in rows if isinstance(row, dict)] != expected_row_ids:
        raise ValueError("Viewer360 source Manifest rows are incomplete")

    expected_images = {
        f"images/row_{row_index:02d}/frame_{frame_index:04d}.webp"
        for row_index in range(1, amount_y + 1)
        for frame_index in range(1, amount_x + 1)
    }
    image_paths = manifest.get("image_list_grid")
    if (
        not isinstance(image_paths, list)
        or len(image_paths) != len(expected_images)
        or set(image_paths) != expected_images
    ):
        raise ValueError("Viewer360 source Manifest image grid is incomplete")
    return manifest


class Viewer360Pipeline:
    def __init__(
        self,
        config: Viewer360Config,
        *,
        storage: Viewer360StorageService | None = None,
        model_client: ModelServiceClient | None = None,
        probe_duration: ProbeDuration = probe_video_duration,
        extract_segment: ExtractSegment = extract_video_segment,
        model_timeout_seconds: int = 600,
    ) -> None:
        self.config = config
        self.storage = storage or Viewer360StorageService()
        self.model_client = model_client or get_model_client()
        self.probe_duration = probe_duration
        self.extract_segment = extract_segment
        self.model_timeout_seconds = model_timeout_seconds

    async def _emit(
        self,
        callback: ProgressCallback | None,
        *,
        stage: str,
        progress: int,
        **values,
    ) -> None:
        if callback is not None:
            await callback(
                {"current_stage": stage, "progress": progress, **values}
            )

    async def _check_cancelled(self, check: CancelCheck | None) -> None:
        if check is None:
            return
        result = check()
        if inspect.isawaitable(result):
            result = await result
        if result:
            raise Viewer360Cancelled("Viewer360 task was cancelled")

    def _reuse_resume_row(
        self,
        source_task_id: str,
        target_row_dir: Path,
        segment: ViewerSegment,
    ) -> bool:
        source = (
            self.config.work_root
            / source_task_id
            / "rows"
            / f"row_{segment.row_index:02d}"
        )
        required = [
            source / "segmentation" / "masks" / f"frame_{index:04d}.png"
            for index in range(1, segment.expected_frames + 1)
        ] + [
            source / "original" / f"frame_{index:04d}.jpg"
            for index in range(1, segment.expected_frames + 1)
        ]
        if not all(path.is_file() for path in required):
            return False
        if source.resolve() == target_row_dir.resolve():
            return True
        shutil.copytree(source, target_row_dir)
        return True

    async def _prepare_row(
        self,
        *,
        model_request_id: str,
        video_path: Path,
        segment: ViewerSegment,
        row_dir: Path,
        allow_resume_from: str | None,
    ) -> ViewerRow:
        if allow_resume_from and self._reuse_resume_row(
            allow_resume_from, row_dir, segment
        ):
            return ViewerRow(
                row_index=segment.row_index,
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                phase_direction=segment.phase_direction,
                mask_dir=row_dir / "segmentation" / "masks",
                original_dir=row_dir / "original",
            )
        try:
            frames = await anyio.to_thread.run_sync(
                self.extract_segment,
                video_path,
                segment,
                row_dir,
                self.config,
            )
        except Exception as exc:
            raise Viewer360PipelineError(
                "extracting",
                str(exc),
                row_index=segment.row_index,
            ) from exc
        result_zip = row_dir / "segmentation.zip"
        try:
            await self.model_client.segment_video_frames(
                frames,
                request_id=model_request_id,
                angle_id=f"angle_{segment.row_index:02d}",
                destination=result_zip,
                timeout_seconds=self.model_timeout_seconds,
            )
        except Exception as exc:
            raise Viewer360PipelineError(
                "model_segmentation",
                str(exc),
                row_index=segment.row_index,
            ) from exc
        try:
            segmentation = await anyio.to_thread.run_sync(
                lambda: extract_segmentation_archive(
                    result_zip,
                    row_dir / "segmentation",
                    expected_frames=segment.expected_frames,
                )
            )
        except Exception as exc:
            raise Viewer360PipelineError(
                "validation",
                str(exc),
                row_index=segment.row_index,
            ) from exc
        return ViewerRow(
            row_index=segment.row_index,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            phase_direction=segment.phase_direction,
            mask_dir=segmentation.mask_paths[0].parent,
            original_dir=frames[0].parent,
        )

    async def _prepare_original_rows(
        self,
        *,
        video_path: Path,
        segments: list[ViewerSegment],
        work_dir: Path,
    ) -> list[ViewerRow]:
        """补齐全部采集角度的原始帧，确保兜底结果不混入分割图片。"""
        rows: list[ViewerRow] = []
        for segment in segments:
            row_dir = work_dir / "rows" / f"row_{segment.row_index:02d}"
            try:
                frames = await anyio.to_thread.run_sync(
                    self.extract_segment,
                    video_path,
                    segment,
                    row_dir,
                    self.config,
                )
            except Exception as exc:
                raise Viewer360PipelineError(
                    "extracting",
                    str(exc),
                    row_index=segment.row_index,
                ) from exc
            rows.append(
                ViewerRow(
                    row_index=segment.row_index,
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                    phase_direction=segment.phase_direction,
                    mask_dir=row_dir / "segmentation" / "masks",
                    original_dir=frames[0].parent,
                )
            )
        return rows

    async def run(
        self,
        task: dict[str, Any],
        *,
        source_task: dict[str, Any] | None = None,
        progress_callback: ProgressCallback | None = None,
        is_cancelled: CancelCheck | None = None,
    ) -> Viewer360PipelineResult:
        task_id = str(task["task_id"])
        model_request_id = build_model_request_id(task)
        item_id = int(task["item_id"])
        retry_mode = task.get("retry_mode") or "none"
        fingerprint = _fingerprint(task, self.config)
        work_dir = self.config.work_root / task_id
        if (
            retry_mode == "resume"
            and source_task is not None
            and source_task.get("fingerprint") != fingerprint
            and work_dir.exists()
        ):
            # 切段协议变化后旧帧不能继续复用，否则新旧帧数会在分割或发布阶段混用。
            await anyio.to_thread.run_sync(shutil.rmtree, work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        # fingerprint 先于耗时阶段落库，失败任务恢复时才能判断本地断点是否仍匹配源视频。
        await self._emit(
            progress_callback,
            stage="preparing",
            progress=1,
            fingerprint=fingerprint,
        )
        await self._check_cancelled(is_cancelled)
        video_path = work_dir / "source_video"
        try:
            await self._emit(progress_callback, stage="downloading_video", progress=5)
            await self.storage.download_source_video(task["source_video_object"], video_path)
            duration = await anyio.to_thread.run_sync(self.probe_duration, video_path)
            segments, ignored_tail = resolve_viewer_segments(self.config, duration)
        except Viewer360Cancelled:
            raise
        except Exception as exc:
            raise Viewer360PipelineError("source_video", str(exc)) from exc

        if retry_mode == "resegment_rows":
            selected = set(int(value) for value in (task.get("retry_rows_json") or []))
            if source_task is None:
                raise Viewer360PipelineError("preparing", "resegment_rows requires a source task")
            source_metadata = source_task.get("pipeline_metadata_json") or {}
            if source_metadata.get("render_mode") == "original":
                # 原图兜底结果没有可复用的透明分割行；要恢复透明模式必须重新校验全部角度。
                selected = {segment.row_index for segment in segments}
        else:
            selected = {segment.row_index for segment in segments}
        row_states = [
            {
                "row_index": segment.row_index,
                "status": "pending" if segment.row_index in selected else "reused",
            }
            for segment in segments
        ]
        total_frames = sum(
            segment.expected_frames for segment in segments if segment.row_index in selected
        )
        await self._emit(
            progress_callback,
            stage="extracting",
            progress=10,
            row_count=len(segments),
            total_frames=total_frames,
            processed_frames=0,
            reused_row_count=len(segments) - len(selected),
            row_states_json=row_states,
        )
        prepared_rows: list[ViewerRow] = []
        processed = 0
        for segment in segments:
            if segment.row_index not in selected:
                continue
            await self._check_cancelled(is_cancelled)
            state = row_states[segment.row_index - 1]
            state["status"] = "segmenting"
            try:
                row = await self._prepare_row(
                    # 前端任务 ID 在重试时保持不变，但模型幂等键按本次执行隔离，
                    # 允许重新抽帧后的 ZIP 内容与上一次不同。
                    model_request_id=model_request_id,
                    video_path=video_path,
                    segment=segment,
                    row_dir=work_dir / "rows" / f"row_{segment.row_index:02d}",
                    allow_resume_from=(
                        str(source_task["task_id"])
                        if (
                            retry_mode == "resume"
                            and source_task is not None
                            and source_task.get("fingerprint") == fingerprint
                        )
                        else None
                    ),
                )
            except Viewer360PipelineError:
                state["status"] = "failed"
                raise
            except Exception as exc:
                state["status"] = "failed"
                raise Viewer360PipelineError(
                    "model_segmentation",
                    str(exc),
                    row_index=segment.row_index,
                ) from exc
            prepared_rows.append(row)
            processed += segment.expected_frames
            state["status"] = "success"
            await self._emit(
                progress_callback,
                stage="segmenting",
                progress=25 + int(50 * processed / max(total_frames, 1)),
                processed_frames=processed,
                row_states_json=row_states,
            )

        await self._check_cancelled(is_cancelled)
        target_center: tuple[float, float] | None = None
        if retry_mode == "resegment_rows":
            metadata = (source_task or {}).get("pipeline_metadata_json") or {}
            center = metadata.get("target_center")
            if not isinstance(center, (list, tuple)) or len(center) != 2:
                raise Viewer360PipelineError("postprocess", "source alignment center is missing")
            target_center = (float(center[0]), float(center[1]))
        await self._emit(progress_callback, stage="postprocessing", progress=75)
        render_mode = "segmented"
        fallback_reason: str | None = None
        try:
            selected_output = work_dir / "selected_grid"
            grid = await anyio.to_thread.run_sync(
                lambda: export_viewer_grid(
                    prepared_rows,
                    selected_output,
                    self.config,
                    fingerprint=fingerprint,
                    target_center=target_center,
                )
            )
        except ViewerGridValidationError as exc:
            logger.warning(
                "Viewer360 分割结果校验失败，整套切换为原始帧: task_id=%s, details=%s",
                task_id,
                "; ".join(exc.failures),
            )
            render_mode = "original"
            fallback_reason = exc.user_message
            try:
                # 任一角度分割不可用时统一发布全部原图，避免前端混合两种视觉结果。
                original_rows = await self._prepare_original_rows(
                    video_path=video_path,
                    segments=segments,
                    work_dir=work_dir,
                )
                grid = await anyio.to_thread.run_sync(
                    lambda: export_original_viewer_grid(
                        original_rows,
                        selected_output,
                        self.config,
                        fingerprint=fingerprint,
                        fallback_reason=fallback_reason,
                    )
                )
            except Viewer360PipelineError:
                raise
            except Exception as fallback_exc:
                raise Viewer360PipelineError(
                    "postprocess",
                    f"分割结果不可用，原图兜底生成失败: {fallback_exc}",
                ) from fallback_exc
            row_states = [
                {"row_index": segment.row_index, "status": "fallback"}
                for segment in segments
            ]
            total_frames = sum(segment.expected_frames for segment in segments)
            await self._emit(
                progress_callback,
                stage="postprocessing",
                progress=85,
                total_frames=total_frames,
                processed_frames=total_frames,
                reused_row_count=0,
                row_states_json=row_states,
            )
        except Exception as exc:
            raise Viewer360PipelineError("postprocess", str(exc)) from exc

        if render_mode == "segmented" and grid.validation.get("fallback_reason"):
            fallback_reason = str(grid.validation["fallback_reason"])
            row_states = [
                {"row_index": segment.row_index, "status": "fallback"}
                for segment in segments
            ]
            await self._emit(
                progress_callback,
                stage="postprocessing",
                progress=85,
                row_states_json=row_states,
            )

        await self._emit(progress_callback, stage="validating", progress=88)
        publish_dir = work_dir / "publish"
        if publish_dir.exists():
            shutil.rmtree(publish_dir)
        if retry_mode == "resegment_rows" and render_mode != "original":
            source_amount_x = int(source_task["amount_x"])
            source_amount_y = int(source_task["amount_y"])
            if source_amount_y != len(segments):
                raise Viewer360PipelineError(
                    "validation",
                    "Viewer360 source task row count differs from the current capture protocol",
                )
            try:
                source_manifest = _validate_source_manifest(
                    await self.storage.read_json(source_task["manifest_object"]),
                    amount_x=source_amount_x,
                    amount_y=source_amount_y,
                )
            except Exception as exc:
                raise Viewer360PipelineError("validation", str(exc)) from exc
            shutil.copytree(selected_output / "images", publish_dir / "images")
            selected_manifest = json.loads(grid.manifest_path.read_text(encoding="utf-8"))
            if grid.amount_x != source_amount_x:
                raise Viewer360PipelineError(
                    "validation",
                    "resegmented row frame count differs from source Viewer360 result",
                )
            selected_rows = {row["id"]: row for row in selected_manifest["rows"]}
            merged_rows = [selected_rows.get(row.get("id"), row) for row in source_manifest["rows"]]
            manifest = dict(source_manifest)
            manifest.update(
                fingerprint=fingerprint,
                rows=merged_rows,
                amount_x=source_amount_x,
                amount_y=source_amount_y,
                render_mode="segmented",
                fallback_reason=fallback_reason,
            )
            publish_dir.mkdir(parents=True, exist_ok=True)
            (publish_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            for segment in segments:
                if segment.row_index not in selected:
                    if str(source_task["task_id"]) == task_id:
                        continue
                    await self.storage.copy_row(
                        source_item_id=int(source_task["item_id"]),
                        source_task_id=str(source_task["task_id"]),
                        target_item_id=item_id,
                        target_task_id=task_id,
                        row_index=segment.row_index,
                        frame_count=source_amount_x,
                    )
            amount_x = source_amount_x
            amount_y = source_amount_y
        else:
            selected_output.replace(publish_dir)
            manifest = json.loads((publish_dir / "manifest.json").read_text(encoding="utf-8"))
            amount_x = grid.amount_x
            amount_y = grid.amount_y

        await self._check_cancelled(is_cancelled)
        await self._emit(progress_callback, stage="publishing", progress=92)
        try:
            manifest_object = await self.storage.publish(
                publish_dir,
                item_id=item_id,
                task_id=task_id,
            )
            await self.storage.verify_manifest_objects(manifest_object, manifest)
        except Exception as exc:
            raise Viewer360PipelineError("upload_result", str(exc)) from exc
        await self._emit(progress_callback, stage="cleanup", progress=99)
        return Viewer360PipelineResult(
            publish_dir=publish_dir,
            manifest_path=publish_dir / "manifest.json",
            amount_x=amount_x,
            amount_y=amount_y,
            fingerprint=fingerprint,
            target_center=grid.target_center,
            total_frames=total_frames,
            row_states=row_states,
            manifest_object=manifest_object,
            render_mode=render_mode,
            fallback_reason=fallback_reason,
        )
