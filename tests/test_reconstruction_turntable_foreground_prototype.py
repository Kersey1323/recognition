from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


COLMAP_BIN = shutil.which("colmap") or "colmap"
ALPHA_THRESHOLD = 8
DEFAULT_PROTOTYPE_FRAME_LIMIT = 48
GS3D_PYTHON = "/home/ubuntu/miniconda3/envs/gs3d/bin/python"
RECONSTRUCTION_SERVER_ROOT = Path("csrcqsf/biz/railwayparts/reconstruction_server")
GS3D_DIR = RECONSTRUCTION_SERVER_ROOT / "3dgs"

TURNTABLE_DATA_ROOT = Path(
    "csrcqsf/biz/railwayparts/reconstruction_server/data/20260430091139_支撑架"
)
DEFAULT_OUTPUT_ROOT = Path("logs/reconstruction/turntable_foreground_prototype")


def test_turntable_segmented_frames_have_tiny_foreground_coverage() -> None:
    stats = _collect_alpha_coverage_stats(TURNTABLE_DATA_ROOT / "images")

    assert stats["count"] == 226
    assert stats["mask_ratio_median"] < 0.03
    assert stats["bbox_w_median"] < 0.25
    assert stats["bbox_h_median"] < 0.25


def test_turntable_centered_crop_variant_enlarges_foreground_bbox() -> None:
    before, after = _measure_center_crop_bbox_gain(
        TURNTABLE_DATA_ROOT / "input" / "frame_0096.jpg",
        TURNTABLE_DATA_ROOT / "images" / "frame_0096.png",
    )

    assert before["bbox_w_frac"] < 0.25
    assert before["bbox_h_frac"] < 0.25
    assert after["bbox_w_frac"] > before["bbox_w_frac"] * 2
    assert after["bbox_h_frac"] > before["bbox_h_frac"] * 2


@pytest.mark.skipif(
    os.getenv("RUN_TURNTABLE_FOREGROUND_PROTOTYPE") != "1",
    reason="手动原型实验；运行前请设置 RUN_TURNTABLE_FOREGROUND_PROTOTYPE=1",
)
def test_turntable_foreground_prototype_colmap_progression() -> None:
    frame_limit = int(
        os.getenv("TURNTABLE_FOREGROUND_FRAME_LIMIT", str(DEFAULT_PROTOTYPE_FRAME_LIMIT))
    )
    output_root = Path(
        os.getenv("TURNTABLE_FOREGROUND_OUTPUT_DIR", str(DEFAULT_OUTPUT_ROOT))
    )

    summary = _run_turntable_foreground_prototype(
        output_root=output_root,
        frame_limit=frame_limit,
    )
    results = {item["variant_name"]: item for item in summary["results"]}

    assert results["original_fullframe_exhaustive"]["progress_rank"] == 2
    assert results["original_fullframe_exhaustive"]["registered_images"] > 0

    # Keeping the original large frame and only suppressing the background is
    # still materially weaker than the original background-dominant route.
    assert (
        results["masked_fullframe_exhaustive"]["progress_rank"]
        < results["original_fullframe_exhaustive"]["progress_rank"]
    )
    assert (
        results["masked_fullframe_exhaustive"]["registered_images"]
        < results["original_fullframe_exhaustive"]["registered_images"]
    )

    # Center-cropping the object usually lets COLMAP get farther than plain
    # full-frame masking, but does not yet guarantee a stable sparse model that
    # is as complete as the original background-based route.
    assert (
        results["crop_centered_sequential"]["progress_rank"]
        >= results["masked_fullframe_exhaustive"]["progress_rank"]
    )
    if results["crop_centered_sequential"]["succeeded"]:
        assert (
            results["crop_centered_sequential"]["registered_images"]
            < results["original_fullframe_exhaustive"]["registered_images"]
        )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


