from csrcqsf.modules.railway_parts.vector_search.storage.collection_manager import (
    CollectionManager,
)


class _FakeIterator:
    def __init__(self, batches):
        self._batches = list(batches)

    def __iter__(self):
        return iter(self._batches)


class _FakeQueryIterator:
    def __init__(self, batches):
        self._batches = list(batches)
        self.closed = False

    def next(self):
        if len(self._batches) == 0:
            return []
        return self._batches.pop(0)

    def close(self):
        self.closed = True


class _FakeClient:
    def __init__(self):
        self.deleted = []
        self.query_iterator_result = _FakeIterator(
            [
                [{"item_id": 101}, {"item_id": 102}],
                [{"item_id": 102}, {"item_id": 103}],
            ]
        )

    def has_collection(self, name):
        return name != "missing_collection"

    def get_collection_stats(self, collection_name):
        return {"row_count": "7"}

    def query_iterator(self, collection_name, filter, output_fields, batch_size):
        assert output_fields == ["item_id"]
        return self.query_iterator_result

    def delete(self, collection_name, filter):
        self.deleted.append((collection_name, filter))
        return {"delete_count": 4}


def test_get_collection_entity_count_returns_zero_when_collection_missing():
    manager = CollectionManager.__new__(CollectionManager)
    manager.client = _FakeClient()

    assert manager.get_collection_entity_count("missing_collection") == 0


def test_iter_collection_item_ids_deduplicates_values():
    manager = CollectionManager.__new__(CollectionManager)
    manager.client = _FakeClient()

    assert manager.iter_collection_item_ids("siglip_collection") == {101, 102, 103}


def test_iter_collection_item_ids_supports_milvus_query_iterator_next_api():
    manager = CollectionManager.__new__(CollectionManager)
    client = _FakeClient()
    client.query_iterator_result = _FakeQueryIterator(
        [
            [{"item_id": 201}, {"item_id": 202}],
            [{"item_id": 202}, {"item_id": 203}],
        ]
    )
    manager.client = client

    assert manager.iter_collection_item_ids("siglip_collection") == {201, 202, 203}
    assert client.query_iterator_result.closed is True


def test_get_collection_item_counts_groups_rows_per_item_id():
    manager = CollectionManager.__new__(CollectionManager)
    client = _FakeClient()
    client.query_iterator_result = _FakeQueryIterator(
        [
            [{"item_id": 201}, {"item_id": 201}],
            [{"item_id": 202}, {"item_id": 203}, {"item_id": 203}],
        ]
    )
    manager.client = client

    assert manager.get_collection_item_counts("siglip_collection") == {
        201: 2,
        202: 1,
        203: 2,
    }
    assert client.query_iterator_result.closed is True


def test_delete_by_item_id_uses_item_id_filter():
    manager = CollectionManager.__new__(CollectionManager)
    manager.client = _FakeClient()

    deleted = manager.delete_by_item_id("siglip_collection", 1935558010375340032)

    assert deleted == 4
    assert manager.client.deleted == [
        ("siglip_collection", "item_id == 1935558010375340032")
    ]


def test_get_collection_image_records_maps_image_id_to_url():
    manager = CollectionManager.__new__(CollectionManager)
    client = _FakeClient()
    client.query_iterator_result = _FakeQueryIterator(
        [
            [
                {"image_id": 9001, "image_url": "bfr-ai-files/a.jpg"},
                {"image_id": 9001, "image_url": "bfr-ai-files/a.jpg"},
            ],
            [
                {"image_id": 9002, "image_url": "bfr-ai-files/b.jpg"},
            ],
        ]
    )

    def _query_iterator(collection_name, filter, output_fields, batch_size):
        assert collection_name == "siglip_collection"
        assert filter == "item_id == 101"
        assert output_fields == ["image_id", "image_url"]
        return client.query_iterator_result

    client.query_iterator = _query_iterator
    manager.client = client

    assert manager.get_collection_image_records("siglip_collection", 101) == {
        9001: "bfr-ai-files/a.jpg",
        9002: "bfr-ai-files/b.jpg",
    }
    assert client.query_iterator_result.closed is True
