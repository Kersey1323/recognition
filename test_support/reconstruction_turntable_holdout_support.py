from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity


ALPHA_THRESHOLD = 8
COLMAP_BIN = shutil.which("colmap") or "colmap"
GS3D_PYTHON = "/home/ubuntu/miniconda3/envs/gs3d/bin/python"
RECO_ROOT = Path("csrcqsf/biz/railwayparts/reconstruction_server")
GS_ROOT = Path("/home/ubuntu/project-train/gaussian-splatting")
TURNTABLE_DATA_ROOT = RECO_ROOT / "data" / "20260430091139_支撑架"
DEFAULT_HOLDOUT_OUTPUT_ROOT = Path("logs/reconstruction/turntable_holdout_eval")


@dataclass
class HoldoutVariantScene:
    variant_name: str
    variant_kind: str
    scene_dir: Path
    frame_stems: list[str]
    train_stems: list[str]
    test_stems: list[str]


@dataclass
class HoldoutColmapResult:
    variant_name: str
    variant_kind: str
    matcher: str
    scene_dir: Path
    returncode: int
    succeeded: bool
    registered_images: int
    points: int
    training_scene_ready: bool
    undistorted_images: int
    commands_log: Path


def split_holdout_stems(
    stems: Sequence[str],
    llffhold: int = 8,
) -> tuple[list[str], list[str]]:
    ordered = sorted(stems)
    if llffhold <= 0:
        return ordered, []

    test_stems = [stem for idx, stem in enumerate(ordered) if idx % llffhold == 0]
    train_stems = [stem for idx, stem in enumerate(ordered) if idx % llffhold != 0]
    return train_stems, test_stems


def _psnr_from_uint8(render: np.ndarray, gt: np.ndarray) -> float:
    render_f = render.astype(np.float32) / 255.0
    gt_f = gt.astype(np.float32) / 255.0
    mse = float(np.mean((render_f - gt_f) ** 2))
    if mse <= 1e-12:
        return 99.0
    return float(-10.0 * math.log10(mse))


def compute_foreground_metrics_from_arrays(
    render: np.ndarray,
    gt: np.ndarray,
    mask: np.ndarray,
) -> dict[str, float]:
    assert render.shape == gt.shape
    if render.shape[:2] != mask.shape:
        mask = np.array(
            Image.fromarray(mask.astype(np.uint8) * 255, mode="L").resize(
                (render.shape[1], render.shape[0]),
                Image.Resampling.BILINEAR,
            )
        ) > 127

    roi = mask.astype(bool)
    render_roi = render.copy()
    gt_roi = gt.copy()
    render_roi[~roi] = 0
    gt_roi[~roi] = 0

    render_fg = np.any(render_roi > 16, axis=2)
    gt_fg = np.any(gt_roi > 16, axis=2)

    inter = float(np.logical_and(render_fg, gt_fg).sum())
    union = float(np.logical_or(render_fg, gt_fg).sum())
    render_area = float(render_fg.sum())
    gt_area = float(gt_fg.sum())

    l1 = float(
        np.mean(np.abs(render_roi.astype(np.float32) - gt_roi.astype(np.float32))) / 255.0
    )
    psnr = _psnr_from_uint8(render_roi, gt_roi)

    return {
        "foreground_psnr": psnr,
        "foreground_l1": l1,
        "foreground_mask_iou": inter / union if union else 1.0,
        "foreground_area_ratio": (
            min(render_area, gt_area) / max(render_area, gt_area)
            if max(render_area, gt_area)
            else 1.0
        ),
    }


def _load_resized_alpha(segmented_image_path: Path, target_size: tuple[int, int]) -> Image.Image:
    alpha = Image.open(segmented_image_path).convert("RGBA").getchannel("A")
    if alpha.size != target_size:
        alpha = alpha.resize(target_size, Image.Resampling.BILINEAR)
    return alpha


