"""Milvus storage for inquiry-description BGE-M3 vectors."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import numpy as np

from csrcqsf.modules.railway_parts.vector_search.config.env_config import get_config
from csrcqsf.modules.railway_parts.vector_search.storage.collection_manager import (
    CollectionManager,
)


class InquirySemanticIndexNotReady(RuntimeError):
    pass


@dataclass(frozen=True)
class InquirySemanticDocument:
    document_key: str
    history_id: int
    inquiry_id: str
    item_id: int
    item_code: str
    description: str
    content_hash: str
    text_vector: np.ndarray
    updated_at: str

    def to_record(self) -> dict:
        record = asdict(self)
        record["text_vector"] = np.asarray(self.text_vector, dtype=np.float32).tolist()
        return record


class InquirySemanticStore:
    def __init__(self, *, collection_manager=None, config=None):
        self.config = config or get_config()
        self.collection_manager = collection_manager or CollectionManager(
            host=self.config.milvus_host,
            port=self.config.milvus_port,
        )
        self.client = self.collection_manager.client
        self.collection_alias = self.config.inquiry_text_collection_alias

    @staticmethod
    def _in_filter(field: str, values: list[str]) -> str:
        encoded = ",".join(json.dumps(value) for value in values)
        return f"{field} in [{encoded}]"

    def get_existing_hashes(
        self,
        document_keys: list[str],
        *,
        collection_name: str | None = None,
    ) -> dict[str, str]:
        if not document_keys:
            return {}
        rows = self.client.query(
            collection_name=collection_name or self.collection_alias,
            filter=self._in_filter("document_key", document_keys),
            output_fields=["document_key", "content_hash"],
        )
        return {
            str(row["document_key"]): str(row["content_hash"])
            for row in rows
        }

    def upsert(
        self,
        documents: list[InquirySemanticDocument],
        *,
        collection_name: str | None = None,
    ) -> int:
        if not documents:
            return 0
        result = self.client.upsert(
            collection_name=collection_name or self.collection_alias,
            data=[document.to_record() for document in documents],
        )
        return int(result.get("upsert_count", len(documents)))

    def delete(
        self,
        document_keys: list[str],
        *,
        collection_name: str | None = None,
    ) -> int:
        if not document_keys:
            return 0
        result = self.client.delete(
            collection_name=collection_name or self.collection_alias,
            filter=self._in_filter("document_key", document_keys),
        )
        return int(result.get("delete_count", 0))

    def search(
        self,
        vector: np.ndarray,
        *,
        limit: int,
        item_ids: list[int] | None = None,
    ) -> list[dict]:
        item_filter = ""
        if item_ids is not None:
            normalized = sorted({int(item_id) for item_id in item_ids})
            if not normalized:
                return []
            item_filter = f"item_id in [{','.join(str(item_id) for item_id in normalized)}]"
        try:
            results = self.client.search(
                collection_name=self.collection_alias,
                data=[np.asarray(vector, dtype=np.float32).tolist()],
                anns_field="text_vector",
                limit=limit,
                filter=item_filter,
                output_fields=[
                    "document_key",
                    "history_id",
                    "inquiry_id",
                    "item_id",
                    "item_code",
                    "description",
                    "content_hash",
                    "updated_at",
                ],
                search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            )
        except Exception as exc:
            message = str(exc).lower()
            if "collection not found" in message or "alias not found" in message:
                raise InquirySemanticIndexNotReady(
                    "询码语义索引尚未就绪，请先执行全量重建"
                ) from exc
            raise
        return list(results[0]) if results else []

    def create_build_collection(self, task_id: str) -> str:
        token = task_id.replace("-", "")[:12]
        collection_name = f"PARTS_INQUIRY_BGE_M3_1024D_BUILD_{token}"
        self.collection_manager.create_inquiry_semantic_collection(
            collection_name,
            self.config.inquiry_text_embedding_dim,
        )
        self.client.load_collection(collection_name=collection_name)
        return collection_name

    def activate_build_collection(self, collection_name: str) -> None:
        # 全量数据和索引就绪后才切换别名，构建失败时线上检索仍使用旧 Collection。
        try:
            self.client.describe_alias(self.collection_alias)
        except Exception:
            self.client.create_alias(
                collection_name=collection_name,
                alias=self.collection_alias,
            )
        else:
            self.client.alter_alias(
                collection_name=collection_name,
                alias=self.collection_alias,
            )

    def drop_build_collection(self, collection_name: str) -> None:
        self.client.drop_collection(collection_name=collection_name)
