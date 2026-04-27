from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager import (
    MilvusStateManagerV2,
)


def _fake_env():
    return SimpleNamespace(
        milvus_host="localhost",
        milvus_port=19530,
        siglip_collection_name="PARTS_SIGLIP_TEST",
        dinov2_collection_name="PARTS_DINOV2_TEST",
    )


def test_state_manager_init_only_builds_collection_manager():
    fake_collection_manager = MagicMock()

    with patch(
        "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager.get_config",
        return_value=_fake_env(),
    ), patch(
        "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager.CollectionManager",
        return_value=fake_collection_manager,
    ) as collection_cls:
        manager = MilvusStateManagerV2()

    collection_cls.assert_called_once_with(host="localhost", port=19530)
    assert manager.collection_manager is fake_collection_manager
    assert manager.siglip_collection == "PARTS_SIGLIP_TEST"
    assert manager.dinov2_collection == "PARTS_DINOV2_TEST"
    assert not hasattr(manager, "siglip_extractor")
    assert not hasattr(manager, "dinov2_extractor")
    assert not hasattr(manager, "sam3_preprocessor")


def test_state_manager_builds_statistics_and_item_snapshot_from_collection_manager():
    fake_collection_manager = MagicMock()
    fake_collection_manager.get_collection_item_image_ids.side_effect = [
        {101: {9001, 9002}, 102: {9101}, 999: {9901, 9902}},
        {102: {9101}, 103: {9301}, 104: {9401}},
        {101: {9001, 9002}, 102: {9101}, 999: {9901, 9902}},
        {102: {9101}, 103: {9301}, 104: {9401}},
    ]

    with patch(
        "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager.get_config",
        return_value=_fake_env(),
    ), patch(
        "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager.CollectionManager",
        return_value=fake_collection_manager,
    ):
        manager = MilvusStateManagerV2()
        stats = manager.get_statistics_snapshot()
        state = manager.get_item_index_state_snapshot()

    assert stats == {
        "siglip_count": 5,
        "dinov2_count": 3,
        "siglip_item_ids": {101, 102, 999},
        "dinov2_item_ids": {102, 103, 104},
    }
    assert state == {
        101: {"has_v2_index": 0, "v2_indexed_image_num": 0},
        102: {"has_v2_index": 1, "v2_indexed_image_num": 1},
        103: {"has_v2_index": 0, "v2_indexed_image_num": 0},
        104: {"has_v2_index": 0, "v2_indexed_image_num": 0},
        999: {"has_v2_index": 0, "v2_indexed_image_num": 0},
    }


def test_state_manager_delete_create_and_drop_delegate_to_collection_manager():
    fake_collection_manager = MagicMock()
    fake_collection_manager.delete_by_item_id.side_effect = [3, 2]
    fake_collection_manager.collection_exists.side_effect = [True, False]

    with patch(
        "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager.get_config",
        return_value=_fake_env(),
    ), patch(
        "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager.CollectionManager",
        return_value=fake_collection_manager,
    ):
        manager = MilvusStateManagerV2()
        delete_result = manager.delete_item_index(1935558010375340032)
        manager.create_collections()
        manager.drop_collections()

    assert delete_result == {"siglip_deleted": 3, "dinov2_deleted": 2}
    fake_collection_manager.create_siglip_collection.assert_called_once_with("PARTS_SIGLIP_TEST")
    fake_collection_manager.create_dinov2_collection.assert_called_once_with("PARTS_DINOV2_TEST")
    fake_collection_manager.drop_collection.assert_called_once_with("PARTS_SIGLIP_TEST")


def test_state_manager_get_indexed_images_by_item_id_uses_intersection_of_two_collections():
    fake_collection_manager = MagicMock()
    fake_collection_manager.get_collection_image_records.side_effect = [
        {
            9001: "bfr-ai-files/a.jpg",
            9002: "bfr-ai-files/b.jpg",
        },
        {
            9002: "bfr-ai-files/b.jpg",
            9003: "bfr-ai-files/c.jpg",
        },
    ]

    with patch(
        "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager.get_config",
        return_value=_fake_env(),
    ), patch(
        "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager.CollectionManager",
        return_value=fake_collection_manager,
    ):
        manager = MilvusStateManagerV2()
        indexed_images = manager.get_indexed_images_by_item_id(101)

    assert indexed_images == {
        9002: "bfr-ai-files/b.jpg",
    }


def test_state_manager_snapshot_counts_unique_source_images_instead_of_variant_rows():
    fake_collection_manager = MagicMock()
    fake_collection_manager.get_collection_item_image_ids.side_effect = [
        {101: {9001, 9002}, 102: {9101}},
        {101: {9002}, 102: {9101, 9102}},
        {101: {9001, 9002}, 102: {9101}},
        {101: {9002}, 102: {9101, 9102}},
    ]

    with patch(
        "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager.get_config",
        return_value=_fake_env(),
    ), patch(
        "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager.CollectionManager",
        return_value=fake_collection_manager,
    ):
        manager = MilvusStateManagerV2()
        stats = manager.get_statistics_snapshot()
        snapshot = manager.get_item_index_state_snapshot()

    assert stats["siglip_count"] == 3
    assert stats["dinov2_count"] == 3
    assert snapshot[101] == {"has_v2_index": 1, "v2_indexed_image_num": 1}
    assert snapshot[102] == {"has_v2_index": 1, "v2_indexed_image_num": 1}
