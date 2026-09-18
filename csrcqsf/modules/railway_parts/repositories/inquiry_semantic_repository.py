"""主库询码语义样本查询。"""

from __future__ import annotations

from datetime import datetime

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

    async def list_eligible_inquiry_ids(
        self,
        inquiry_ids: list[str],
        *,
        exclude_inquiry_id: str,
        before_inquiry_time: datetime,
    ) -> set[str]:
        normalized = sorted({str(inquiry_id) for inquiry_id in inquiry_ids if inquiry_id})
        if not normalized:
            return set()
        async with SessionLocal() as session:
            records = await session.execute(
                select(ItemInquiryHistory.inquiry_id)
                .where(ItemInquiryHistory.inquiry_id.in_(normalized))
                .where(ItemInquiryHistory.inquiry_id != exclude_inquiry_id)
                .where(ItemInquiryHistory.inquiry_time < before_inquiry_time)
            )
            return {str(inquiry_id) for (inquiry_id,) in records.all()}

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
