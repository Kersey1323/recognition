import asyncio
from unittest.mock import MagicMock

import numpy as np
from PIL import Image

from csrcqsf.biz.railwayparts.vector_db.preprocessing.sam3_preprocessor import (
    SAM3PreprocessOutcome,
)
from csrcqsf.biz.railwayparts.vector_db.storage.milvus_manager import MilvusManagerV2


def _build_manager(tmp_path):
    manager = object.__new__(MilvusManagerV2)
    manager.siglip_collection = "SIGLIP_TEST"
    manager.dinov2_collection = "DINOV2_TEST"
    manager.patch_tokens_dir = str(tmp_path)
    manager.collection_manager = MagicMock()
    manager.siglip_extractor = MagicMock()
    manager.dinov2_extractor = MagicMock()
    manager.sam3_preprocessor = MagicMock()
    manager.siglip_extractor.extract_image_features.return_value = np.array([0.1, 0.2])
    manager.siglip_extractor.extract_text_features.return_value = np.array([0.3, 0.4])
    manager.dinov2_extractor.extract_global_vector.return_value = np.array([0.5, 0.6])
    manager.dinov2_extractor.extract_patch_tokens.return_value = np.array(
        [[0.7, 0.8], [0.9, 1.0]]
    )
    manager.dinov2_extractor.save_patch_tokens = MagicMock()
    return manager


def test_index_image_writes_original_and_segmented_variants_when_sam3_succeeds(tmp_path):
    manager = _build_manager(tmp_path)
    manager.sam3_preprocessor.preprocess_image_with_metadata.return_value = SAM3PreprocessOutcome(
        result_image=Image.new("RGB", (4, 4), "white"),
        original_item_name="特殊螺栓M10X40",
        normalized_item_name="特殊螺栓",
        prompt_candidates=["bolt", "object"],
        selected_prompt="bolt",
        attempt_count=1,
    )

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
    assert [record["image_variant"] for record in siglip_records] == [
        "original",
        "sam3_segmented",
    ]
    assert [record["image_variant"] for record in dinov2_records] == [
        "original",
        "sam3_segmented",
    ]
    assert dinov2_records[0]["patch_tokens_path"].endswith("_original.npy")
    assert dinov2_records[1]["patch_tokens_path"].endswith("_sam3_segmented.npy")
    assert manager.last_preprocess_outcome.selected_prompt == "bolt"


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
    segmented_image = Image.new("RGB", (4, 4), "white")
    manager.sam3_preprocessor.preprocess_image_with_metadata.return_value = SAM3PreprocessOutcome(
        result_image=segmented_image,
        original_item_name="特殊螺栓M10X40",
        normalized_item_name="特殊螺栓",
        prompt_candidates=["bolt", "object"],
        selected_prompt="bolt",
        attempt_count=1,
    )

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
    assert dinov2_records[0]["patch_tokens_path"].endswith("item_101_img_9001.npy")
    assert manager.siglip_extractor.extract_image_features.call_args.args[0] is segmented_image
    assert manager.dinov2_extractor.extract_global_vector.call_args.args[0] is segmented_image
