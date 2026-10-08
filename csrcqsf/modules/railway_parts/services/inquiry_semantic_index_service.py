"""询码自然语言描述的 BGE-M3 索引与检索业务。"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import unicodedata
from datetime import datetime
from typing import Any, AsyncIterator, Callable

from anyio.to_thread import run_sync

from csrcqsf.infra.external.model_client import get_model_client
from csrcqsf.modules.railway_parts.repositories.inquiry_semantic_repository import (
    InquirySemanticRepository,
)
from csrcqsf.modules.railway_parts.repositories.inquiry_text_index_document_repository import (
    InquiryTextIndexDocumentRepository,
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
        state_repository=None,
        store=None,
        model_client=None,
        config=None,
    ):
        self.repository = repository or InquirySemanticRepository()
        self.state_repository = (
            state_repository or InquiryTextIndexDocumentRepository()
        )
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

    @staticmethod
    def _state_document(row, key: str, content_hash: str, description: str) -> dict:
        return {
            "document_key": key,
            "history_id": int(row.id),
            "inquiry_id": str(row.inquiry_id),
            "item_id": int(row.item_id),
            "item_code": str(row.item_code or ""),
            "description": description,
            "content_hash": content_hash,
        }

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
        state_upserts: list[dict[str, Any]] = []
        state_deletes: list[str] = []

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
                if key:
                    # Milvus 已无该键时仍清理本地镜像，使失败后的重试可以修复状态。
                    state_deletes.append(key)
                processed_items += 1
                continue
            key, content_hash, description = metadata
            if compare_hashes and existing_hashes.get(key) == content_hash:
                state_upserts.append(
                    self._state_document(row, key, content_hash, description)
                )
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
                state_upserts.extend(
                    self._state_document(row, key, content_hash, description)
                    for row, key, content_hash, description in batch
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
            "_state_upserts": state_upserts,
            "_state_deletes": state_deletes,
        }

    async def run_incremental(
        self,
        history_ids: list[int],
        progress_callback: ProgressCallback | None = None,
        *,
        task_id: str = "incremental",
    ) -> dict[str, Any]:
        rows = await self.repository.list_by_ids(history_ids)
        result = await self._index_rows(
            rows,
            collection_name=None,
            compare_hashes=True,
            progress_callback=progress_callback,
        )
        # 增量写入成功后同步本地镜像；重试时未变化文档也会补齐历史缺失状态。
        await self.state_repository.upsert(result.pop("_state_upserts"), task_id)
        await self.state_repository.delete(result.pop("_state_deletes"))
        return result

    async def run_full(
        self,
        task_id: str,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        # 全量任务在临时 Collection 构建完成后原子切换别名，失败不影响在线旧索引。
        collection_name = await run_sync(
            lambda: self.store.create_build_collection(task_id)
        )
        activated = False
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
                activated = True
                # 只有别名已经指向新 Collection，镜像才可以整体替换为本次文档。
                await self.state_repository.replace_all(
                    result["_state_upserts"],
                    task_id,
                )
            result.pop("_state_upserts", None)
            result.pop("_state_deletes", None)
            return result
        except asyncio.CancelledError:
            if not activated:
                await run_sync(lambda: self.store.drop_build_collection(collection_name))
            raise
        except Exception:
            # 别名切换后新库已承担在线检索，本地镜像失败不能反向删除活动 Collection。
            if not activated:
                await run_sync(lambda: self.store.drop_build_collection(collection_name))
            raise

    async def _filter_search_hits(
        self,
        hits: list[dict],
        *,
        exclude_inquiry_id: str | None,
        before_inquiry_time: datetime | None,
    ) -> list[dict]:
        if exclude_inquiry_id and before_inquiry_time:
            # Agent 回放在按配件去重前剔除当前及未来询码，保留同一配件更早的合法命中。
            eligible_inquiry_ids = await self.repository.list_eligible_inquiry_ids(
                [
                    str(hit.get("entity", {}).get("inquiry_id") or "")
                    for hit in hits
                    if hit.get("entity", {}).get("inquiry_id")
                ],
                exclude_inquiry_id=exclude_inquiry_id,
                before_inquiry_time=before_inquiry_time,
            )
            hits = [
                hit
                for hit in hits
                if str(hit.get("entity", {}).get("inquiry_id") or "")
                in eligible_inquiry_ids
            ]

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
        )

    async def search_candidate_batches(
        self,
        query_text: str,
        *,
        candidate_limits: tuple[int, ...] = (200, 500, 1000),
        item_ids: list[int] | None = None,
        exclude_inquiry_id: str | None = None,
        before_inquiry_time: datetime | None = None,
    ) -> AsyncIterator[list[dict]]:
        """一次生成查询向量，按深度递增返回去重后的配件候选。"""
        normalized = normalize_inquiry_description(query_text)
        if not normalized:
            raise ValueError("查询文本不能为空")
        vectors = await self.model_client.text_embeddings([normalized])
        max_candidates = self.config.inquiry_text_search_max_candidates
        limits = tuple(
            dict.fromkeys(
                min(max_candidates, int(limit))
                for limit in candidate_limits
                if int(limit) > 0
            )
        )
        for limit in limits:
            hits = await run_sync(
                lambda current_limit=limit: self.store.search(
                    vectors[0],
                    limit=current_limit,
                    item_ids=item_ids,
                )
            )
            yield await self._filter_search_hits(
                hits,
                exclude_inquiry_id=exclude_inquiry_id,
                before_inquiry_time=before_inquiry_time,
            )
            if len(hits) < limit:
                return

    async def search(
        self,
        query_text: str,
        *,
        top_k: int,
        item_ids: list[int] | None = None,
        exclude_inquiry_id: str | None = None,
        before_inquiry_time: datetime | None = None,
    ) -> list[dict]:
        """检索历史询码描述样本，并按配件去重返回最高分语义候选。"""
        candidate_limit = min(
            self.config.inquiry_text_search_max_candidates,
            max(
                self.config.inquiry_text_search_min_candidates,
                int(top_k) * self.config.inquiry_text_search_oversample,
            ),
        )
        batches = self.search_candidate_batches(
            query_text,
            candidate_limits=(candidate_limit,),
            item_ids=item_ids,
            exclude_inquiry_id=exclude_inquiry_id,
            before_inquiry_time=before_inquiry_time,
        )
        async for hits in batches:
            return hits[:top_k]
        return []


_service: InquirySemanticIndexService | None = None


def get_inquiry_semantic_index_service() -> InquirySemanticIndexService:
    global _service
    if _service is None:
        _service = InquirySemanticIndexService()
    return _service