@pytest.mark.skipif(
    os.getenv("RUN_TURNTABLE_FOREGROUND_TRAIN_PREVIEW") != "1",
    reason="手动训练预览；运行前请设置 RUN_TURNTABLE_FOREGROUND_TRAIN_PREVIEW=1",
)
def test_turntable_foreground_prototype_train_render_preview() -> None:
    frame_limit = int(
        os.getenv("TURNTABLE_FOREGROUND_FRAME_LIMIT", str(DEFAULT_PROTOTYPE_FRAME_LIMIT))
    )
    iterations = int(os.getenv("TURNTABLE_FOREGROUND_TRAIN_ITERATIONS", "1000"))
    output_root = Path(
        os.getenv("TURNTABLE_FOREGROUND_OUTPUT_DIR", str(DEFAULT_OUTPUT_ROOT))
    )

    summary = _run_turntable_foreground_training_preview(
        output_root=output_root,
        frame_limit=frame_limit,
        iterations=iterations,
    )
    assert summary["runs"], "expected at least one trained prototype run"
    print(json.dumps(summary, ensure_ascii=False, indent=2))


@dataclass
class ColmapPrototypeResult:
    variant_name: str
    strategy: str
    matcher: str
    scene_dir: str
    frame_count: int
    returncode: int
    succeeded: bool
    progress_rank: int
    found_initial_pair: bool
    max_registration_image: int
    registered_images: int
    points: int
    mean_observations_per_image: float | None
    mean_reprojection_error: float | None
    training_scene_ready: bool
    undistorted_images: int
    mapper_stdout_tail: str
    mapper_stderr_tail: str
    commands_log: str


@dataclass
class RenderAlignmentStats:
    count: int
    iou_mean: float
    iou_median: float
    area_ratio_mean: float
    area_ratio_median: float


@dataclass
class TrainingPreviewResult:
    variant_name: str
    scene_dir: str
    model_dir: str
    iterations: int
    point_cloud_path: str
    point_cloud_size_bytes: int
    render_root: str
    render_pairs: int
    alignment: dict[str, float]
    train_stdout_tail: str
    train_stderr_tail: str
    render_stdout_tail: str
    render_stderr_tail: str
    logs_dir: str


def _require_paths(*paths: Path) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        pytest.skip(f"turntable prototype artifacts not available: {missing}")


def _collect_alpha_coverage_stats(images_dir: Path) -> dict[str, float]:
    _require_paths(images_dir)
    ratios: list[float] = []
    bbox_ws: list[float] = []
    bbox_hs: list[float] = []

    for path in sorted(images_dir.glob("*.png")):
        alpha = Image.open(path).convert("RGBA").getchannel("A")
        metrics = _mask_metrics(np.array(alpha) > ALPHA_THRESHOLD)
        ratios.append(metrics["mask_ratio"])
        bbox_ws.append(metrics["bbox_w_frac"])
        bbox_hs.append(metrics["bbox_h_frac"])

    assert ratios, f"no segmented png files found under {images_dir}"
    return {
        "count": len(ratios),
        "mask_ratio_mean": float(np.mean(ratios)),
        "mask_ratio_median": float(np.median(ratios)),
        "bbox_w_mean": float(np.mean(bbox_ws)),
        "bbox_w_median": float(np.median(bbox_ws)),
        "bbox_h_mean": float(np.mean(bbox_hs)),
        "bbox_h_median": float(np.median(bbox_hs)),
    }


def _measure_center_crop_bbox_gain(
    input_image_path: Path,
    segmented_image_path: Path,
) -> tuple[dict[str, float], dict[str, float]]:
    rgb = Image.open(input_image_path).convert("RGB")
    alpha = _load_resized_alpha(segmented_image_path, rgb.size)
    centered_image, centered_alpha = _build_center_crop_variant(rgb, alpha)

    before = _mask_metrics(np.array(alpha) > ALPHA_THRESHOLD)
    after = _mask_metrics(np.array(centered_alpha) > ALPHA_THRESHOLD)

    assert centered_image.size == rgb.size
    assert centered_alpha.size == rgb.size
    return before, after


