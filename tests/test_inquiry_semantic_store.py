from types import SimpleNamespace

import numpy as np


class FakeSchema:
    def __init__(self):
        self.fields = []

    def add_field(self, **kwargs):
        self.fields.append(kwargs)


class FakeIndexParams:
    def __init__(self):
        self.indexes = []

    def add_index(self, **kwargs):
        self.indexes.append(kwargs)


class FakeClient:
    def __init__(self):
        self.calls = []
        self.alias_target = None
        self.query_rows = []
        self.search_rows = []

    def prepare_index_params(self):
        return FakeIndexParams()

    def create_collection(self, **kwargs):
        self.calls.append(("create_collection", kwargs))

    def load_collection(self, **kwargs):
        self.calls.append(("load_collection", kwargs))

    def upsert(self, **kwargs):
        self.calls.append(("upsert", kwargs))
        return {"upsert_count": len(kwargs["data"])}

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return {"delete_count": 1}

    def query(self, **kwargs):
        self.calls.append(("query", kwargs))
        return self.query_rows

    def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        return [self.search_rows]

    def describe_alias(self, alias):
        if self.alias_target is None:
            raise RuntimeError("alias not found")
        return {"alias": alias, "collection": self.alias_target}

    def create_alias(self, collection_name, alias):
        self.calls.append(("create_alias", {"collection_name": collection_name, "alias": alias}))
        self.alias_target = collection_name

    def alter_alias(self, collection_name, alias):
        self.calls.append(("alter_alias", {"collection_name": collection_name, "alias": alias}))
        self.alias_target = collection_name

    def drop_collection(self, collection_name):
        self.calls.append(("drop_collection", {"collection_name": collection_name}))


def test_collection_manager_creates_inquiry_semantic_schema(monkeypatch):
    from csrcqsf.modules.railway_parts.vector_search.storage import collection_manager as module

    schema = FakeSchema()
    monkeypatch.setattr(module.MilvusClient, "create_schema", lambda **_kwargs: schema)
    manager = object.__new__(module.CollectionManager)
    manager.client = FakeClient()
    monkeypatch.setattr(manager, "collection_exists", lambda _name: False)

    assert manager.create_inquiry_semantic_collection("inquiry-build", 1024) is True

    fields = {field["field_name"]: field for field in schema.fields}
    assert fields["document_key"]["is_primary"] is True
    assert fields["document_key"].get("auto_id") is not True
    assert fields["text_vector"]["dim"] == 1024
    assert set(fields) == {
        "document_key",
        "history_id",
        "inquiry_id",
        "item_id",
        "item_code",
        "description",
        "content_hash",
        "text_vector",
        "updated_at",
    }
    create_call = manager.client.calls[0][1]
    assert create_call["index_params"].indexes == [
        {
            "field_name": "text_vector",
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "params": {"M": 16, "efConstruction": 200},
        }
    ]


def test_store_upserts_queries_hashes_deletes_and_searches():
    from csrcqsf.modules.railway_parts.vector_search.storage.inquiry_semantic_store import (
        InquirySemanticDocument,
        InquirySemanticStore,
    )

    client = FakeClient()
    client.query_rows = [{"document_key": "abc", "content_hash": "hash-1"}]
    client.search_rows = [
        {"distance": 0.91, "entity": {"document_key": "abc", "item_id": 10}}
    ]
    manager = SimpleNamespace(client=client)
    config = SimpleNamespace(
        inquiry_text_collection_alias="inquiry-current",
        inquiry_text_embedding_dim=1024,
    )
    store = InquirySemanticStore(collection_manager=manager, config=config)
    document = InquirySemanticDocument(
        document_key="abc",
        history_id=1,
        inquiry_id="inquiry-1",
        item_id=10,
        item_code="40001",
        description="监控室对面窗帘",
        content_hash="hash-1",
        text_vector=np.ones(1024, dtype=np.float32),
        updated_at="2026-08-28T10:00:00",
    )

    assert store.get_existing_hashes(["abc"]) == {"abc": "hash-1"}
    assert store.upsert([document]) == 1
    assert store.delete(["abc"]) == 1
    assert store.search(np.ones(1024, dtype=np.float32), limit=30) == client.search_rows

    upsert_call = next(call for call in client.calls if call[0] == "upsert")
    assert upsert_call[1]["collection_name"] == "inquiry-current"
    assert upsert_call[1]["data"][0]["document_key"] == "abc"
    search_call = next(call for call in client.calls if call[0] == "search")
    assert search_call[1]["anns_field"] == "text_vector"
    assert search_call[1]["search_params"] == {
        "metric_type": "COSINE",
        "params": {"ef": 64},
    }


def test_store_creates_then_switches_stable_alias():
    from csrcqsf.modules.railway_parts.vector_search.storage.inquiry_semantic_store import (
        InquirySemanticStore,
    )

    client = FakeClient()
    manager = SimpleNamespace(
        client=client,
        create_inquiry_semantic_collection=lambda name, dim: True,
    )
    config = SimpleNamespace(
        inquiry_text_collection_alias="inquiry-current",
        inquiry_text_embedding_dim=1024,
    )
    store = InquirySemanticStore(collection_manager=manager, config=config)

    first = store.create_build_collection("12345678-abcd")
    store.activate_build_collection(first)
    second = store.create_build_collection("abcdef12-3456")
    store.activate_build_collection(second)

    assert first == "PARTS_INQUIRY_BGE_M3_1024D_BUILD_12345678abcd"
    assert second == "PARTS_INQUIRY_BGE_M3_1024D_BUILD_abcdef123456"
    assert [name for name, _ in client.calls if name in {"create_alias", "alter_alias"}] == [
        "create_alias",
        "alter_alias",
    ]


def test_store_reports_missing_alias_as_index_not_ready():
    from csrcqsf.modules.railway_parts.vector_search.storage.inquiry_semantic_store import (
        InquirySemanticIndexNotReady,
        InquirySemanticStore,
    )

    class MissingCollectionClient(FakeClient):
        def search(self, **kwargs):
            raise RuntimeError("collection not found[collection=inquiry-current]")

    store = InquirySemanticStore(
        collection_manager=SimpleNamespace(client=MissingCollectionClient()),
        config=SimpleNamespace(
            inquiry_text_collection_alias="inquiry-current",
            inquiry_text_embedding_dim=1024,
        ),
    )

    try:
        store.search(np.ones(1024, dtype=np.float32), limit=30)
    except InquirySemanticIndexNotReady as exc:
        assert str(exc) == "询码语义索引尚未就绪，请先执行全量重建"
    else:
        raise AssertionError("missing semantic alias should return a business error")
