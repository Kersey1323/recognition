from unittest.mock import MagicMock, patch

from pymilvus import DataType

from csrcqsf.modules.railway_parts.vector_search.storage.collection_manager import (
    CollectionManager,
)


class _Iterator:
    def __init__(self, batches):
        self._batches = list(batches)

    def next(self):
        return self._batches.pop(0) if self._batches else []

    def close(self):
        return None


def test_get_collection_item_image_ids_dedupes_variants_per_source_image():
    manager = object.__new__(CollectionManager)
    manager.client = MagicMock()
    manager.client.has_collection.return_value = True
    manager.client.query_iterator.return_value = _Iterator(
        [
            [
                {"item_id": 101, "image_id": 9001, "image_variant": "original"},
                {"item_id": 101, "image_id": 9001, "image_variant": "sam3_segmented"},
                {"item_id": 101, "image_id": 9002, "image_variant": "original"},
                {"item_id": 202, "image_id": 9901, "image_variant": "original"},
            ],
            [],
        ]
    )

    image_ids = manager.get_collection_item_image_ids("PARTS_SIGLIP_TEST")

    assert image_ids == {
        101: {9001, 9002},
        202: {9901},
    }


def test_create_siglip_collection_adds_image_variant_field():
    manager = object.__new__(CollectionManager)
    manager.client = MagicMock()
    fake_schema = MagicMock()
    fake_index_params = MagicMock()
    manager.client.prepare_index_params.return_value = fake_index_params

    with patch.object(manager, "collection_exists", return_value=False), patch(
        "csrcqsf.modules.railway_parts.vector_search.storage.collection_manager.MilvusClient.create_schema",
        return_value=fake_schema,
    ):
        manager.create_siglip_collection("PARTS_SIGLIP_TEST")

    fake_schema.add_field.assert_any_call(
        field_name="image_variant",
        datatype=DataType.VARCHAR,
        max_length=32,
    )


def test_collection_has_field_reads_described_schema():
    manager = object.__new__(CollectionManager)
    manager.client = MagicMock()
    manager.client.has_collection.return_value = True
    manager.client.describe_collection.return_value = {
        "fields": [
            {"name": "item_id"},
            {"name": "image_id"},
            {"name": "image_variant"},
        ]
    }

    assert manager.collection_has_field("PARTS_SIGLIP_TEST", "image_variant") is True
    assert manager.collection_has_field("PARTS_SIGLIP_TEST", "patch_tokens_path") is False


def test_create_dinov2_collection_keeps_legacy_path_and_adds_patch_token_key():
    manager = object.__new__(CollectionManager)
    manager.client = MagicMock()
    fake_schema = MagicMock()
    fake_index_params = MagicMock()
    manager.client.prepare_index_params.return_value = fake_index_params

    with patch.object(manager, "collection_exists", return_value=False), patch(
        "csrcqsf.modules.railway_parts.vector_search.storage.collection_manager.MilvusClient.create_schema",
        return_value=fake_schema,
    ):
        manager.create_dinov2_collection("PARTS_DINOV2_TEST")

    fake_schema.add_field.assert_any_call(
        field_name="patch_token_key",
        datatype=DataType.VARCHAR,
        max_length=500,
    )
    fake_schema.add_field.assert_any_call(
        field_name="patch_tokens_path",
        datatype=DataType.VARCHAR,
        max_length=500,
    )
