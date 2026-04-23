from csrcqsf.biz.railwayparts.vector_db.storage.collection_manager import CollectionManager


class _FakeIterator:
    def __init__(self, batches):
        self._batches = list(batches)

    def __iter__(self):
        return iter(self._batches)


class _FakeClient:
    def __init__(self):
        self.deleted = []

    def has_collection(self, name):
        return name != "missing_collection"

    def get_collection_stats(self, collection_name):
        return {"row_count": "7"}

    def query_iterator(self, collection_name, filter, output_fields, batch_size):
        assert output_fields == ["item_id"]
        return _FakeIterator(
            [
                [{"item_id": 101}, {"item_id": 102}],
                [{"item_id": 102}, {"item_id": 103}],
            ]
        )

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


def test_delete_by_item_id_uses_item_id_filter():
    manager = CollectionManager.__new__(CollectionManager)
    manager.client = _FakeClient()

    deleted = manager.delete_by_item_id("siglip_collection", 1935558010375340032)

    assert deleted == 4
    assert manager.client.deleted == [
        ("siglip_collection", "item_id == 1935558010375340032")
    ]