def _load_resized_alpha(segmented_image_path: Path, target_size: tuple[int, int]) -> Image.Image:
    segmented = Image.open(segmented_image_path).convert("RGBA")
    alpha = segmented.getchannel("A")
    if alpha.size != target_size:
        alpha = alpha.resize(target_size, Image.Resampling.BILINEAR)
    return alpha


def _mask_metrics(mask: np.ndarray) -> dict[str, float]:
    height, width = mask.shape
    mask_ratio = float(mask.sum() / mask.size)

    ys, xs = np.where(mask)
    if len(xs) == 0:
        return {
            "mask_ratio": mask_ratio,
            "bbox_w_frac": 0.0,
            "bbox_h_frac": 0.0,
        }

    bbox_w = int(xs.max() - xs.min() + 1)
    bbox_h = int(ys.max() - ys.min() + 1)
    return {
        "mask_ratio": mask_ratio,
        "bbox_w_frac": float(bbox_w / width),
        "bbox_h_frac": float(bbox_h / height),
    }


def _foreground_mask(image_path: Path) -> np.ndarray:
    arr = np.array(Image.open(image_path).convert("RGB"))
    return np.any(arr > 16, axis=2)


def _compute_alignment_stats(render_root: Path) -> RenderAlignmentStats:
    gt_dir = render_root / "gt"
    renders_dir = render_root / "renders"
    _require_paths(gt_dir, renders_dir)

    ious: list[float] = []
    area_ratios: list[float] = []

    for gt_path in sorted(gt_dir.glob("*.png")):
        render_path = renders_dir / gt_path.name
        if not render_path.exists():
            continue

        gt_mask = _foreground_mask(gt_path)
        render_mask = _foreground_mask(render_path)

        inter = np.logical_and(gt_mask, render_mask).sum()
        union = np.logical_or(gt_mask, render_mask).sum()
        iou = inter / union if union else 1.0

        gt_area = gt_mask.sum()
        render_area = render_mask.sum()
        if max(gt_area, render_area):
            area_ratio = min(gt_area, render_area) / max(gt_area, render_area)
        else:
            area_ratio = 1.0

        ious.append(float(iou))
        area_ratios.append(float(area_ratio))

    assert ious, f"no gt/render pairs found under {render_root}"
    return RenderAlignmentStats(
        count=len(ious),
        iou_mean=float(np.mean(ious)),
        iou_median=float(np.median(ious)),
        area_ratio_mean=float(np.mean(area_ratios)),
        area_ratio_median=float(np.median(area_ratios)),
    )


def _build_fullframe_masked_variant(
    rgb: Image.Image,
    alpha: Image.Image,
    background_color: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    alpha_arr = np.array(alpha, dtype=np.float32) / 255.0
    rgb_arr = np.array(rgb, dtype=np.float32)
    bg_arr = np.full_like(rgb_arr, background_color, dtype=np.float32)
    blended = rgb_arr * alpha_arr[..., None] + bg_arr * (1.0 - alpha_arr[..., None])
    return Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8), mode="RGB")


