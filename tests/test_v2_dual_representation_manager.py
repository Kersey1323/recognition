import asyncio
import inspect
from unittest.mock import MagicMock

import numpy as np
from PIL import Image

from csrcqsf.modules.railway_parts.vector_search.storage.milvus_manager import (
    MilvusManagerV2,
)
from csrcqsf.modules.railway_parts.vector_search.indexing.indexer import VectorIndexer


class _FakeModelClient:
    async def siglip_text_features(self, text):
        return np.array([0.3, 0.4], dtype=float)

    async def siglip_image_features(self, image):
        return np.array([0.1, 0.2], dtype=float)

    async def dinov2_global_vector(self, image):
        return np.array([0.5, 0.6], dtype=float)

    async def dinov2_patch_tokens(self, image):
        return np.array([[0.7, 0.8], [0.9, 1.0]], dtype=float)


def _build_manager(tmp_path):
    manager = object.__new__(MilvusManagerV2)
    manager.siglip_collection = "SIGLIP_TEST"
    manager.dinov2_collection = "DINOV2_TEST"
    manager.patch_tokens_dir = str(tmp_path)
    manager.collection_manager = MagicMock()
    manager.model_client = _FakeModelClient()
    manager.image_variant_supported = True
    return manager


def test_vector_managers_do_not_expose_removed_sam3_switch():
    assert "enable_sam3" not in inspect.signature(MilvusManagerV2).parameters
    assert "enable_sam3" not in inspect.signature(VectorIndexer).parameters


def test_index_image_writes_only_original_variant(tmp_path):
    manager = _build_manager(tmp_path)

    siglip_ok, dinov2_ok = asyncio.run(
        manager.index_image(
            image=Image.new("RGB", (8, 8), "white"),
            item_id=101,
            item_name="特殊螺栓M10X40",
            item_code="40000543491",
            image_id=9001,
            image_url="bfr-ai-files/a.jpg",
            description="特殊螺栓M10X40",
        )
    )

    siglip_records = manager.collection_manager.insert_siglip_records.call_args.args[1]
    dinov2_records = manager.collection_manager.insert_dinov2_records.call_args.args[1]

    assert siglip_ok is True
    assert dinov2_ok is True
    assert [record["image_variant"] for record in siglip_records] == ["original"]
    assert [record["image_variant"] for record in dinov2_records] == ["original"]
    assert dinov2_records[0]["patch_tokens_path"].endswith("_original.npy")
    assert dinov2_records[0]["patch_token_key"] == "item_101_img_9001_original.npy"


def test_dedupe_hits_by_image_id_keeps_highest_scoring_variant():
    manager = object.__new__(MilvusManagerV2)
    hits = [
        {"entity": {"image_id": 9001, "image_variant": "original"}, "distance": 0.72},
        {
            "entity": {"image_id": 9001, "image_variant": "sam3_segmented"},
            "distance": 0.90,
        },
        {"entity": {"image_id": 9002, "image_variant": "original"}, "distance": 0.81},
    ]

    deduped = manager._dedupe_hits_by_image_id(hits)

    assert [hit["entity"]["image_id"] for hit in deduped] == [9001, 9002]
    assert deduped[0]["distance"] == 0.90


def test_index_image_falls_back_to_legacy_single_record_when_variant_field_missing(tmp_path):
    manager = _build_manager(tmp_path)
    manager.image_variant_supported = False

    siglip_ok, dinov2_ok = asyncio.run(
        manager.index_image(
            image=Image.new("RGB", (8, 8), "black"),
            item_id=101,
            item_name="特殊螺栓M10X40",
            item_code="40000543491",
            image_id=9001,
            image_url="bfr-ai-files/a.jpg",
            description="特殊螺栓M10X40",
        )
    )

    siglip_records = manager.collection_manager.insert_siglip_records.call_args.args[1]
    dinov2_records = manager.collection_manager.insert_dinov2_records.call_args.args[1]

    assert siglip_ok is True
    assert dinov2_ok is True
    assert len(siglip_records) == 1
    assert len(dinov2_records) == 1
    assert "image_variant" not in siglip_records[0]
    assert "image_variant" not in dinov2_records[0]
    assert dinov2_records[0]["patch_token_key"] == "item_101_img_9001.npy"
    assert dinov2_records[0]["patch_tokens_path"].endswith("item_101_img_9001.npy")


def test_resolve_patch_tokens_path_prefers_patch_token_key_and_falls_back_to_legacy_path(
    tmp_path,
):
    manager = object.__new__(MilvusManagerV2)
    manager.patch_tokens_dir = str(tmp_path)

    new_path = tmp_path / "nested" / "candidate.npy"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(new_path, np.array([[1.0, 2.0]], dtype=float))

    legacy_path = tmp_path / "legacy.npy"
    np.save(legacy_path, np.array([[3.0, 4.0]], dtype=float))

    assert manager._resolve_patch_tokens_path(
        {
            "patch_token_key": "nested/candidate.npy",
            "patch_tokens_path": str(legacy_path),
        }
    ) == str(new_path)

    assert manager._resolve_patch_tokens_path(
        {
            "patch_token_key": "missing.npy",
            "patch_tokens_path": str(legacy_path),
        }
    ) == str(legacy_path)


def test_resolve_patch_tokens_path_maps_legacy_source_tree_path_into_new_state_dir(tmp_path):
    manager = object.__new__(MilvusManagerV2)
    manager.patch_tokens_dir = str(tmp_path / "state" / "vector_db" / "patch_tokens")

    mapped_path = tmp_path / "state" / "vector_db" / "patch_tokens" / "nested" / "candidate.npy"
    mapped_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(mapped_path, np.array([[5.0, 6.0]], dtype=float))

    legacy_path = (
        "/home/ubuntu/project-train/recognition/"
        "csrcqsf/biz/railwayparts/vector_db/patch_tokens/nested/candidate.npy"
    )

    assert manager._resolve_patch_tokens_path(
        {
            "patch_tokens_path": legacy_path,
        }
    ) == str(mapped_path)


def test_search_by_image_dinov2_degrades_to_coarse_results_when_patch_tokens_missing(
    tmp_path,
):
    manager = object.__new__(MilvusManagerV2)
    manager.model_client = _FakeModelClient()
    manager.collection_manager = MagicMock()
    manager.dinov2_collection = "DINOV2_TEST"
    manager.image_variant_supported = False
    manager.patch_tokens_dir = str(tmp_path)

    manager.collection_manager.client.search.return_value = [[
        {
            "entity": {
                "item_id": 101,
                "item_name": "橡胶套",
                "item_code": "40000543491",
                "image_id": 9001,
                "image_url": "bfr-ai-files/a.jpg",
                "patch_token_key": "missing-a.npy",
                "patch_tokens_path": str(tmp_path / "missing-a.npy"),
            },
            "distance": 0.9,
        },
        {
            "entity": {
                "item_id": 102,
                "item_name": "橡胶垫",
                "item_code": "40000543492",
                "image_id": 9002,
                "image_url": "bfr-ai-files/b.jpg",
                "patch_token_key": "missing-b.npy",
                "patch_tokens_path": str(tmp_path / "missing-b.npy"),
            },
            "distance": 0.8,
        },
    ]]

    results = asyncio.run(
        manager._search_by_image_dinov2(
            image=Image.new("RGB", (8, 8), "white"),
            coarse_top_k=2,
            fine_top_k=2,
        )
    )

    assert [result["entity"]["image_id"] for result in results] == [9001, 9002]
    assert all(result["fine_rerank_skipped"] is True for result in results)
