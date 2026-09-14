"""带条件图片检索的数据访问边界。"""

from __future__ import annotations

from sqlalchemy import func, select, update

from csrcqsf.models.orm.item import Items
from csrcqsf.models.orm.item_inquiry_history import ItemInquiryHistory
from csrcqsf.models.orm.search_history import SearchHistory
from csrcqsf.models.orm.sgo import SgoItemImages
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
    async def list_history_item_ids_by_vehicle(
        cls,
        session,
        vehicle_batch: str,
    ) -> list[int]:
        normalized_batch = str(vehicle_batch).strip().upper()
        if not normalized_batch:
            return []
        # 车型候选以真实询码记录为准；新数据使用归一化车型字段，旧数据缺失时
        # 回退到原始车型文本，避免正式物料车型关系缺失造成目标配件被提前排除。
        history_vehicle = func.upper(
            func.coalesce(
                func.nullif(func.trim(ItemInquiryHistory.vehicle_batch), ""),
                func.trim(ItemInquiryHistory.vehicle),
            )
        )
        result = await session.execute(
            select(ItemInquiryHistory.item_id)
            .where(ItemInquiryHistory.item_id.is_not(None))
            .where(history_vehicle == normalized_batch)
            .distinct()
        )
        return [int(item_id) for (item_id,) in result.all()]

    @classmethod
    async def list_item_ids_by_exact_name(cls, session, item_name: str) -> list[int]:
        # 配件名称只承担强过滤：忽略大小写和首尾空格，但不做模糊或语义匹配。
        normalized_name = str(item_name).strip().casefold()
        if not normalized_name:
            return []
        result = await session.execute(
            select(Items.id).where(
                func.lower(func.trim(Items.item_name)) == normalized_name
            )
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
    async def list_first_images_by_item_ids(cls, session, item_ids: list[int]):
        if not item_ids:
            return []
        normalized = sorted(set(item_ids))
        # 每个配件只取未删除图片中 ID 最小的一张作为列表封面，避免结果集重复膨胀。
        first_image_ids = (
            select(
                SgoItemImages.item_id.label("item_id"),
                func.min(SgoItemImages.id).label("image_id"),
            )
            .where(SgoItemImages.item_id.in_(normalized))
            .where(SgoItemImages.is_deleted == 0)
            .group_by(SgoItemImages.item_id)
            .subquery()
        )
        result = await session.execute(
            select(SgoItemImages).join(
                first_image_ids,
                SgoItemImages.id == first_image_ids.c.image_id,
            )
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
                query_text=parameters.item_description,
                search_results=results,
                search_result_item_name=(top_item.item_name if top_item else None),
                search_result_item_code=(top_item.item_code if top_item else ""),
                search_revision=expected_revision + 1,
            )
        )
        result = await session.execute(stmt)
        return int(result.rowcount or 0) == 1
