import asyncio
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageOps
from sqlalchemy import select

from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.models.item import Items
from csrcqsf.models.sgo import SgoItemImages
from csrcqsf.settings import (
    minio_access_key,
    minio_bucket,
    minio_endpoint,
    minio_secret_key,
    minio_secure,
    sam3_model_path,
)


DEFAULT_ITEM_ID = 1970402822689427456
DEFAULT_IMAGE_ID = 1982687972792864768
DEFAULT_DEBUG_DIR = "logs/vector_db/sam3_debug_visual_test"
DEFAULT_BATCH_DEBUG_DIR = "logs/vector_db/sam3_debug_visual_batch"
DEFAULT_PROMPT = "toilet lid assembly"
DEFAULT_BATCH_LIMIT = 50


async def _load_sample_record(item_id: int, preferred_image_id: int | None):
    async with SessionLocal() as session:
        item = await Items.get_item_by_id(session, item_id)
        if item is None:
            raise AssertionError(f"配件不存在: item_id={item_id}")

        image_result = await SgoItemImages.list_item_images_by_item_id(session, item_id)
        images = list(image_result) if image_result else []
        if len(images) == 0:
            raise AssertionError(f"配件没有图片: item_id={item_id}")

        target_image = None
        if preferred_image_id is not None:
            target_image = next((img for img in images if int(img.id) == preferred_image_id), None)
            if target_image is None:
                raise AssertionError(
                    f"未找到指定图片: item_id={item_id}, image_id={preferred_image_id}"
                )

        if target_image is None:
            target_image = images[0]

        return {
            "item_id": int(item.id),
            "item_name": item.item_name,
            "item_code": item.item_code,
            "image_id": int(target_image.id),
            "image_url": target_image.image_url,
        }


async def _load_batch_sample_records(limit: int, candidate_limit: int | None = None):
    if limit <= 0:
        raise AssertionError(f"limit 必须大于 0，当前: {limit}")

    effective_candidate_limit = candidate_limit or max(limit * 30, 1000)

    async with SessionLocal() as session:
        stmt = (
            select(
                Items.id.label("item_id"),
                Items.item_name.label("item_name"),
                Items.item_code.label("item_code"),
                SgoItemImages.id.label("image_id"),
                SgoItemImages.image_url.label("image_url"),
            )
            .join(SgoItemImages, SgoItemImages.item_id == Items.id)
            .where(Items.item_name.is_not(None))
            .where(Items.item_name != "")
            .where(SgoItemImages.image_url.is_not(None))
            .where(SgoItemImages.image_url != "")
            .order_by(SgoItemImages.id.asc())
            .limit(effective_candidate_limit)
        )
        result = await session.execute(stmt)
        rows = [dict(row._mapping) for row in result]

    records = _select_unique_sample_records(rows, limit=limit)
    if len(records) < limit:
        raise AssertionError(
            "可用于 SAM3 批量测试的不同配件不足，"
            f"需要 {limit} 条，实际只找到 {len(records)} 条；"
            f" candidate_limit={effective_candidate_limit}"
        )
    return records


def _select_unique_sample_records(rows: list[dict[str, Any]], limit: int):
    selected: list[dict[str, Any]] = []
    seen_item_ids: set[int] = set()

    for row in rows:
        item_id = int(row["item_id"])
        if item_id in seen_item_ids:
            continue

        seen_item_ids.add(item_id)
        record = {
            "item_id": item_id,
            "item_name": row["item_name"],
            "image_id": int(row["image_id"]),
            "image_url": row["image_url"],
        }
        if row.get("item_code") is not None:
            record["item_code"] = row["item_code"]

        selected.append(record)
        if len(selected) >= limit:
            break

    return selected


def _resolve_prompt_override(
    sample: dict[str, Any],
    prompt_override: str,
    use_llm_translation: bool,
    default_prompt: str,
):
    cleaned_prompt = prompt_override.strip()
    if cleaned_prompt:
        return cleaned_prompt

    if use_llm_translation:
        return None

    if int(sample["item_id"]) == DEFAULT_ITEM_ID and default_prompt:
        return default_prompt

    return None