def _build_center_crop_variant(
    rgb: Image.Image,
    alpha: Image.Image,
    padding_ratio: float = 0.2,
    min_padding_px: int = 30,
) -> tuple[Image.Image, Image.Image]:
    alpha_arr = np.array(alpha)
    ys, xs = np.where(alpha_arr > ALPHA_THRESHOLD)
    if len(xs) == 0:
        return rgb.copy(), alpha.copy()

    x0 = int(xs.min())
    x1 = int(xs.max())
    y0 = int(ys.min())
    y1 = int(ys.max())

    pad_x = max(min_padding_px, int((x1 - x0 + 1) * padding_ratio))
    pad_y = max(min_padding_px, int((y1 - y0 + 1) * padding_ratio))
    x0 = max(0, x0 - pad_x)
    x1 = min(rgb.size[0] - 1, x1 + pad_x)
    y0 = max(0, y0 - pad_y)
    y1 = min(rgb.size[1] - 1, y1 + pad_y)

    crop_rgb = rgb.crop((x0, y0, x1 + 1, y1 + 1))
    crop_alpha = alpha.crop((x0, y0, x1 + 1, y1 + 1))

    scale = min(rgb.size[0] / crop_rgb.size[0], rgb.size[1] / crop_rgb.size[1])
    new_size = (
        max(1, int(round(crop_rgb.size[0] * scale))),
        max(1, int(round(crop_rgb.size[1] * scale))),
    )
    resized_rgb = crop_rgb.resize(new_size, Image.Resampling.LANCZOS)
    resized_alpha = crop_alpha.resize(new_size, Image.Resampling.BILINEAR)

    canvas_rgb = Image.new("RGB", rgb.size, "white")
    canvas_alpha = Image.new("L", rgb.size, 0)
    offset = (
        (rgb.size[0] - new_size[0]) // 2,
        (rgb.size[1] - new_size[1]) // 2,
    )
    canvas_rgb.paste(resized_rgb, offset)
    canvas_alpha.paste(resized_alpha, offset)
    return canvas_rgb, canvas_alpha


def _collect_common_frame_stems(data_root: Path) -> list[str]:
    input_stems = {path.stem for path in (data_root / "input").glob("*.jpg")}
    image_stems = {path.stem for path in (data_root / "images").glob("*.png")}
    stems = sorted(input_stems & image_stems)
    assert stems, f"no shared frame stems under {data_root}"
    return stems


def _select_frame_stems(data_root: Path, frame_limit: int) -> list[str]:
    stems = _collect_common_frame_stems(data_root)
    if frame_limit <= 0 or frame_limit >= len(stems):
        return stems
    indexes = np.linspace(0, len(stems) - 1, frame_limit, dtype=int)
    return [stems[index] for index in indexes]


def _prepare_variant_scene(
    output_root: Path,
    variant_name: str,
    strategy: str,
    frame_stems: list[str],
) -> Path:
    _require_paths(TURNTABLE_DATA_ROOT / "input", TURNTABLE_DATA_ROOT / "images")
    scene_dir = output_root / variant_name
    input_dir = scene_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    for stem in frame_stems:
        input_path = TURNTABLE_DATA_ROOT / "input" / f"{stem}.jpg"
        segmented_path = TURNTABLE_DATA_ROOT / "images" / f"{stem}.png"
        rgb = Image.open(input_path).convert("RGB")
        alpha = _load_resized_alpha(segmented_path, rgb.size)

        if strategy == "original_fullframe":
            variant = rgb
        elif strategy == "masked_fullframe":
            variant = _build_fullframe_masked_variant(rgb, alpha)
        elif strategy == "crop_centered":
            variant, _ = _build_center_crop_variant(rgb, alpha)
        else:
            raise AssertionError(f"unknown strategy: {strategy}")

        variant.save(input_dir / f"{stem}.jpg", quality=95)

    return scene_dir


def _parse_model_analyzer_output(output: str) -> dict[str, float | int | None]:
    def _extract_int(pattern: str) -> int:
        match = re.search(pattern, output)
        assert match is not None, f"pattern not found: {pattern}"
        return int(match.group(1))

    def _extract_float(pattern: str) -> float | None:
        match = re.search(pattern, output)
        return float(match.group(1)) if match is not None else None

    return {
        "registered_images": _extract_int(r"Registered images:\s+(\d+)"),
        "points": _extract_int(r"Points:\s+(\d+)"),
        "mean_observations_per_image": _extract_float(r"Mean observations per image:\s+([0-9.]+)"),
        "mean_reprojection_error": _extract_float(r"Mean reprojection error:\s+([0-9.]+)px"),
    }


def _parse_mapper_progress(output: str) -> tuple[bool, int]:
    found_initial_pair = (
        "Initializing with image pair" in output
        or "Registering image #" in output
    )
    registration_matches = [int(value) for value in re.findall(r"Registering image #(\d+)", output)]
    max_registration_image = max(registration_matches, default=0)
    return found_initial_pair, max_registration_image


