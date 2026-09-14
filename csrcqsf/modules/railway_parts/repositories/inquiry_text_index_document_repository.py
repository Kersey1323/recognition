"""询码语义索引文档镜像的数据访问。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.models.orm.inquiry_text_index_document import (
    InquiryTextIndexDocument,
)


class InquiryTextIndexDocumentRepository:
    @staticmethod
    def _values(document: dict[str, Any], task_id: str, indexed_at: datetime) -> dict:
        return {
            "document_key": str(document["document_key"]),
            "history_id": int(document["history_id"]),
            "inquiry_id": str(document["inquiry_id"]),
            "item_id": int(document["item_id"]),
            "item_code": str(document.get("item_code") or ""),
            "description": str(document["description"]),
            "content_hash": str(document["content_hash"]),
            "index_task_id": task_id,
            "indexed_at": indexed_at,
        }

    async def replace_all(self, documents: list[dict[str, Any]], task_id: str) -> None:
        """全量 Collection 生效后，在单个事务中替换在线文档镜像。"""
        indexed_at = datetime.now()
        values = [self._values(document, task_id, indexed_at) for document in documents]
        async with SessionLocal() as session:
            await session.execute(delete(InquiryTextIndexDocument))
            for offset in range(0, len(values), 1000):
                await session.execute(
                    mysql_insert(InquiryTextIndexDocument),
                    values[offset : offset + 1000],
                )
            await session.commit()

    async def upsert(self, documents: list[dict[str, Any]], task_id: str) -> None:
        if not documents:
            return
        indexed_at = datetime.now()
        values = [self._values(document, task_id, indexed_at) for document in documents]
        async with SessionLocal() as session:
            for offset in range(0, len(values), 1000):
                stmt = mysql_insert(InquiryTextIndexDocument).values(
                    values[offset : offset + 1000]
                )
                await session.execute(
                    stmt.on_duplicate_key_update(
                        history_id=stmt.inserted.history_id,
                        inquiry_id=stmt.inserted.inquiry_id,
                        item_id=stmt.inserted.item_id,
                        item_code=stmt.inserted.item_code,
                        description=stmt.inserted.description,
                        content_hash=stmt.inserted.content_hash,
                        index_task_id=stmt.inserted.index_task_id,
                        indexed_at=stmt.inserted.indexed_at,
                    )
                )
            await session.commit()

    async def delete(self, document_keys: list[str]) -> None:
        normalized = list(dict.fromkeys(str(key) for key in document_keys if key))
        if not normalized:
            return
        async with SessionLocal() as session:
            await session.execute(
                delete(InquiryTextIndexDocument).where(
                    InquiryTextIndexDocument.document_key.in_(normalized)
                )
            )
            await session.commit()

    @classmethod
    async def list_features_by_item_ids(
        cls,
        session,
        item_ids: list[int],
    ) -> dict[int, list[str]]:
        if not item_ids:
            return {}
        rows = await session.execute(
            select(
                InquiryTextIndexDocument.item_id,
                InquiryTextIndexDocument.description,
            )
            .where(InquiryTextIndexDocument.item_id.in_(sorted(set(item_ids))))
            .order_by(
                InquiryTextIndexDocument.item_id,
                InquiryTextIndexDocument.indexed_at.desc(),
                InquiryTextIndexDocument.document_key,
            )
        )
        features_by_item: dict[int, list[str]] = {}
        seen_by_item: dict[int, set[str]] = {}
        for item_id, description in rows:
            normalized = str(description or "").strip()
            if not normalized:
                continue
            item_id = int(item_id)
            seen = seen_by_item.setdefault(item_id, set())
            if normalized in seen:
                continue
            seen.add(normalized)
            features_by_item.setdefault(item_id, []).append(normalized)
        return features_by_item
