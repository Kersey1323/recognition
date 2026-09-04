"""询码自然语言描述的 BGE-M3 索引与检索业务。"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import unicodedata
from datetime import datetime
from typing import Any, Callable

from anyio.to_thread import run_sync

from csrcqsf.infra.external.model_client import get_model_client
from csrcqsf.modules.railway_parts.repositories.inquiry_semantic_repository import (
    InquirySemanticRepository,
)
from csrcqsf.modules.railway_parts.vector_search.config.env_config import get_config
from csrcqsf.modules.railway_parts.vector_search.storage.inquiry_semantic_store import (
    InquirySemanticDocument,
    InquirySemanticStore,
)


ProgressCallback = Callable[[dict[str, Any]], Any]


def normalize_inquiry_description(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", " ", normalized).strip()


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_document_key(source: str, inquiry_id: str, return_item_code: str) -> str:
    return _sha256(
        f"{source.strip()}|{inquiry_id.strip()}|{return_item_code.strip()}"
    )


def build_content_hash(item_id: int, item_code: str, description: str) -> str:
    payload = json.dumps(
        [int(item_id), str(item_code or "").strip(), description],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return _sha256(payload)


async def _notify(callback: ProgressCallback | None, payload: dict[str, Any]) -> None:
    if callback is None:
        return
    result = callback(payload)
    if inspect.isawaitable(result):
        await result


class InquirySemanticIndexService:
    """将有效询码描述建成独立 BGE-M3 文本索引，并提供按配件过滤的语义检索。"""
    def __init__(
        self,
        *,
        repository=None,
        store=None,
        model_client=None,
        config=None,
    ):
        self.repository = repository or InquirySemanticRepository()
        self.store = store or InquirySemanticStore()
        self.model_client = model_client or get_model_client()
        self.config = config or get_config()

    @staticmethod
    def _source_values(row) -> tuple[str, str, str, str]:
        source = str(getattr(row, "source", "sgo") or "sgo").strip()
        inquiry_id = str(getattr(row, "inquiry_id", "") or "").strip()
        return_item_code = str(
            getattr(row, "return_item_code", None)
            or getattr(row, "item_code", "")
            or ""
        ).strip()
        description = normalize_inquiry_description(
            getattr(row, "inquiry_item_name", None)
        )
        return source, inquiry_id, return_item_code, description

    @classmethod
    def _document_metadata(cls, row) -> tuple[str, str, str] | None:
        # 只索引名称描述并关联唯一返回配件；空描述或未匹配主数据的记录不进入向量库。
        source, inquiry_id, return_item_code, description = cls._source_values(row)
        item_id = getattr(row, "item_id", None)
        if not inquiry_id or not return_item_code or item_id is None or not description:
            return None
        document_key = build_document_key(source, inquiry_id, return_item_code)
        content_hash = build_content_hash(
            int(item_id),
            str(getattr(row, "item_code", "") or ""),
            description,
        )
        return document_key, content_hash, description

    async def _embed_with_retry(self, texts: list[str]) -> Any:
        # 模型服务短暂失败仅重试当前文本批次，不重跑已经写入的前序样本。
        last_error = None
        for attempt in range(3):
            try:
                return await self.model_client.text_embeddings(texts)
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.2 * (attempt + 1))
        raise last_error  # type: ignore[misc]

    async def _index_rows(
        self,
        rows: list,
        *,
        collection_name: str | None,
        compare_hashes: bool,
        progress_callback: ProgressCallback | None,
    ) -> dict[str, Any]:
        total_items = len(rows)
        processed_items = 0
        indexed_count = 0
        skipped_count = 0
        deleted_count = 0
        failures: list[dict[str, Any]] = []

        latest_by_key: dict[str, tuple[int, Any, tuple[str, str, str] | None]] = {}
        rows_without_key = []
        for position, row in enumerate(rows):
            source, inquiry_id, return_item_code, _description = self._source_values(row)
            key = (
                build_document_key(source, inquiry_id, return_item_code)
                if inquiry_id and return_item_code
                else None
            )
            entry = (position, row, self._document_metadata(row))
            if key is None:
                rows_without_key.append(entry)
                continue

            # 同一询码可以返回多个配件；仅合并返回编码也相同的重复历史版本。
            current = latest_by_key.get(key)
            if current is None or int(row.id) > int(current[1].id):
                latest_by_key[key] = entry

        selected_rows = rows_without_key + list(latest_by_key.values())
        selected_rows.sort(key=lambda entry: entry[0])
        superseded_count = total_items - len(selected_rows)
        processed_items += superseded_count
        skipped_count += superseded_count

        keyed_rows = []
        document_keys = []
        for _position, row, metadata in selected_rows:
            source, inquiry_id, return_item_code, _description = self._source_values(row)
            key = (
                build_document_key(source, inquiry_id, return_item_code)
                if inquiry_id and return_item_code
                else None
            )
            keyed_rows.append((row, key, metadata))
            if key:
                document_keys.append(key)

        existing_hashes = {}
        if compare_hashes and document_keys:
            existing_hashes = await run_sync(
                lambda: self.store.get_existing_hashes(
                    document_keys,
                    collection_name=collection_name,
                )
            )

        changed_rows = []
        for row, key, metadata in keyed_rows:
            if metadata is None:
                # 已入库样本变为无效时删除旧向量，避免过期描述继续被召回。
                if key and key in existing_hashes:
                    deleted_count += await run_sync(
                        lambda current_key=key: self.store.delete(
                            [current_key],
                            collection_name=collection_name,
                        )
                    )
                else:
                    skipped_count += 1
                processed_items += 1
                continue
            key, content_hash, description = metadata
            if compare_hashes and existing_hashes.get(key) == content_hash:
                skipped_count += 1
                processed_items += 1
                continue
            changed_rows.append((row, key, content_hash, description))

        batch_size = self.config.inquiry_text_index_batch_size
        for offset in range(0, len(changed_rows), batch_size):
            batch = changed_rows[offset : offset + batch_size]
            batch_failures: list[dict[str, Any]] = []
            try:
                vectors = await self._embed_with_retry([entry[3] for entry in batch])
                now = datetime.now().isoformat()
                documents = [
                    InquirySemanticDocument(
                        document_key=key,
                        history_id=int(row.id),
                        inquiry_id=str(row.inquiry_id),
                        item_id=int(row.item_id),
                        item_code=str(row.item_code or ""),
                        description=description,
                        content_hash=content_hash,
                        text_vector=vectors[index],
                        updated_at=now,
                    )
                    for index, (row, key, content_hash, description) in enumerate(batch)
                ]
                indexed_count += await run_sync(
                    lambda: self.store.upsert(
                        documents,
                        collection_name=collection_name,
                    )
                )
            except Exception as exc:
                for row, _key, _content_hash, _description in batch:
                    batch_failures.append(
                        {
                            "history_id": int(row.id),
                            "inquiry_id": str(row.inquiry_id),
                            "item_id": int(row.item_id) if row.item_id is not None else None,
                            "stage": "embedding_or_upsert",
                            "error_type": type(exc).__name__,
                            "error_message": str(exc) or repr(exc),
                        }
                    )
                failures.extend(batch_failures)
            processed_items += len(batch)
            await _notify(
                progress_callback,
                {
                    "progress": int(processed_items * 100 / total_items) if total_items else 100,
                    "total_items": total_items,
                    "processed_items": processed_items,
                    "indexed_count": indexed_count,
                    "skipped_count": skipped_count,
                    "deleted_count": deleted_count,
                    "fail_count": len(failures),
                    "current_inquiry_id": str(batch[-1][0].inquiry_id),
                    "new_failure_details": batch_failures,
                },
            )
            await asyncio.sleep(0)

        await _notify(
            progress_callback,
            {
                "progress": 100,
                "total_items": total_items,
                "processed_items": processed_items,
                "indexed_count": indexed_count,
                "skipped_count": skipped_count,
                "deleted_count": deleted_count,
                "fail_count": len(failures),
                "current_inquiry_id": None,
            },
        )
        return {
            "total_items": total_items,
            "processed_items": processed_items,
            "indexed_count": indexed_count,
            "skipped_count": skipped_count,
            "deleted_count": deleted_count,
            "fail_count": len(failures),
            "failure_details": failures,
            "failures_persisted_incrementally": bool(progress_callback),
        }

    async def run_incremental(
        self,
        history_ids: list[int],
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        rows = await self.repository.list_by_ids(history_ids)
        return await self._index_rows(
            rows,
            collection_name=None,
            compare_hashes=True,
            progress_callback=progress_callback,
        )

    async def run_full(
        self,
        task_id: str,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        # 全量任务在临时 Collection 构建完成后原子切换别名，失败不影响在线旧索引。
        collection_name = await run_sync(
            lambda: self.store.create_build_collection(task_id)
        )
        try:
            rows = await self.repository.list_valid()
            result = await self._index_rows(
                rows,
                collection_name=collection_name,
                compare_hashes=False,
                progress_callback=progress_callback,
            )
            if result["fail_count"]:
                await run_sync(lambda: self.store.drop_build_collection(collection_name))
            else:
                await run_sync(
                    lambda: self.store.activate_build_collection(collection_name)
                )
            return result
        except asyncio.CancelledError:
            await run_sync(lambda: self.store.drop_build_collection(collection_name))
            raise
        except Exception:
            await run_sync(lambda: self.store.drop_build_collection(collection_name))
            raise

    async def search(
        self,
        query_text: str,
        *,
        top_k: int,
        item_ids: list[int] | None = None,
    ) -> list[dict]:
        """检索历史询码描述样本，并按配件去重返回最高分语义候选。"""
        normalized = normalize_inquiry_description(query_text)
        if not normalized:
            raise ValueError("查询文本不能为空")
        vectors = await self.model_client.text_embeddings([normalized])
        candidate_limit = min(
            self.config.inquiry_text_search_max_candidates,
            max(
                self.config.inquiry_text_search_min_candidates,
                int(top_k) * self.config.inquiry_text_search_oversample,
            ),
        )
        hits = await run_sync(
            lambda: self.store.search(
                vectors[0],
                limit=candidate_limit,
                item_ids=item_ids,
            )
        )
        best_by_item: dict[int, dict] = {}
        for hit in hits:
            score = float(hit.get("distance", 0) or 0)
            entity = hit.get("entity", {})
            item_id = entity.get("item_id")
            if item_id is None or score < self.config.inquiry_text_min_score:
                continue
            item_id = int(item_id)
            previous = best_by_item.get(item_id)
            if previous is None or score > float(previous.get("distance", 0) or 0):
                best_by_item[item_id] = hit
        return sorted(
            best_by_item.values(),
            key=lambda hit: float(hit.get("distance", 0) or 0),
            reverse=True,
        )[:top_k]


_service: InquirySemanticIndexService | None = None


def get_inquiry_semantic_index_service() -> InquirySemanticIndexService:
    global _service
    if _service is None:
        _service = InquirySemanticIndexService()
    return _service