def _run_logged_command(cmd: list[str], log_path: Path) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    log_path.write_text(
        "\n".join(
            [
                "$ " + " ".join(cmd),
                "",
                "=== STDOUT ===",
                proc.stdout,
                "",
                "=== STDERR ===",
                proc.stderr,
            ]
        ),
        encoding="utf-8",
    )
    return proc


def _count_image_files(images_dir: Path) -> int:
    return len(
        list(images_dir.glob("*.png"))
        + list(images_dir.glob("*.jpg"))
        + list(images_dir.glob("*.jpeg"))
    )


def _finalize_colmap_scene_for_training(scene_dir: Path, commands_dir: Path) -> tuple[bool, int]:
    sparse_input = scene_dir / "distorted" / "sparse" / "0"
    if not sparse_input.exists():
        return False, 0

    undistort_cmd = [
        COLMAP_BIN,
        "image_undistorter",
        "--image_path",
        str(scene_dir / "input"),
        "--input_path",
        str(sparse_input),
        "--output_path",
        str(scene_dir),
        "--output_type",
        "COLMAP",
    ]
    undistort_proc = _run_logged_command(
        undistort_cmd,
        commands_dir / "04_image_undistorter.log",
    )
    assert undistort_proc.returncode == 0, undistort_proc.stderr

    sparse_root = scene_dir / "sparse"
    sparse_zero = sparse_root / "0"
    sparse_zero.mkdir(parents=True, exist_ok=True)
    for path in list(sparse_root.iterdir()):
        if path.name == "0":
            continue
        shutil.move(str(path), str(sparse_zero / path.name))

    images_dir = scene_dir / "images"
    training_scene_ready = images_dir.exists() and (scene_dir / "sparse" / "0").exists()
    return training_scene_ready, _count_image_files(images_dir)


def _run_colmap_variant(
    scene_dir: Path,
    variant_name: str,
    strategy: str,
    matcher: str,
    frame_count: int,
    finalize_for_training: bool = False,
) -> ColmapPrototypeResult:
    distorted_dir = scene_dir / "distorted" / "sparse"
    distorted_dir.mkdir(parents=True, exist_ok=True)
    database_path = scene_dir / "distorted" / "database.db"
    commands_dir = scene_dir / "logs"
    commands_dir.mkdir(parents=True, exist_ok=True)

    feature_cmd = [
        COLMAP_BIN,
        "feature_extractor",
        "--database_path",
        str(database_path),
        "--image_path",
        str(scene_dir / "input"),
        "--ImageReader.single_camera",
        "1",
        "--ImageReader.camera_model",
        "OPENCV",
        "--SiftExtraction.use_gpu",
        "0",
    ]
    if matcher == "exhaustive":
        matcher_cmd = [
            COLMAP_BIN,
            "exhaustive_matcher",
            "--database_path",
            str(database_path),
            "--SiftMatching.use_gpu",
            "0",
        ]
    elif matcher == "sequential":
        matcher_cmd = [
            COLMAP_BIN,
            "sequential_matcher",
            "--database_path",
            str(database_path),
            "--SiftMatching.use_gpu",
            "0",
        ]
    else:
        raise AssertionError(f"unknown matcher: {matcher}")

    mapper_cmd = [
        COLMAP_BIN,
        "mapper",
        "--database_path",
        str(database_path),
        "--image_path",
        str(scene_dir / "input"),
        "--output_path",
        str(distorted_dir),
        "--Mapper.ba_global_function_tolerance=0.000001",
    ]

    feature_proc = _run_logged_command(feature_cmd, commands_dir / "01_feature_extractor.log")
    assert feature_proc.returncode == 0, feature_proc.stderr

    matcher_proc = _run_logged_command(matcher_cmd, commands_dir / "02_matcher.log")
    assert matcher_proc.returncode == 0, matcher_proc.stderr

    mapper_proc = _run_logged_command(mapper_cmd, commands_dir / "03_mapper.log")
    found_initial_pair, max_registration_image = _parse_mapper_progress(mapper_proc.stdout)

    registered_images = 0
    points = 0
    mean_observations_per_image = None
    mean_reprojection_error = None
    training_scene_ready = False
    undistorted_images = 0
    succeeded = mapper_proc.returncode == 0 and (distorted_dir / "0").exists()

    if succeeded:
        analyzer_cmd = [COLMAP_BIN, "model_analyzer", "--path", str(distorted_dir / "0")]
        analyzer_proc = _run_logged_command(analyzer_cmd, commands_dir / "05_model_analyzer.log")
        assert analyzer_proc.returncode == 0, analyzer_proc.stderr
        parsed = _parse_model_analyzer_output(analyzer_proc.stdout)
        registered_images = int(parsed["registered_images"])
        points = int(parsed["points"])
        mean_observations_per_image = parsed["mean_observations_per_image"]
        mean_reprojection_error = parsed["mean_reprojection_error"]
        if finalize_for_training:
            training_scene_ready, undistorted_images = _finalize_colmap_scene_for_training(
                scene_dir=scene_dir,
                commands_dir=commands_dir,
            )

    progress_rank = 2 if succeeded else 1 if found_initial_pair else 0
    return ColmapPrototypeResult(
        variant_name=variant_name,
        strategy=strategy,
        matcher=matcher,
        scene_dir=str(scene_dir),
        frame_count=frame_count,
        returncode=mapper_proc.returncode,
        succeeded=succeeded,
        progress_rank=progress_rank,
        found_initial_pair=found_initial_pair,
        max_registration_image=max_registration_image,
        registered_images=registered_images,
        points=points,
        mean_observations_per_image=mean_observations_per_image,
        mean_reprojection_error=mean_reprojection_error,
        training_scene_ready=training_scene_ready,
        undistorted_images=undistorted_images,
        mapper_stdout_tail="\n".join(mapper_proc.stdout.splitlines()[-20:]),
        mapper_stderr_tail="\n".join(mapper_proc.stderr.splitlines()[-20:]),
        commands_log=str(commands_dir),
    )


def _run_turntable_foreground_prototype(
    output_root: Path,
    frame_limit: int,
    finalize_for_training: bool = False,
) -> dict[str, object]:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    experiment_root = output_root / f"{timestamp}_limit{frame_limit}"
    experiment_root.mkdir(parents=True, exist_ok=True)

    frame_stems = _select_frame_stems(TURNTABLE_DATA_ROOT, frame_limit)
    (experiment_root / "selected_frames.json").write_text(
        json.dumps(frame_stems, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    variants = [
        ("original_fullframe_exhaustive", "original_fullframe", "exhaustive"),
        ("masked_fullframe_exhaustive", "masked_fullframe", "exhaustive"),
        ("crop_centered_sequential", "crop_centered", "sequential"),
    ]

    results: list[dict[str, object]] = []
    for variant_name, strategy, matcher in variants:
        scene_dir = _prepare_variant_scene(
            output_root=experiment_root,
            variant_name=variant_name,
            strategy=strategy,
            frame_stems=frame_stems,
        )
        result = _run_colmap_variant(
            scene_dir=scene_dir,
            variant_name=variant_name,
            strategy=strategy,
            matcher=matcher,
            frame_count=len(frame_stems),
            finalize_for_training=finalize_for_training,
        )
        results.append(asdict(result))

    summary = {
        "timestamp": timestamp,
        "frame_limit": frame_limit,
        "frame_count": len(frame_stems),
        "experiment_root": str(experiment_root),
        "results": results,
        "conclusion": (
            "当前原型表明：单纯全帧抑背景不足以让 turntable 视频稳定通过 COLMAP；"
            "居中裁剪 + sequential matcher 可以作为下一步实验方向，但尚不能等价视为‘最终模型不会崩塌’。"
        ),
    }
    (experiment_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _tail_text(text: str, lines: int = 20) -> str:
    return "\n".join(text.splitlines()[-lines:])


def _run_3dgs_training_preview(
    scene_dir: Path,
    variant_name: str,
    model_root: Path,
    iterations: int,
) -> TrainingPreviewResult:
    model_dir = model_root / variant_name
    logs_dir = model_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    train_cmd = [
        GS3D_PYTHON,
        str(GS3D_DIR / "train.py"),
        "-s",
        str(scene_dir),
        "-m",
        str(model_dir),
        "--iterations",
        str(iterations),
        "--test_iterations",
        str(iterations),
        "--save_iterations",
        str(iterations),
        "--disable_viewer",
    ]
    train_proc = _run_logged_command(train_cmd, logs_dir / "01_train.log")
    assert train_proc.returncode == 0, train_proc.stderr

    render_cmd = [
        GS3D_PYTHON,
        str(GS3D_DIR / "render.py"),
        "-s",
        str(scene_dir),
        "-m",
        str(model_dir),
        "--iteration",
        str(iterations),
        "--skip_test",
    ]
    render_proc = _run_logged_command(render_cmd, logs_dir / "02_render.log")
    assert render_proc.returncode == 0, render_proc.stderr

    point_cloud_path = model_dir / "point_cloud" / f"iteration_{iterations}" / "point_cloud.ply"
    render_root = model_dir / "train" / f"ours_{iterations}"
    _require_paths(point_cloud_path, render_root / "gt", render_root / "renders")

    alignment = _compute_alignment_stats(render_root)
    return TrainingPreviewResult(
        variant_name=variant_name,
        scene_dir=str(scene_dir),
        model_dir=str(model_dir),
        iterations=iterations,
        point_cloud_path=str(point_cloud_path),
        point_cloud_size_bytes=point_cloud_path.stat().st_size,
        render_root=str(render_root),
        render_pairs=alignment.count,
        alignment=asdict(alignment),
        train_stdout_tail=_tail_text(train_proc.stdout),
        train_stderr_tail=_tail_text(train_proc.stderr),
        render_stdout_tail=_tail_text(render_proc.stdout),
        render_stderr_tail=_tail_text(render_proc.stderr),
        logs_dir=str(logs_dir),
    )


def _run_turntable_foreground_training_preview(
    output_root: Path,
    frame_limit: int,
    iterations: int,
) -> dict[str, object]:
    prototype_summary = _run_turntable_foreground_prototype(
        output_root=output_root,
        frame_limit=frame_limit,
        finalize_for_training=True,
    )
    experiment_root = Path(str(prototype_summary["experiment_root"]))
    model_root = experiment_root / "training_preview"
    requested_variants = [
        item.strip()
        for item in os.getenv(
            "TURNTABLE_FOREGROUND_TRAIN_VARIANTS",
            "original_fullframe_exhaustive,crop_centered_sequential",
        ).split(",")
        if item.strip()
    ]

    colmap_results = {item["variant_name"]: item for item in prototype_summary["results"]}
    runs: list[dict[str, object]] = []
    for variant_name in requested_variants:
        colmap_result = colmap_results.get(variant_name)
        if not colmap_result:
            continue
        if not colmap_result["succeeded"] or not colmap_result["training_scene_ready"]:
            continue
        run = _run_3dgs_training_preview(
            scene_dir=Path(str(colmap_result["scene_dir"])),
            variant_name=variant_name,
            model_root=model_root,
            iterations=iterations,
        )
        runs.append(asdict(run))

    summary = {
        "timestamp": prototype_summary["timestamp"],
        "frame_limit": frame_limit,
        "iterations": iterations,
        "experiment_root": str(experiment_root),
        "prototype_summary": prototype_summary,
        "runs": runs,
        "conclusion": (
            "该预览仅用于观察 tests-only 前景优先原型是否能产出可渲染模型；"
            "是否真正解决 turntable 崩塌，需要以 render/gt 对齐和点云质量继续判断。"
        ),
    }
    (experiment_root / "training_preview_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary
