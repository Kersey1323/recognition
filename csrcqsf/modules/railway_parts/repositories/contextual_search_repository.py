"""带条件图片检索的数据访问边界。"""

from __future__ import annotations

from sqlalchemy import func, select, update

from csrcqsf.models.orm.item import Items
from csrcqsf.models.orm.item_inquiry_history import ItemInquiryHistory
from csrcqsf.models.orm.search_history import SearchHistory
from csrcqsf.models.orm.sgo_external import (
    SgoMaterielMasterplate,
    SgoMaterielVehicle,
)


class ContextualSearchRepository:
    @classmethod
    async def list_vehicle_item_codes(
        cls,
        session,
        vehicle_batch: str,
    ) -> set[str]:
        normalized_batch = str(vehicle_batch).strip().upper()
        stmt = (
            select(SgoMaterielMasterplate.MATNR)
            .select_from(SgoMaterielVehicle)
            .join(
                SgoMaterielMasterplate,
                SgoMaterielMasterplate.id == SgoMaterielVehicle.masterplate_id,
            )
            .where(
                func.upper(func.trim(SgoMaterielVehicle.vehicle_batch))
                == normalized_batch
            )
            .where(SgoMaterielMasterplate.MATNR.is_not(None))
            .distinct()
        )
        result = await session.execute(stmt)
        return {
            str(item_code).strip()
            for (item_code,) in result.all()
            if item_code is not None and str(item_code).strip()
        }

    @classmethod
    async def list_item_ids_by_codes(cls, session, item_codes: set[str]) -> list[int]:
        if not item_codes:
            return []
        result = await session.execute(
            select(Items.id).where(Items.item_code.in_(sorted(item_codes)))
        )
        return [int(item_id) for (item_id,) in result.all()]

    @classmethod
    async def list_items_by_ids(cls, session, item_ids: list[int]):
        if not item_ids:
            return []
        result = await session.execute(
            select(Items).where(Items.id.in_(sorted(set(item_ids))))
        )
        return list(result.scalars().all())

    @classmethod
    async def list_histories_by_item_ids(cls, session, item_ids: list[int]):
        if not item_ids:
            return []
        result = await session.execute(
            select(ItemInquiryHistory).where(
                ItemInquiryHistory.item_id.in_(sorted(set(item_ids)))
            )
        )
        return list(result.scalars().all())

    @classmethod
    async def get_history(cls, session, history_id: int):
        result = await session.execute(
            select(SearchHistory).where(SearchHistory.id == history_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def update_history_window(
        cls,
        session,
        *,
        history_id: int,
        expected_revision: int,
        previous_snapshot,
        query_images: list[str],
        parameters,
        results,
        top_item,
    ) -> bool:
        # 同一历史只允许一个 pending 请求按读取到的版本推进窗口。
        stmt = (
            update(SearchHistory)
            .where(SearchHistory.id == history_id)
            .where(SearchHistory.verify_status == "pending")
            .where(SearchHistory.search_revision == expected_revision)
            .values(
                previous_search_snapshot=previous_snapshot,
                query_image=query_images[0] if len(query_images) == 1 else None,
                query_images_json=query_images if len(query_images) > 1 else None,
                search_parameter=parameters,
                query_text=parameters.item_name,
                search_results=results,
                search_result_item_name=(top_item.item_name if top_item else None),
                search_result_item_code=(top_item.item_code if top_item else ""),
                search_revision=expected_revision + 1,
            )
        )
        result = await session.execute(stmt)
        return int(result.rowcount or 0) == 1
