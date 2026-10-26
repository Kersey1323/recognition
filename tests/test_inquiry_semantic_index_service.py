import asyncio
from datetime import datetime
from types import SimpleNamespace

import numpy as np


class FakeRepository:
    def __init__(self, rows):
        self.rows = rows

    async def list_by_ids(self, history_ids):
        wanted = set(history_ids)
        return [row for row in self.rows if row.id in wanted]

    async def list_valid(self):
        return [
            row
            for row in self.rows
            if row.item_id is not None and str(row.inquiry_item_name or "").strip()
        ]

    async def list_eligible_inquiry_ids(
        self,
        inquiry_ids,
        *,
        exclude_inquiry_id,
        before_inquiry_time,
    ):
        wanted = set(inquiry_ids)
        return {
            row.inquiry_id
            for row in self.rows
            if row.inquiry_id in wanted
            and row.inquiry_id != exclude_inquiry_id
            and row.inquiry_time < before_inquiry_time
        }


class FakeModelClient:
    def __init__(self):
        self.calls = []

    async def text_embeddings(self, texts):
        self.calls.append(list(texts))
        return np.asarray(
            [[float(index + 1)] * 1024 for index, _text in enumerate(texts)],
            dtype=np.float32,
        )


class FakeStore:
    def __init__(self):
        self.hashes = {}
        self.upserts = []
        self.deletes = []
        self.search_hits = []
        self.search_hits_by_limit = {}
        self.search_calls = []
        self.activated = []
        self.dropped = []

    def get_existing_hashes(self, keys, collection_name=None):
        return {key: self.hashes[key] for key in keys if key in self.hashes}

    def upsert(self, documents, collection_name=None):
        self.upserts.extend((collection_name, document) for document in documents)
        return len(documents)

    def delete(self, keys, collection_name=None):
        self.deletes.append((collection_name, list(keys)))
        return len(keys)

    def search(self, vector, *, limit, item_ids=None):
        self.search_limit = limit
        self.search_item_ids = item_ids
        self.search_calls.append((limit, item_ids))
        return self.search_hits_by_limit.get(limit, self.search_hits)

    def create_build_collection(self, task_id):
        return f"build-{task_id}"

    def activate_build_collection(self, collection_name):
        self.activated.append(collection_name)

    def drop_build_collection(self, collection_name):
        self.dropped.append(collection_name)


class FakeStateRepository:
    def __init__(self):
        self.replaced = []
        self.upserted = []
        self.deleted = []

    async def replace_all(self, documents, task_id):
        self.replaced.append((task_id, list(documents)))

    async def upsert(self, documents, task_id):
        self.upserted.append((task_id, list(documents)))

    async def delete(self, document_keys):
        self.deleted.append(list(document_keys))


def make_row(
    row_id,
    inquiry_id,
    description,
    *,
    item_id=10,
    item_code="40001",
    return_item_code=None,
    source="sgo",
    inquiry_time=None,
):
    return SimpleNamespace(
        id=row_id,
        inquiry_id=inquiry_id,
        inquiry_item_name=description,
        item_id=item_id,
        item_code=item_code,
        return_item_code=return_item_code or item_code,
        source=source,
        inquiry_time=inquiry_time or datetime(2026, 1, 1),
    )


def make_config(**overrides):
    values = {
        "inquiry_text_index_batch_size": 128,
        "inquiry_text_search_oversample": 5,
        "inquiry_text_search_min_candidates": 30,
        "inquiry_text_search_max_candidates": 200,
        "inquiry_text_min_score": 0.55,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_catalog_names_survive_replay_filter_without_admitting_unmarked_rows():
    from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
        InquirySemanticIndexService,
    )

    service = InquirySemanticIndexService(
        repository=FakeRepository([]),
        state_repository=FakeStateRepository(),
        store=FakeStore(),
        model_client=FakeModelClient(),
        config=make_config(),
    )
    hits = [
        {"distance": 0.9, "entity": {"item_id": 10, "document_key": "catalog:40001", "history_id": 0, "inquiry_id": ""}},
        {"distance": 0.95, "entity": {"item_id": 20, "inquiry_id": ""}},
        {"distance": 0.99, "entity": {"item_id": 30, "document_key": "catalog:40003", "history_id": 5, "inquiry_id": "current"}},
    ]
    filtered = asyncio.run(service._filter_search_hits(
        hits, exclude_inquiry_id="current", before_inquiry_time=datetime(2026, 3, 5),
    ))
    assert [hit["entity"]["item_id"] for hit in filtered] == [10]