def _parse_bool_env(env_name: str, default: bool = False) -> bool:
    value = os.getenv(env_name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _find_latest_debug_dir(debug_root: Path, image_id: int) -> Path:
    candidates = sorted(
        p for p in debug_root.glob(f"{image_id}_*") if p.is_dir()
    )
    if not candidates:
        raise AssertionError(f"未生成调试目录: debug_root={debug_root}, image_id={image_id}")
    return candidates[-1]


def _build_compare_image(debug_dir: Path) -> Path:
    original = Image.open(debug_dir / "1_original.jpg").convert("RGB")
    mask = Image.open(debug_dir / "2_mask.jpg").convert("L").convert("RGB")
    result = Image.open(debug_dir / "3_result.jpg").convert("RGB")

    panel_height = max(original.height, mask.height, result.height)
    panels = []
    for image in (original, mask, result):
        contained = ImageOps.contain(image, (max(image.width, 1), panel_height))
        if contained.height < panel_height:
            contained = ImageOps.pad(
                contained,
                (contained.width, panel_height),
                color=(255, 255, 255),
                centering=(0.5, 0.5),
            )
        panels.append(contained)

    compare_width = sum(image.width for image in panels)
    compare = Image.new("RGB", (compare_width, panel_height), (255, 255, 255))

    cursor_x = 0
    for panel in panels:
        compare.paste(panel, (cursor_x, 0))
        cursor_x += panel.width

    compare_path = debug_dir / "4_compare.jpg"
    compare.save(compare_path, "JPEG", quality=95)
    return compare_path


def _extract_text_prompt_from_info(debug_dir: Path) -> str | None:
    info_path = debug_dir / "info.txt"
    if not info_path.exists():
        return None

    with open(info_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("Text Prompt:"):
                return line.split(":", 1)[1].strip()

    return None


def _extract_info_fields(debug_dir: Path) -> dict[str, str]:
    info_path = debug_dir / "info.txt"
    fields: dict[str, str] = {}
    if not info_path.exists():
        return fields

    with open(info_path, "r", encoding="utf-8") as f:
        for line in f:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def _build_image_loader():
    from csrcqsf.modules.railway_parts.vector_search.repositories.image_loader import (
        ImageLoader,
    )

    return ImageLoader(
        minio_endpoint=minio_endpoint,
        minio_access_key=minio_access_key,
        minio_secret_key=minio_secret_key,
        minio_bucket=minio_bucket,
        minio_secure=minio_secure,
    )


def _build_preprocessor(debug_root: Path):
    from csrcqsf.modules.railway_parts.vector_search.preprocessing.sam3_preprocessor import (
        SAM3Preprocessor,
    )

    assert Path(sam3_model_path).exists(), f"SAM3 模型路径不存在: {sam3_model_path}"
    debug_root.mkdir(parents=True, exist_ok=True)

    return SAM3Preprocessor(
        model_path=str(sam3_model_path),
        save_debug_images=True,
        debug_output_dir=str(debug_root),
    )


def _run_visual_case(
    *,
    preprocessor,
    image_loader,
    sample: dict[str, Any],
    debug_root: Path,
    prompt_override: str | None,
):
    image = image_loader.load_image(sample["image_url"])
    assert image is not None, f"图片加载失败: {sample['image_url']}"

    original_extract_prompt = preprocessor.extract_prompt_from_name
    if prompt_override is not None:
        preprocessor.extract_prompt_from_name = lambda _item_name: prompt_override  # type: ignore[method-assign]

    try:
        result = preprocessor.preprocess_image(
            image=image,
            item_name=sample["item_name"],
            image_id=sample["image_id"],
        )
    finally:
        preprocessor.extract_prompt_from_name = original_extract_prompt

    assert result is not None, (
        "SAM3 预处理返回 None，未生成可视化输出；"
        f" item_id={sample['item_id']}, image_id={sample['image_id']}"
    )

    latest_debug_dir = _find_latest_debug_dir(debug_root, sample["image_id"])
    original_path = latest_debug_dir / "1_original.jpg"
    mask_path = latest_debug_dir / "2_mask.jpg"
    result_path = latest_debug_dir / "3_result.jpg"

    assert original_path.exists()
    assert mask_path.exists()
    assert result_path.exists()

    mask_np = np.array(Image.open(mask_path).convert("L"))
    assert mask_np.max() > 0, "mask 全黑，说明没有前景"
    assert np.count_nonzero(mask_np) < mask_np.size, "mask 全白，说明没有背景被去除"

    compare_path = _build_compare_image(latest_debug_dir)
    text_prompt = _extract_text_prompt_from_info(latest_debug_dir)

    return {
        **sample,
        "text_prompt": text_prompt,
        "debug_dir": str(latest_debug_dir),
        "compare_path": str(compare_path),
        "mask_nonzero_pixels": int(np.count_nonzero(mask_np)),
        "mask_total_pixels": int(mask_np.size),
        "mask_ratio": float(np.count_nonzero(mask_np) / max(mask_np.size, 1)),
    }


def _write_batch_summary(debug_root: Path, results: list[dict[str, Any]]) -> Path:
    summary_path = debug_root / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "total": len(results),
                "success_count": sum(1 for item in results if item["success"]),
                "failure_count": sum(1 for item in results if not item["success"]),
                "items": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    return summary_path


@pytest.mark.skipif(
    os.getenv("RUN_SAM3_VISUAL_TEST") != "1",
    reason="手动可视化测试；运行前请设置 RUN_SAM3_VISUAL_TEST=1",
)
def test_sam3_preprocessor_visual_outputs_debug_images():
    """
    手动可视化测试：
    1. 从 PG 查询真实配件图片
    2. 调用 SAM3Preprocessor.preprocess_image
    3. 将原图、mask、结果图、对比图保存到 sam3_debug 目录

    默认使用我们日志中已成功分割的一条样本：
    - item_id=1970402822689427456
    - image_id=1982687972792864768

    如需切换样本，可设置：
    - SAM3_VISUAL_ITEM_ID
    - SAM3_VISUAL_IMAGE_ID
    - SAM3_VISUAL_TEXT_PROMPT
    - SAM3_VISUAL_USE_LLM_TRANSLATION=1
    - SAM3_VISUAL_DEBUG_DIR
    """
    item_id = int(os.getenv("SAM3_VISUAL_ITEM_ID", str(DEFAULT_ITEM_ID)))
    image_id = int(os.getenv("SAM3_VISUAL_IMAGE_ID", str(DEFAULT_IMAGE_ID)))
    debug_root = Path(os.getenv("SAM3_VISUAL_DEBUG_DIR", DEFAULT_DEBUG_DIR))
    prompt_override = os.getenv("SAM3_VISUAL_TEXT_PROMPT", "").strip()
    use_llm_translation = _parse_bool_env("SAM3_VISUAL_USE_LLM_TRANSLATION", default=False)

    sample = asyncio.run(_load_sample_record(item_id=item_id, preferred_image_id=image_id))

    resolved_prompt_override = _resolve_prompt_override(
        sample,
        prompt_override=prompt_override,
        use_llm_translation=use_llm_translation,
        default_prompt=DEFAULT_PROMPT,
    )

    image_loader = _build_image_loader()
    preprocessor = _build_preprocessor(debug_root)
    result = _run_visual_case(
        preprocessor=preprocessor,
        image_loader=image_loader,
        sample=sample,
        debug_root=debug_root,
        prompt_override=resolved_prompt_override,
    )

    print("\nSAM3 可视化输出已生成:")
    print(f"  item_id: {result['item_id']}")
    print(f"  item_name: {result['item_name']}")
    print(f"  image_id: {result['image_id']}")
    print(f"  image_url: {result['image_url']}")
    print(f"  text_prompt: {result['text_prompt']}")
    print(f"  debug_dir: {result['debug_dir']}")
    print(f"  compare: {result['compare_path']}")


@pytest.mark.skipif(
    os.getenv("RUN_SAM3_VISUAL_BATCH_TEST") != "1",
    reason="手动批量可视化测试；运行前请设置 RUN_SAM3_VISUAL_BATCH_TEST=1",
)
def test_sam3_preprocessor_visual_outputs_debug_images_batch():
    """
    手动批量可视化测试：
    1. 从 PG 中挑选 N 个不同配件，每个配件取第一张图片
    2. 复用同一个 SAM3Preprocessor 实例逐条执行分割
    3. 为每条样本保存调试图，并输出 summary.json 方便人工抽查

    建议配合环境变量：
    - RUN_SAM3_VISUAL_BATCH_TEST=1
    - SAM3_VISUAL_USE_LLM_TRANSLATION=1
    - SAM3_VISUAL_BATCH_LIMIT=50
    - SAM3_VISUAL_BATCH_DEBUG_DIR=logs/vector_db/sam3_debug_visual_batch
    - SAM3_VISUAL_BATCH_CANDIDATE_LIMIT=2000
    - SAM3_VISUAL_MIN_SUCCESS_COUNT=1
    """
    limit = int(os.getenv("SAM3_VISUAL_BATCH_LIMIT", str(DEFAULT_BATCH_LIMIT)))
    candidate_limit = int(
        os.getenv("SAM3_VISUAL_BATCH_CANDIDATE_LIMIT", str(max(limit * 30, 1000)))
    )
    min_success_count = int(os.getenv("SAM3_VISUAL_MIN_SUCCESS_COUNT", "1"))
    debug_root = Path(os.getenv("SAM3_VISUAL_BATCH_DEBUG_DIR", DEFAULT_BATCH_DEBUG_DIR))
    prompt_override = os.getenv("SAM3_VISUAL_TEXT_PROMPT", "").strip()
    use_llm_translation = _parse_bool_env("SAM3_VISUAL_USE_LLM_TRANSLATION", default=True)

    samples = asyncio.run(_load_batch_sample_records(limit=limit, candidate_limit=candidate_limit))
    image_loader = _build_image_loader()
    preprocessor = _build_preprocessor(debug_root)

    results: list[dict[str, Any]] = []
    for sample in samples:
        resolved_prompt_override = _resolve_prompt_override(
            sample,
            prompt_override=prompt_override,
            use_llm_translation=use_llm_translation,
            default_prompt=DEFAULT_PROMPT,
        )
        try:
            output = _run_visual_case(
                preprocessor=preprocessor,
                image_loader=image_loader,
                sample=sample,
                debug_root=debug_root,
                prompt_override=resolved_prompt_override,
            )
            results.append(
                {
                    **output,
                    "success": True,
                    "error": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    **sample,
                    "text_prompt": None,
                    "debug_dir": None,
                    "compare_path": None,
                    "mask_nonzero_pixels": None,
                    "mask_total_pixels": None,
                    "mask_ratio": None,
                    "success": False,
                    "error": str(exc),
                }
            )

    summary_path = _write_batch_summary(debug_root, results)
    success_count = sum(1 for item in results if item["success"])
    failure_count = len(results) - success_count

    print("\nSAM3 批量可视化输出已生成:")
    print(f"  total: {len(results)}")
    print(f"  success_count: {success_count}")
    print(f"  failure_count: {failure_count}")
    print(f"  summary: {summary_path}")

    for item in results[:10]:
        print(
            "  - "
            f"item_id={item['item_id']}, image_id={item['image_id']}, "
            f"success={item['success']}, prompt={item['text_prompt']}, "
            f"compare={item['compare_path']}"
        )

    assert len(results) == limit
    assert success_count >= min_success_count, (
        f"成功样本数不足: success_count={success_count}, "
        f"min_success_count={min_success_count}, summary={summary_path}"
    )


def test_select_unique_sample_records_keeps_first_image_per_item():
    rows = [
        {"item_id": 1, "item_name": "A", "image_id": 101, "image_url": "a-1.jpg"},
        {"item_id": 1, "item_name": "A", "image_id": 102, "image_url": "a-2.jpg"},
        {"item_id": 2, "item_name": "B", "image_id": 201, "image_url": "b-1.jpg"},
        {"item_id": 3, "item_name": "C", "image_id": 301, "image_url": "c-1.jpg"},
    ]

    result = _select_unique_sample_records(rows, limit=2)

    assert result == [
        {"item_id": 1, "item_name": "A", "image_id": 101, "image_url": "a-1.jpg"},
        {"item_id": 2, "item_name": "B", "image_id": 201, "image_url": "b-1.jpg"},
    ]


def test_resolve_prompt_override_prefers_explicit_override_and_llm_mode():
    sample = {
        "item_id": DEFAULT_ITEM_ID,
        "item_name": "座便器盖组成",
        "image_id": DEFAULT_IMAGE_ID,
        "image_url": "sample.jpg",
    }

    assert _resolve_prompt_override(
        sample,
        prompt_override="manual prompt",
        use_llm_translation=False,
        default_prompt=DEFAULT_PROMPT,
    ) == "manual prompt"

    assert _resolve_prompt_override(
        sample,
        prompt_override="",
        use_llm_translation=True,
        default_prompt=DEFAULT_PROMPT,
    ) is None

    assert _resolve_prompt_override(
        sample,
        prompt_override="",
        use_llm_translation=False,
        default_prompt=DEFAULT_PROMPT,
    ) == DEFAULT_PROMPT


def test_extract_text_prompt_from_info_reads_selected_prompt_and_candidates(tmp_path):
    info_dir = tmp_path / "9001_20260427_000000"
    info_dir.mkdir(parents=True)
    (info_dir / "info.txt").write_text(
        "\n".join(
            [
                "Text Prompt: bracket",
                "Prompt Candidates: [\"support\", \"bracket\"]",
                "Selected Prompt: bracket",
                "Index Strategy: original_plus_segmented",
            ]
        ),
        encoding="utf-8",
    )

    fields = _extract_info_fields(info_dir)

    assert fields["Text Prompt"] == "bracket"
    assert fields["Selected Prompt"] == "bracket"
    assert fields["Index Strategy"] == "original_plus_segmented"
