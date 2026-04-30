from __future__ import annotations

import json
import os
import numpy as np
from pathlib import Path

import pytest
from PIL import Image

from test_support.reconstruction_turntable_holdout_support import (
    DEFAULT_HOLDOUT_OUTPUT_ROOT,
    HoldoutVariantScene,
    build_holdout_commands,
    collect_holdout_variant_summary,
    compute_foreground_metrics_from_arrays,
    prepare_holdout_variant_scene,
    run_turntable_holdout_eval,
    split_holdout_stems,
)


def test_split_holdout_stems_respects_llffhold_stride() -> None:
    stems = [f"frame_{idx:04d}" for idx in range(8)]

    train_stems, test_stems = split_holdout_stems(stems, llffhold=4)

    assert test_stems == ["frame_0000", "frame_0004"]
    assert train_stems == [
        "frame_0001",
        "frame_0002",
        "frame_0003",
        "frame_0005",
        "frame_0006",
        "frame_0007",
    ]


def test_compute_foreground_metrics_uses_supplied_mask_instead_of_full_frame() -> None:
    gt = np.zeros((4, 4, 3), dtype=np.uint8)
    render = np.zeros((4, 4, 3), dtype=np.uint8)
    mask = np.zeros((4, 4), dtype=bool)

    gt[:2, :2] = 255
    render[1:3, 1:3] = 255
    mask[:2, :2] = True

    metrics = compute_foreground_metrics_from_arrays(render, gt, mask)

    assert round(metrics["foreground_mask_iou"], 4) == 0.25
    assert round(metrics["foreground_area_ratio"], 4) == 0.25
    assert metrics["foreground_l1"] > 0
    assert metrics["foreground_psnr"] < 20


def _write_sample_turntable_source(root: Path) -> None:
    (root / "input").mkdir(parents=True, exist_ok=True)
    (root / "images").mkdir(parents=True, exist_ok=True)

    rgb = Image.new("RGB", (12, 8), "black")
    for x in range(3, 7):
        for y in range(2, 6):
            rgb.putpixel((x, y), (255, 255, 255))
    rgb.save(root / "input" / "frame_0001.jpg", quality=95)

    rgba = Image.new("RGBA", (12, 8), (0, 0, 0, 0))
    for x in range(3, 7):
        for y in range(2, 6):
            rgba.putpixel((x, y), (255, 255, 255, 255))
    rgba.save(root / "images" / "frame_0001.png")


def test_prepare_holdout_variant_scene_writes_input_mask_and_manifest(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    experiment_root = tmp_path / "experiment"
    _write_sample_turntable_source(source_root)

    scene = prepare_holdout_variant_scene(
        source_root=source_root,
        experiment_root=experiment_root,
        variant_name="segmented_fullframe_exhaustive",
        variant_kind="segmented_fullframe",
        frame_stems=["frame_0001"],
        llffhold=8,
    )

    assert (scene.scene_dir / "input" / "frame_0001.jpg").exists()
    assert (scene.scene_dir / "masks" / "frame_0001.png").exists()
    assert (scene.scene_dir / "holdout_manifest.json").exists()
    assert scene.test_stems == ["frame_0001"]


def test_prepare_holdout_variant_scene_centers_crop_mask_for_crop_variant(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    experiment_root = tmp_path / "experiment"
    _write_sample_turntable_source(source_root)

    scene = prepare_holdout_variant_scene(
        source_root=source_root,
        experiment_root=experiment_root,
        variant_name="crop_centered_sequential",
        variant_kind="crop_centered",
        frame_stems=["frame_0001"],
        llffhold=8,
    )

    mask = Image.open(scene.scene_dir / "masks" / "frame_0001.png").convert("L")
    xs, ys = [], []
    for y in range(mask.height):
        for x in range(mask.width):
            if mask.getpixel((x, y)) > 0:
                xs.append(x)
                ys.append(y)

    assert xs and ys
    center_x = (min(xs) + max(xs)) / 2
    center_y = (min(ys) + max(ys)) / 2
    assert abs(center_x - ((mask.width - 1) / 2)) <= 1.0
    assert abs(center_y - ((mask.height - 1) / 2)) <= 1.0


def test_build_holdout_commands_use_eval_training_and_test_only_render(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "scene"
    model_dir = tmp_path / "model"

    train_cmd, render_cmd, metrics_cmd = build_holdout_commands(
        scene_dir=scene_dir,
        model_dir=model_dir,
        iterations=1000,
        gs_python="/tmp/python",
        gs_root=Path("/tmp/gaussian-splatting"),
    )

    assert "--eval" in train_cmd
    assert "--skip_train" in render_cmd
    assert metrics_cmd[-2:] == ["-m", str(model_dir)]


def test_collect_holdout_variant_summary_reads_results_and_ranks_worst_frames(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "scene"
    model_dir = tmp_path / "model"
    render_root = model_dir / "test" / "ours_1000"
    gt_dir = render_root / "gt"
    renders_dir = render_root / "renders"
    masks_dir = scene_dir / "masks"
    gt_dir.mkdir(parents=True, exist_ok=True)
    renders_dir.mkdir(parents=True, exist_ok=True)
    masks_dir.mkdir(parents=True, exist_ok=True)

    gt = np.zeros((4, 4, 3), dtype=np.uint8)
    render = np.zeros((4, 4, 3), dtype=np.uint8)
    gt[:2, :2] = 255
    render[1:3, 1:3] = 255
    Image.fromarray(gt).save(gt_dir / "00000.png")
    Image.fromarray(render).save(renders_dir / "00000.png")

    mask = np.zeros((4, 4), dtype=np.uint8)
    mask[:2, :2] = 255
    Image.fromarray(mask).save(masks_dir / "frame_0001.png")

    (model_dir / "results.json").write_text(
        json.dumps({"ours_1000": {"PSNR": 11.5, "SSIM": 0.61, "LPIPS": 0.42}}),
        encoding="utf-8",
    )
    (model_dir / "per_view.json").write_text(
        json.dumps(
            {
                "ours_1000": {
                    "PSNR": {"00000.png": 11.5},
                    "SSIM": {"00000.png": 0.61},
                    "LPIPS": {"00000.png": 0.42},
                }
            }
        ),
        encoding="utf-8",
    )

    scene = HoldoutVariantScene(
        variant_name="segmented_fullframe_exhaustive",
        variant_kind="segmented_fullframe",
        scene_dir=scene_dir,
        frame_stems=["frame_0001"],
        train_stems=[],
        test_stems=["frame_0001"],
    )

    summary = collect_holdout_variant_summary(
        scene=scene,
        model_dir=model_dir,
        iteration=1000,
    )

    assert summary["variant_name"] == "segmented_fullframe_exhaustive"
    assert summary["test_psnr_mean"] == 11.5
    assert summary["test_ssim_mean"] == 0.61
    assert summary["test_l1_mean"] > 0
    assert len(summary["worst_test_frames"]) == 1
    assert summary["worst_test_frames"][0]["frame_stem"] == "frame_0001"


def test_collect_holdout_variant_summary_falls_back_to_image_metrics(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "scene"
    model_dir = tmp_path / "model"
    render_root = model_dir / "test" / "ours_1000"
    gt_dir = render_root / "gt"
    renders_dir = render_root / "renders"
    masks_dir = scene_dir / "masks"
    gt_dir.mkdir(parents=True, exist_ok=True)
    renders_dir.mkdir(parents=True, exist_ok=True)
    masks_dir.mkdir(parents=True, exist_ok=True)

    gt = np.zeros((4, 4, 3), dtype=np.uint8)
    render = np.zeros((4, 4, 3), dtype=np.uint8)
    gt[:2, :2] = 255
    render[:2, :2] = 255
    Image.fromarray(gt).save(gt_dir / "00000.png")
    Image.fromarray(render).save(renders_dir / "00000.png")

    mask = np.zeros((4, 4), dtype=np.uint8)
    mask[:2, :2] = 255
    Image.fromarray(mask).save(masks_dir / "frame_0001.png")

    scene = HoldoutVariantScene(
        variant_name="segmented_fullframe_exhaustive",
        variant_kind="segmented_fullframe",
        scene_dir=scene_dir,
        frame_stems=["frame_0001"],
        train_stems=[],
        test_stems=["frame_0001"],
    )

    summary = collect_holdout_variant_summary(
        scene=scene,
        model_dir=model_dir,
        iteration=1000,
    )

    assert summary["test_psnr_mean"] >= 99.0
    assert summary["test_ssim_mean"] == 1.0
    assert summary["test_l1_mean"] == 0.0


@pytest.mark.skipif(
    os.getenv("RUN_TURNTABLE_HOLDOUT_EVAL") != "1",
    reason="手动 holdout 评估；运行前请设置 RUN_TURNTABLE_HOLDOUT_EVAL=1",
)
def test_turntable_holdout_eval() -> None:
    frame_limit = int(os.getenv("TURNTABLE_HOLDOUT_FRAME_LIMIT", "48"))
    iterations = int(os.getenv("TURNTABLE_HOLDOUT_ITERATIONS", "1000"))
    output_root = Path(
        os.getenv("TURNTABLE_HOLDOUT_OUTPUT_DIR", str(DEFAULT_HOLDOUT_OUTPUT_ROOT))
    )

    summary = run_turntable_holdout_eval(
        output_root=output_root,
        frame_limit=frame_limit,
        iterations=iterations,
    )

    assert summary["results"], "expected at least one variant result"
    success_results = [item for item in summary["results"] if item["status"] == "success"]
    if success_results:
        for item in success_results:
            assert "test_psnr_mean" in item
            assert "foreground_mask_iou_mean" in item
            assert "worst_test_frames" in item
    else:
        for item in summary["results"]:
            assert item["status"] == "failed"
            assert item["failed_stage"] in {"colmap", "train", "render"}
            assert "returncode" in item
    print(json.dumps(summary, ensure_ascii=False, indent=2))