def test_description_normalization_and_hashes_are_deterministic():
    from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
        build_content_hash,
        build_document_key,
        normalize_inquiry_description,
    )

    assert normalize_inquiry_description(" 监控室\u3000对面\n窗帘 ") == "监控室 对面 窗帘"
    assert build_document_key("sgo", "1001", "40001") == build_document_key(
        "sgo", "1001", "40001"
    )
    assert build_document_key("sgo", "1001", "40001") != build_document_key(
        "sgo", "1001", "40002"
    )
    assert build_content_hash(10, "40001", "描述") != build_content_hash(11, "40001", "描述")


def test_incremental_index_skips_unchanged_updates_changed_and_deletes_invalid():
    from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
        InquirySemanticIndexService,
        build_content_hash,
        build_document_key,
    )

    unchanged = make_row(1, "1001", "监控室对面窗帘")
    changed = make_row(2, "1002", "底板螺栓", item_id=20, item_code="40002")
    invalid = make_row(3, "1003", " ", item_id=None, item_code="40003")
    store = FakeStore()
    store.hashes[build_document_key("sgo", "1001", "40001")] = build_content_hash(
        10, "40001", "监控室对面窗帘"
    )
    store.hashes[build_document_key("sgo", "1003", "40003")] = "old"
    model = FakeModelClient()
    state = FakeStateRepository()
    service = InquirySemanticIndexService(
        repository=FakeRepository([unchanged, changed, invalid]),
        state_repository=state,
        store=store,
        model_client=model,
        config=make_config(),
    )

    result = asyncio.run(service.run_incremental([1, 2, 3]))

    assert result["total_items"] == 3
    assert result["processed_items"] == 3
    assert result["indexed_count"] == 1
    assert result["skipped_count"] == 1
    assert result["deleted_count"] == 1
    assert result["fail_count"] == 0
    assert model.calls == [["底板螺栓"]]
    assert store.upserts[0][1].inquiry_id == "1002"
    assert store.deletes == [(None, [build_document_key("sgo", "1003", "40003")])]
    assert {row["history_id"] for row in state.upserted[0][1]} == {1, 2}
    assert state.deleted == [[build_document_key("sgo", "1003", "40003")]]


def test_full_build_switches_alias_only_after_success():
    from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
        InquirySemanticIndexService,
    )

    store = FakeStore()
    state = FakeStateRepository()
    service = InquirySemanticIndexService(
        repository=FakeRepository([make_row(1, "1001", "监控室对面窗帘")]),
        state_repository=state,
        store=store,
        model_client=FakeModelClient(),
        config=make_config(),
    )

    result = asyncio.run(service.run_full("task-1"))

    assert result["indexed_count"] == 1
    assert store.activated == ["build-task-1"]
    assert store.dropped == []
    assert store.upserts[0][0] == "build-task-1"
    assert state.replaced[0][0] == "task-1"
    assert state.replaced[0][1][0]["description"] == "监控室对面窗帘"