def _build_segmented_fullframe_variant(
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

    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
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
    offset = ((rgb.size[0] - new_size[0]) // 2, (rgb.size[1] - new_size[1]) // 2)
    canvas_rgb.paste(resized_rgb, offset)
    canvas_alpha.paste(resized_alpha, offset)
    return canvas_rgb, canvas_alpha


def prepare_holdout_variant_scene(
    source_root: Path,
    experiment_root: Path,
    variant_name: str,
    variant_kind: str,
    frame_stems: list[str],
    llffhold: int = 8,
) -> HoldoutVariantScene:
    scene_dir = experiment_root / variant_name
    input_dir = scene_dir / "input"
    masks_dir = scene_dir / "masks"
    input_dir.mkdir(parents=True, exist_ok=True)
    masks_dir.mkdir(parents=True, exist_ok=True)

    train_stems, test_stems = split_holdout_stems(frame_stems, llffhold=llffhold)

    for stem in frame_stems:
        rgb = Image.open(source_root / "input" / f"{stem}.jpg").convert("RGB")
        alpha = _load_resized_alpha(source_root / "images" / f"{stem}.png", rgb.size)

        if variant_kind == "original_fullframe":
            variant_rgb = rgb
            variant_alpha = alpha
        elif variant_kind == "segmented_fullframe":
            variant_rgb = _build_segmented_fullframe_variant(rgb, alpha)
            variant_alpha = alpha
        elif variant_kind == "crop_centered":
            variant_rgb, variant_alpha = _build_center_crop_variant(rgb, alpha)
        else:
            raise AssertionError(f"unknown variant_kind: {variant_kind}")

        variant_rgb.save(input_dir / f"{stem}.jpg", quality=95)
        variant_alpha.save(masks_dir / f"{stem}.png")

    (scene_dir / "holdout_manifest.json").write_text(
        json.dumps(
            {
                "variant_name": variant_name,
                "variant_kind": variant_kind,
                "frame_stems": frame_stems,
                "train_stems": train_stems,
                "test_stems": test_stems,
                "llffhold": llffhold,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return HoldoutVariantScene(
        variant_name=variant_name,
        variant_kind=variant_kind,
        scene_dir=scene_dir,
        frame_stems=frame_stems,
        train_stems=train_stems,
        test_stems=test_stems,
    )


def build_holdout_commands(
    scene_dir: Path,
    model_dir: Path,
    iterations: int,
    gs_python: str = GS3D_PYTHON,
    gs_root: Path = GS_ROOT,
) -> tuple[list[str], list[str], list[str]]:
    train_cmd = [
        gs_python,
        str(gs_root / "train.py"),
        "-s",
        str(scene_dir),
        "-m",
        str(model_dir),
        "--eval",
        "--iterations",
        str(iterations),
        "--test_iterations",
        str(iterations),
        "--save_iterations",
        str(iterations),
        "--disable_viewer",
        "--quiet",
    ]
    render_cmd = [
        gs_python,
        str(gs_root / "render.py"),
        "-s",
        str(scene_dir),
        "-m",
        str(model_dir),
        "--iteration",
        str(iterations),
        "--skip_train",
        "--quiet",
    ]
    metrics_cmd = [
        gs_python,
        str(gs_root / "metrics.py"),
        "-m",
        str(model_dir),
    ]
    return train_cmd, render_cmd, metrics_cmd


def build_holdout_colmap_commands(
    scene_dir: Path,
    matcher: str,
) -> tuple[list[str], list[str], list[str], list[str]]:
    distorted_dir = scene_dir / "distorted" / "sparse"
    database_path = scene_dir / "distorted" / "database.db"
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
    undistort_cmd = [
        COLMAP_BIN,
        "image_undistorter",
        "--image_path",
        str(scene_dir / "input"),
        "--input_path",
        str(distorted_dir / "0"),
        "--output_path",
        str(scene_dir),
        "--output_type",
        "COLMAP",
    ]
    return feature_cmd, matcher_cmd, mapper_cmd, undistort_cmd


def _run_logged_command(cmd: list[str], log_path: Path) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    log_path.parent.mkdir(parents=True, exist_ok=True)
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


def _parse_model_analyzer_output(output: str) -> dict[str, int]:
    def _extract_int(pattern: str) -> int:
        match = re.search(pattern, output)
        assert match is not None, f"pattern not found: {pattern}"
        return int(match.group(1))

    return {
        "registered_images": _extract_int(r"Registered images:\s+(\d+)"),
        "points": _extract_int(r"Points:\s+(\d+)"),
    }


def _count_image_files(images_dir: Path) -> int:
    return len(
        list(images_dir.glob("*.png"))
        + list(images_dir.glob("*.jpg"))
        + list(images_dir.glob("*.jpeg"))
    )


def _finalize_holdout_scene_for_training(scene_dir: Path, commands_dir: Path) -> tuple[bool, int]:
    sparse_input = scene_dir / "distorted" / "sparse" / "0"
    if not sparse_input.exists():
        return False, 0

    _, _, _, undistort_cmd = build_holdout_colmap_commands(scene_dir=scene_dir, matcher="exhaustive")
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


def _run_holdout_colmap_variant(
    scene: HoldoutVariantScene,
    matcher: str,
) -> HoldoutColmapResult:
    for cleanup_path in [
        scene.scene_dir / "distorted",
        scene.scene_dir / "images",
        scene.scene_dir / "sparse",
        scene.scene_dir / "logs",
    ]:
        if cleanup_path.exists():
            shutil.rmtree(cleanup_path)

    distorted_dir = scene.scene_dir / "distorted" / "sparse"
    distorted_dir.mkdir(parents=True, exist_ok=True)
    commands_dir = scene.scene_dir / "logs"
    commands_dir.mkdir(parents=True, exist_ok=True)

    feature_cmd, matcher_cmd, mapper_cmd, _ = build_holdout_colmap_commands(
        scene_dir=scene.scene_dir,
        matcher=matcher,
    )
    feature_proc = _run_logged_command(feature_cmd, commands_dir / "01_feature_extractor.log")
    assert feature_proc.returncode == 0, feature_proc.stderr

    matcher_proc = _run_logged_command(matcher_cmd, commands_dir / "02_matcher.log")
    assert matcher_proc.returncode == 0, matcher_proc.stderr

    mapper_proc = _run_logged_command(mapper_cmd, commands_dir / "03_mapper.log")
    succeeded = mapper_proc.returncode == 0 and (distorted_dir / "0").exists()
    registered_images = 0
    points = 0
    training_scene_ready = False
    undistorted_images = 0

    if succeeded:
        analyzer_cmd = [COLMAP_BIN, "model_analyzer", "--path", str(distorted_dir / "0")]
        analyzer_proc = _run_logged_command(analyzer_cmd, commands_dir / "05_model_analyzer.log")
        assert analyzer_proc.returncode == 0, analyzer_proc.stderr
        parsed = _parse_model_analyzer_output(analyzer_proc.stdout)
        registered_images = parsed["registered_images"]
        points = parsed["points"]
        if points > 0:
            training_scene_ready, undistorted_images = _finalize_holdout_scene_for_training(
                scene_dir=scene.scene_dir,
                commands_dir=commands_dir,
            )

    return HoldoutColmapResult(
        variant_name=scene.variant_name,
        variant_kind=scene.variant_kind,
        matcher=matcher,
        scene_dir=scene.scene_dir,
        returncode=mapper_proc.returncode,
        succeeded=succeeded,
        registered_images=registered_images,
        points=points,
        training_scene_ready=training_scene_ready,
        undistorted_images=undistorted_images,
        commands_log=commands_dir,
    )


def _mean_l1_from_render_pairs(render_root: Path) -> float:
    gt_dir = render_root / "gt"
    renders_dir = render_root / "renders"
    values: list[float] = []
    for gt_path in sorted(gt_dir.glob("*.png")):
        render_path = renders_dir / gt_path.name
        gt = np.array(Image.open(gt_path).convert("RGB"), dtype=np.float32)
        render = np.array(Image.open(render_path).convert("RGB"), dtype=np.float32)
        values.append(float(np.mean(np.abs(render - gt)) / 255.0))
    return float(np.mean(values)) if values else 0.0


def _compute_fullframe_metrics_from_render_pairs(
    render_root: Path,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    gt_dir = render_root / "gt"
    renders_dir = render_root / "renders"
    psnr_values: list[float] = []
    ssim_values: list[float] = []
    l1_values: list[float] = []
    per_view = {
        "PSNR": {},
        "SSIM": {},
        "L1": {},
    }

    for gt_path in sorted(gt_dir.glob("*.png")):
        render_path = renders_dir / gt_path.name
        gt = np.array(Image.open(gt_path).convert("RGB"))
        render = np.array(Image.open(render_path).convert("RGB"))
        psnr_value = _psnr_from_uint8(render, gt)
        win_size = min(7, gt.shape[0], gt.shape[1])
        if win_size % 2 == 0:
            win_size -= 1
        win_size = max(win_size, 3)
        ssim_value = float(
            structural_similarity(
                render,
                gt,
                channel_axis=2,
                data_range=255,
                win_size=win_size,
            )
        )
        l1_value = float(np.mean(np.abs(render.astype(np.float32) - gt.astype(np.float32))) / 255.0)

        psnr_values.append(psnr_value)
        ssim_values.append(ssim_value)
        l1_values.append(l1_value)
        per_view["PSNR"][gt_path.name] = psnr_value
        per_view["SSIM"][gt_path.name] = ssim_value
        per_view["L1"][gt_path.name] = l1_value

    aggregate = {
        "PSNR": float(np.mean(psnr_values)) if psnr_values else 0.0,
        "SSIM": float(np.mean(ssim_values)) if ssim_values else 0.0,
        "L1": float(np.mean(l1_values)) if l1_values else 0.0,
    }
    return aggregate, per_view


def collect_holdout_variant_summary(
    scene: HoldoutVariantScene,
    model_dir: Path,
    iteration: int,
) -> dict[str, object]:
    render_root = model_dir / "test" / f"ours_{iteration}"
    method_key = f"ours_{iteration}"
    masks_dir = scene.scene_dir / "masks"
    results_path = model_dir / "results.json"
    per_view_path = model_dir / "per_view.json"
    if results_path.exists() and per_view_path.exists():
        results = json.loads(results_path.read_text(encoding="utf-8"))
        per_view = json.loads(per_view_path.read_text(encoding="utf-8"))
        test_psnr_mean = float(results[method_key]["PSNR"])
        test_ssim_mean = float(results[method_key]["SSIM"])
        test_l1_mean = _mean_l1_from_render_pairs(render_root)
        per_view_psnr = per_view[method_key]["PSNR"]
        per_view_ssim = per_view[method_key]["SSIM"]
    else:
        aggregate, per_view_metrics = _compute_fullframe_metrics_from_render_pairs(render_root)
        test_psnr_mean = aggregate["PSNR"]
        test_ssim_mean = aggregate["SSIM"]
        test_l1_mean = aggregate["L1"]
        per_view_psnr = per_view_metrics["PSNR"]
        per_view_ssim = per_view_metrics["SSIM"]

    render_files = sorted((render_root / "gt").glob("*.png"))
    rendered_test_stems = scene.test_stems[: len(render_files)]
    cameras_path = model_dir / "cameras.json"
    if cameras_path.exists():
        cameras = json.loads(cameras_path.read_text(encoding="utf-8"))
        rendered_test_stems = [
            Path(item["img_name"]).stem for item in cameras[: len(render_files)] if "img_name" in item
        ]
        if len(rendered_test_stems) != len(render_files):
            rendered_test_stems = scene.test_stems[: len(render_files)]

    fg_metrics: list[dict[str, float]] = []
    worst_frames: list[dict[str, float | str]] = []
    for idx, stem in enumerate(rendered_test_stems):
        fname = render_files[idx].name
        gt = np.array(Image.open(render_root / "gt" / fname).convert("RGB"))
        render = np.array(Image.open(render_root / "renders" / fname).convert("RGB"))
        mask = np.array(Image.open(masks_dir / f"{stem}.png").convert("L")) > ALPHA_THRESHOLD
        fg = compute_foreground_metrics_from_arrays(render, gt, mask)
        fg_metrics.append(fg)
        worst_frames.append(
            {
                "frame_stem": stem,
                "file_name": fname,
                "test_psnr": float(per_view_psnr[fname]),
                "test_ssim": float(per_view_ssim[fname]),
                "foreground_mask_iou": fg["foreground_mask_iou"],
                "foreground_area_ratio": fg["foreground_area_ratio"],
            }
        )

    worst_frames.sort(key=lambda item: (item["foreground_mask_iou"], item["test_psnr"]))
    return {
        "variant_name": scene.variant_name,
        "variant_kind": scene.variant_kind,
        "scene_dir": str(scene.scene_dir),
        "model_dir": str(model_dir),
        "iteration": iteration,
        "train_frames": len(scene.train_stems),
        "test_frames": len(scene.test_stems),
        "test_psnr_mean": test_psnr_mean,
        "test_ssim_mean": test_ssim_mean,
        "test_l1_mean": test_l1_mean,
        "foreground_psnr_mean": float(np.mean([item["foreground_psnr"] for item in fg_metrics])),
        "foreground_l1_mean": float(np.mean([item["foreground_l1"] for item in fg_metrics])),
        "foreground_mask_iou_mean": float(
            np.mean([item["foreground_mask_iou"] for item in fg_metrics])
        ),
        "foreground_area_ratio_mean": float(
            np.mean([item["foreground_area_ratio"] for item in fg_metrics])
        ),
        "worst_test_frames": worst_frames[:5],
    }


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


def run_turntable_holdout_eval(
    output_root: Path,
    frame_limit: int,
    iterations: int,
    llffhold: int = 8,
) -> dict[str, object]:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    experiment_root = output_root / f"{timestamp}_limit{frame_limit}"
    experiment_root.mkdir(parents=True, exist_ok=True)

    frame_stems = _select_frame_stems(TURNTABLE_DATA_ROOT, frame_limit)
    variants = [
        ("original_fullframe_exhaustive", "original_fullframe", ("exhaustive",)),
        ("segmented_fullframe_exhaustive", "segmented_fullframe", ("exhaustive",)),
        ("crop_centered_sequential", "crop_centered", ("sequential", "exhaustive")),
    ]

    results: list[dict[str, object]] = []
    for variant_name, variant_kind, matcher_candidates in variants:
        scene = prepare_holdout_variant_scene(
            source_root=TURNTABLE_DATA_ROOT,
            experiment_root=experiment_root,
            variant_name=variant_name,
            variant_kind=variant_kind,
            frame_stems=frame_stems,
            llffhold=llffhold,
        )
        colmap_result = None
        for matcher in matcher_candidates:
            colmap_result = _run_holdout_colmap_variant(scene=scene, matcher=matcher)
            if colmap_result.succeeded and colmap_result.training_scene_ready:
                break
        assert colmap_result is not None
        matcher = colmap_result.matcher
        if not colmap_result.succeeded or not colmap_result.training_scene_ready:
            results.append(
                {
                    "variant_name": variant_name,
                    "variant_kind": variant_kind,
                    "matcher": matcher,
                    "scene_dir": str(scene.scene_dir),
                    "status": "failed",
                    "failed_stage": "colmap",
                    "returncode": colmap_result.returncode,
                    "registered_images": colmap_result.registered_images,
                    "points": colmap_result.points,
                    "undistorted_images": colmap_result.undistorted_images,
                }
            )
            continue

        model_dir = experiment_root / "models" / variant_name
        logs_dir = experiment_root / "logs" / variant_name
        train_cmd, render_cmd, _ = build_holdout_commands(
            scene_dir=scene.scene_dir,
            model_dir=model_dir,
            iterations=iterations,
        )

        train_proc = _run_logged_command(train_cmd, logs_dir / "01_train.log")
        if train_proc.returncode != 0:
            results.append(
                {
                    "variant_name": variant_name,
                    "variant_kind": variant_kind,
                    "matcher": matcher,
                    "scene_dir": str(scene.scene_dir),
                    "model_dir": str(model_dir),
                    "status": "failed",
                    "failed_stage": "train",
                    "returncode": train_proc.returncode,
                    "registered_images": colmap_result.registered_images,
                    "points": colmap_result.points,
                    "undistorted_images": colmap_result.undistorted_images,
                }
            )
            continue

        render_proc = _run_logged_command(render_cmd, logs_dir / "02_render.log")
        if render_proc.returncode != 0:
            results.append(
                {
                    "variant_name": variant_name,
                    "variant_kind": variant_kind,
                    "matcher": matcher,
                    "scene_dir": str(scene.scene_dir),
                    "model_dir": str(model_dir),
                    "status": "failed",
                    "failed_stage": "render",
                    "returncode": render_proc.returncode,
                    "registered_images": colmap_result.registered_images,
                    "points": colmap_result.points,
                    "undistorted_images": colmap_result.undistorted_images,
                }
            )
            continue

        result = collect_holdout_variant_summary(
            scene=scene,
            model_dir=model_dir,
            iteration=iterations,
        )
        result["matcher"] = matcher
        result["registered_images"] = colmap_result.registered_images
        result["points"] = colmap_result.points
        result["undistorted_images"] = colmap_result.undistorted_images
        result["status"] = "success"
        results.append(result)

    summary = {
        "timestamp": timestamp,
        "frame_limit": frame_limit,
        "iterations": iterations,
        "llffhold": llffhold,
        "experiment_root": str(experiment_root),
        "results": results,
    }
    (experiment_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary
