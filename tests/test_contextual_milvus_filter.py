import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
from PIL import Image

from csrcqsf.modules.railway_parts.vector_search.storage.milvus_manager import (
    MilvusManagerV2,
)


def _manager_with_empty_search_results():
    manager = MilvusManagerV2.__new__(MilvusManagerV2)
    manager.siglip_collection = "siglip"
    manager.dinov2_collection = "dinov2"
    manager.image_variant_supported = False
    manager.patch_token_key_supported = False
    manager.model_client = SimpleNamespace(
        siglip_text_features=AsyncMock(return_value=np.zeros(4, dtype=np.float32)),
        siglip_image_features=AsyncMock(return_value=np.zeros(4, dtype=np.float32)),
        dinov2_global_vector=AsyncMock(return_value=np.zeros(4, dtype=np.float32)),
        dinov2_patch_tokens=AsyncMock(return_value=np.zeros((2, 4), dtype=np.float32)),
    )
    manager.collection_manager = SimpleNamespace(
        client=MagicMock(search=MagicMock(return_value=[[]]))
    )
    return manager


def test_contextual_filter_is_applied_to_text_and_all_image_search_modes():
    manager = _manager_with_empty_search_results()
    image = Image.new("RGB", (8, 8), "white")
    item_ids = [102, 101, 102]

    asyncio.run(manager.search_by_text("制动盘", top_k=10, item_ids=item_ids))
    asyncio.run(manager.search_by_image(image, mode="siglip", item_ids=item_ids))
    asyncio.run(manager.search_by_image(image, mode="dinov2", item_ids=item_ids))
    asyncio.run(manager.search_by_image(image, mode="hybrid", item_ids=item_ids))

    calls = manager.collection_manager.client.search.call_args_list
    assert len(calls) == 5
    assert all(call.kwargs["filter"] == "item_id in [101,102]" for call in calls)


def test_regular_search_does_not_send_an_empty_filter_to_milvus():
    manager = _manager_with_empty_search_results()

    asyncio.run(manager.search_by_text("制动盘", top_k=10))

    assert "filter" not in manager.collection_manager.client.search.call_args.kwargs


def test_grouped_siglip_search_requests_distinct_parts_before_truncation():
    manager = _manager_with_empty_search_results()
    manager.siglip_group_by_item = True
    asyncio.run(manager.search_by_image(Image.new("RGB", (8, 8)), top_k=20))
    kwargs = manager.collection_manager.client.search.call_args.kwargs
    assert kwargs["group_by_field"] == "item_id"
    assert kwargs["limit"] == 20
