import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from PIL import Image

from csrcqsf.infra.external.model_client import ModelServiceError
from csrcqsf.modules.railway_parts.services import parts_index_service


class AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def extraction_result():
    return SimpleNamespace(
        segmented_image=Image.new("RGB", (2, 2), "black"),
        bbox=(1, 2, 2, 2),
        mask_area=4,
        selected_prompt="object",
        detection_score=0.8,
        siglip_vector=np.asarray([0.1, 0.2], dtype=np.float32),
        dinov2_global_vector=np.asarray([0.3, 0.4], dtype=np.float32),
        dinov2_patch_tokens=np.asarray([[0.5, 0.6]], dtype=np.float32),
    )


def build_scenario(images, *, extraction_side_effect=None, existing=None):
    session = AsyncMock()
    item = SimpleNamespace(
        id=101,
        item_name="橡胶套",
        item_code="40000543491",
        has_v2_index=0,
    )
    model_client = SimpleNamespace(
        require_indexing_extract_capability=AsyncMock(),
        siglip_text_features=AsyncMock(
            return_value=np.asarray([0.7, 0.8], dtype=np.float32)
        ),
        indexing_extract=AsyncMock(
            side_effect=extraction_side_effect
            if extraction_side_effect is not None
            else [extraction_result() for _ in images]
        ),
        siglip_image_features=AsyncMock(
            return_value=np.asarray([0.1, 0.2], dtype=np.float32)
        ),
        dinov2_global_vector=AsyncMock(
            return_value=np.asarray([0.3, 0.4], dtype=np.float32)
        ),
        dinov2_patch_tokens=AsyncMock(
            return_value=np.asarray([[0.5, 0.6]], dtype=np.float32)
        ),
    )
    manager = SimpleNamespace(
        index_precomputed_features=AsyncMock(return_value=(True, True)),
        delete_item_patch_tokens=MagicMock(return_value=0),
    )
    state_manager = SimpleNamespace(
        delete_item_index=MagicMock(
            return_value={"siglip_deleted": 0, "dinov2_deleted": 0}
        )
    )
    segmented_record = SimpleNamespace(
        id=7001,
        segmented_image_url="bfr-ai-files/segmented/101/9001/a.png",
        bbox_x=1,
        bbox_y=2,
        bbox_w=2,
        bbox_h=2,
        mask_area=4,
    )
    segmented_service = SimpleNamespace(
        get_latest_success=AsyncMock(return_value=existing),
        persist_success=AsyncMock(return_value=segmented_record),
        persist_failure=AsyncMock(),
        load_image=AsyncMock(return_value=Image.new("RGB", (2, 2), "black")),
        mark_indexed=AsyncMock(),
        remove_source_artifacts=AsyncMock(return_value=0),
    )
    items_model = SimpleNamespace(get_item_by_id=AsyncMock(return_value=item))
    images_model = SimpleNamespace(
        list_item_images_by_item_id=AsyncMock(return_value=images),
        indexed_image=AsyncMock(),
        un_indexed_image=AsyncMock(),
    )
    runtime = SimpleNamespace(
        SessionLocal=lambda: AsyncSessionContext(session),
        Items=items_model,
        SgoItemImages=images_model,
        SegmentedImageService=lambda _session: segmented_service,
        get_model_client=lambda: model_client,
        ModelServiceError=ModelServiceError,
        _get_milvus_manager_v2_cls=lambda: lambda: manager,
        _get_milvus_state_manager_v2_cls=lambda: lambda: state_manager,
        logger=MagicMock(),
        datetime=datetime,
    )
    railway_manager = SimpleNamespace(
        get_image_from_oss=AsyncMock(
            return_value=np.zeros((2, 2, 3), dtype=np.uint8)
        ),
        sync_item_v2_index_state=AsyncMock(),
    )
    return SimpleNamespace(
        session=session,
        item=item,
        model_client=model_client,
        manager=manager,
        state_manager=state_manager,
        segmented_service=segmented_service,
        runtime=runtime,
        railway_manager=railway_manager,
    )


def test_rebuild_requires_composite_model_capability_before_opening_database():
    model_client = SimpleNamespace(
        require_indexing_extract_capability=AsyncMock(
            side_effect=RuntimeError("SAM2 model missing")
        )
    )
    runtime = SimpleNamespace(
        get_model_client=lambda: model_client,
        SessionLocal=MagicMock(),
    )

    with pytest.raises(RuntimeError, match="SAM2 model missing"):
        asyncio.run(
            parts_index_service.rebuild_v2_index(
                SimpleNamespace(),
                item_id=101,
                runtime=runtime,
            )
        )

    runtime.SessionLocal.assert_not_called()


