"""主库询码语义样本查询。"""

from __future__ import annotations

from sqlalchemy import select

from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.models.orm.item_inquiry_history import ItemInquiryHistory


class InquirySemanticRepository:
    async def list_by_ids(self, history_ids: list[int]) -> list[ItemInquiryHistory]:
        normalized = sorted({int(history_id) for history_id in history_ids})
        if not normalized:
            return []
        async with SessionLocal() as session:
            records = await session.scalars(
                select(ItemInquiryHistory)
                .where(ItemInquiryHistory.id.in_(normalized))
                .order_by(ItemInquiryHistory.id.asc())
            )
            return list(records)

    async def list_valid(self) -> list[ItemInquiryHistory]:
        async with SessionLocal() as session:
            records = await session.scalars(
                select(ItemInquiryHistory)
                .where(ItemInquiryHistory.item_id.is_not(None))
                .where(ItemInquiryHistory.inquiry_item_name.is_not(None))
                .where(ItemInquiryHistory.inquiry_item_name != "")
                .order_by(ItemInquiryHistory.id.asc())
            )
            return list(records)