def test_full_build_does_not_drop_active_collection_when_state_persistence_fails():
    from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
        InquirySemanticIndexService,
    )

    class FailingStateRepository(FakeStateRepository):
        async def replace_all(self, documents, task_id):
            raise RuntimeError("state persistence failed")

    store = FakeStore()
    service = InquirySemanticIndexService(
        repository=FakeRepository([make_row(1, "1001", "监控室对面窗帘")]),
        state_repository=FailingStateRepository(),
        store=store,
        model_client=FakeModelClient(),
        config=make_config(),
    )

    try:
        asyncio.run(service.run_full("task-state-failure"))
    except RuntimeError as exc:
        assert str(exc) == "state persistence failed"
    else:
        raise AssertionError("state persistence failure must fail the rebuild task")

    assert store.activated == ["build-task-state-failure"]
    assert store.dropped == []


def test_full_build_indexes_each_distinct_return_for_the_same_inquiry():
    from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
        InquirySemanticIndexService,
    )

    store = FakeStore()
    model = FakeModelClient()
    service = InquirySemanticIndexService(
        repository=FakeRepository(
            [
                make_row(3, "1001", "同一询码描述", item_code="40001"),
                make_row(1, "1002", "其他描述"),
                make_row(5, "1001", "同一询码描述", item_id=20, item_code="40002"),
            ]
        ),
        state_repository=FakeStateRepository(),
        store=store,
        model_client=model,
        config=make_config(inquiry_text_index_batch_size=1),
    )

    result = asyncio.run(service.run_full("task-deduplicate"))

    assert result["total_items"] == 3
    assert result["processed_items"] == 3
    assert result["indexed_count"] == 3
    assert result["skipped_count"] == 0
    assert result["fail_count"] == 0
    documents = [document for _collection, document in store.upserts]
    assert len({document.document_key for document in documents}) == 3
    assert {
        document.item_code
        for document in documents
        if document.inquiry_id == "1001"
    } == {"40001", "40002"}
    assert model.calls == [["同一询码描述"], ["其他描述"], ["同一询码描述"]]


def test_incremental_latest_invalid_history_deletes_existing_document():
    from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
        InquirySemanticIndexService,
        build_document_key,
    )

    old_valid = make_row(3, "1001", "旧描述")
    latest_invalid = make_row(5, "1001", " ", item_id=None)
    store = FakeStore()
    document_key = build_document_key("sgo", "1001", "40001")
    store.hashes[document_key] = "old-content-hash"
    model = FakeModelClient()
    service = InquirySemanticIndexService(
        repository=FakeRepository([old_valid, latest_invalid]),
        state_repository=FakeStateRepository(),
        store=store,
        model_client=model,
        config=make_config(),
    )

    result = asyncio.run(service.run_incremental([3, 5]))

    assert result["total_items"] == 2
    assert result["processed_items"] == 2
    assert result["indexed_count"] == 0
    assert result["skipped_count"] == 1
    assert result["deleted_count"] == 1
    assert result["fail_count"] == 0
    assert model.calls == []
    assert store.deletes == [(None, [document_key])]


def test_search_applies_threshold_and_aggregates_by_best_item_hit():
    from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
        InquirySemanticIndexService,
    )

    store = FakeStore()
    store.search_hits = [
        {"distance": 0.91, "entity": {"item_id": 10, "inquiry_id": "a", "description": "描述A"}},
        {"distance": 0.82, "entity": {"item_id": 10, "inquiry_id": "b", "description": "描述B"}},
        {"distance": 0.73, "entity": {"item_id": 20, "inquiry_id": "c", "description": "描述C"}},
        {"distance": 0.50, "entity": {"item_id": 30, "inquiry_id": "d", "description": "描述D"}},
    ]
    service = InquirySemanticIndexService(
        repository=FakeRepository([]),
        state_repository=FakeStateRepository(),
        store=store,
        model_client=FakeModelClient(),
        config=make_config(),
    )

    result = asyncio.run(service.search("窗帘在哪里", top_k=2, item_ids=[10, 20, 30]))

    assert [hit["entity"]["item_id"] for hit in result] == [10, 20]
    assert result[0]["entity"]["inquiry_id"] == "a"
    assert store.search_limit == 30
    assert store.search_item_ids == [10, 20, 30]


def test_search_filters_current_and_future_hits_before_item_deduplication():
    from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
        InquirySemanticIndexService,
    )

    cutoff = datetime(2026, 3, 5, 10, 30, 26)
    store = FakeStore()
    store.search_hits = [
        {"distance": 0.99, "entity": {"history_id": 0, "item_id": 10, "inquiry_id": "current", "description": "当前"}},
        {"distance": 0.95, "entity": {"history_id": 0, "item_id": 10, "inquiry_id": "future", "description": "未来"}},
        {"distance": 0.82, "entity": {"history_id": 0, "item_id": 10, "inquiry_id": "older", "description": "历史"}},
    ]
    service = InquirySemanticIndexService(
        repository=FakeRepository(
            [
                make_row(1, "current", "当前", inquiry_time=cutoff),
                make_row(2, "future", "未来", inquiry_time=datetime(2026, 3, 6)),
                make_row(3, "older", "历史", inquiry_time=datetime(2026, 3, 4)),
            ]
        ),
        state_repository=FakeStateRepository(),
        store=store,
        model_client=FakeModelClient(),
        config=make_config(),
    )

    results = asyncio.run(
        service.search(
            "门控器",
            top_k=20,
            exclude_inquiry_id="current",
            before_inquiry_time=cutoff,
        )
    )

    assert [hit["entity"]["inquiry_id"] for hit in results] == ["older"]


def test_search_candidate_batches_expand_depth_without_reembedding_query():
    from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
        InquirySemanticIndexService,
    )

    store = FakeStore()
    store.search_hits_by_limit = {
        200: [
            {"distance": 0.91, "entity": {"item_id": 10, "inquiry_id": "a"}},
        ]
        * 200,
        500: [
            {"distance": 0.91, "entity": {"item_id": 10, "inquiry_id": "a"}},
            {"distance": 0.81, "entity": {"item_id": 20, "inquiry_id": "b"}},
        ]
        * 250,
        1000: [
            {"distance": 0.91, "entity": {"item_id": 10, "inquiry_id": "a"}},
            {"distance": 0.81, "entity": {"item_id": 20, "inquiry_id": "b"}},
            {"distance": 0.71, "entity": {"item_id": 30, "inquiry_id": "c"}},
        ]
        * 334,
    }
    model = FakeModelClient()
    service = InquirySemanticIndexService(
        repository=FakeRepository([]),
        state_repository=FakeStateRepository(),
        store=store,
        model_client=model,
        config=make_config(inquiry_text_search_max_candidates=1000),
    )

    async def collect_batches():
        return [
            batch
            async for batch in service.search_candidate_batches(
                "  Door\u3000hinge ",
                candidate_limits=(200, 500, 1000),
            )
        ]

    batches = asyncio.run(collect_batches())

    assert [[hit["entity"]["item_id"] for hit in batch] for batch in batches] == [
        [10],
        [10, 20],
        [10, 20, 30],
    ]
    assert store.search_calls == [(200, None), (500, None), (1000, None)]
    assert model.calls == [["Door hinge"]]


def test_incremental_progress_only_reports_failures_from_current_batch():
    from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
        InquirySemanticIndexService,
    )

    class FirstRowFailsModel(FakeModelClient):
        async def text_embeddings(self, texts):
            if texts == ["失败描述"]:
                raise RuntimeError("embedding failed")
            return await super().text_embeddings(texts)

    progress = []
    service = InquirySemanticIndexService(
        repository=FakeRepository(
            [
                make_row(1, "1001", "失败描述"),
                make_row(2, "1002", "成功描述"),
            ]
        ),
        state_repository=FakeStateRepository(),
        store=FakeStore(),
        model_client=FirstRowFailsModel(),
        config=make_config(inquiry_text_index_batch_size=1),
    )

    result = asyncio.run(
        service.run_incremental([1, 2], progress_callback=progress.append)
    )

    assert result["fail_count"] == 1
    assert len(progress[0]["new_failure_details"]) == 1
    assert progress[1]["new_failure_details"] == []