def test_rebuild_segments_only_createbyself_and_indexes_other_sources_original():
    images = [
        SimpleNamespace(id=9001, image_url="bfr-ai-files/a.jpg", image_source="BASEINFO"),
        SimpleNamespace(id=9002, image_url="bfr-ai-files/b.jpg", image_source="INQUERY"),
        SimpleNamespace(id=9003, image_url="bfr-ai-files/c.jpg", image_source="CREATEBYSELF"),
    ]
    scenario = build_scenario(images)

    result = asyncio.run(
        parts_index_service.rebuild_v2_index(
            scenario.railway_manager,
            item_id=101,
            runtime=scenario.runtime,
        )
    )

    scenario.model_client.require_indexing_extract_capability.assert_awaited_once()
    assert scenario.model_client.indexing_extract.await_count == 1
    assert scenario.segmented_service.get_latest_success.await_count == 1
    assert [
        call.args[1]
        for call in scenario.segmented_service.get_latest_success.await_args_list
    ] == [9003]
    assert scenario.segmented_service.persist_success.await_count == 1
    assert scenario.model_client.siglip_image_features.await_count == 2
    assert scenario.model_client.dinov2_global_vector.await_count == 2
    assert scenario.model_client.dinov2_patch_tokens.await_count == 2
    assert scenario.manager.index_precomputed_features.await_count == 3
    calls_by_image_id = {
        call.kwargs["image_id"]: call.kwargs
        for call in scenario.manager.index_precomputed_features.await_args_list
    }
    assert calls_by_image_id[9001]["image_url"] == "bfr-ai-files/a.jpg"
    assert calls_by_image_id[9001]["image_variant"] == "original"
    assert calls_by_image_id[9002]["image_url"] == "bfr-ai-files/b.jpg"
    assert calls_by_image_id[9002]["image_variant"] == "original"
    assert calls_by_image_id[9003]["image_variant"] == "segmented"
    assert result["segmented_count"] == 1
    assert result["fallback_count"] == 0
    assert result["success_count"] == 3


def test_foreground_detection_error_falls_back_to_original_features():
    image = SimpleNamespace(
        id=9001,
        image_url="bfr-ai-files/a.jpg",
        image_source="CREATEBYSELF",
    )
    scenario = build_scenario(
        [image],
        extraction_side_effect=ModelServiceError(
            422,
            "no foreground",
            error_code="foreground_not_detected",
        ),
    )

    result = asyncio.run(
        parts_index_service.rebuild_v2_index(
            scenario.railway_manager,
            item_id=101,
            runtime=scenario.runtime,
        )
    )

    scenario.segmented_service.persist_failure.assert_awaited_once()
    scenario.model_client.siglip_image_features.assert_awaited_once()
    call = scenario.manager.index_precomputed_features.await_args.kwargs
    assert call["image_url"] == "bfr-ai-files/a.jpg"
    assert call["image_variant"] == "original"
    assert result["fallback_count"] == 1
    assert result["success_count"] == 1


def test_invalid_foreground_mask_falls_back_to_original_features():
    image = SimpleNamespace(
        id=9001,
        image_url="bfr-ai-files/a.jpg",
        image_source="CREATEBYSELF",
    )
    scenario = build_scenario(
        [image],
        extraction_side_effect=ModelServiceError(
            422,
            "turntable-like mask",
            error_code="invalid_foreground_mask",
        ),
    )

    result = asyncio.run(
        parts_index_service.rebuild_v2_index(
            scenario.railway_manager,
            item_id=101,
            runtime=scenario.runtime,
        )
    )

    call = scenario.manager.index_precomputed_features.await_args.kwargs
    assert call["image_url"] == "bfr-ai-files/a.jpg"
    assert call["image_variant"] == "original"
    assert result["fallback_count"] == 1
    assert result["success_count"] == 1


def test_model_service_unavailable_does_not_silently_fallback():
    image = SimpleNamespace(
        id=9001,
        image_url="bfr-ai-files/a.jpg",
        image_source="CREATEBYSELF",
    )
    scenario = build_scenario(
        [image],
        extraction_side_effect=ModelServiceError(503, "model unavailable"),
    )

    result = asyncio.run(
        parts_index_service.rebuild_v2_index(
            scenario.railway_manager,
            item_id=101,
            runtime=scenario.runtime,
        )
    )

    scenario.model_client.siglip_image_features.assert_not_awaited()
    scenario.manager.index_precomputed_features.assert_not_awaited()
    assert result["fallback_count"] == 0
    assert result["fail_count"] == 1
    scenario.session.commit.assert_awaited()


def test_existing_segmented_image_is_reused_without_running_segmentation_again():
    image = SimpleNamespace(
        id=9001,
        image_url="bfr-ai-files/a.jpg",
        image_source="CREATEBYSELF",
    )
    existing = SimpleNamespace(
        id=7001,
        segmented_image_url="bfr-ai-files/segmented/101/9001/a.png",
    )
    scenario = build_scenario([image], existing=existing)

    result = asyncio.run(
        parts_index_service.rebuild_v2_index(
            scenario.railway_manager,
            item_id=101,
            runtime=scenario.runtime,
        )
    )

    scenario.model_client.indexing_extract.assert_not_awaited()
    scenario.segmented_service.load_image.assert_awaited_once_with(existing)
    scenario.segmented_service.persist_success.assert_not_awaited()
    assert result["segmented_count"] == 1


def test_force_rebuild_removes_old_vectors_tokens_and_segmented_objects():
    images = [
        SimpleNamespace(id=9001, image_url="bfr-ai-files/a.jpg", image_source="BASEINFO")
    ]
    scenario = build_scenario(images)
    scenario.item.has_v2_index = 1

    asyncio.run(
        parts_index_service.rebuild_v2_index(
            scenario.railway_manager,
            item_id=101,
            rebuild_existing=True,
            runtime=scenario.runtime,
        )
    )

    scenario.state_manager.delete_item_index.assert_called_once_with(101)
    scenario.manager.delete_item_patch_tokens.assert_called_once_with(101)
    scenario.segmented_service.remove_source_artifacts.assert_awaited_once_with(
        101, 9001
    )
