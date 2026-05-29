"""
业务逻辑层 - 配件管理核心业务
职责：实现具体的业务逻辑、算法调用、数据处理
注意：此层包含核心业务实现，调用数据层和算法模块
"""
from __future__ import annotations

from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import sys
from csrcqsf.models.item import *
from bfrcommon.snowflake import get_id
from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.data.mdpdb import sgo_sessionLocal
from csrcqsf.models.search_history import (
    MatchedImage,
    SearchHistory,
    SearchResultItem,
    SearchResults,
    SearchReviewTicket,
)
# 导入Milvus向量检索管理器
from csrcqsf.biz.railwayparts.milvus import MilvusManager, ImageIndex
from csrcqsf.modules.railway_parts.repositories.search_history_repository import (
    SearchHistoryRepository,
)
from csrcqsf.modules.railway_parts.services import parts_search_service
from csrcqsf.modules.railway_parts.schemas.parts import (
    CreateItemImagesRes,
    GetItemDetailRes,
    IndexStatisticsRes,
    ItemImageIndexInfo,
    ItemImageItem,
    ItemSuggestItem,
    ItemSuggestRes,
    LisItemRes,
    ListItem,
    ListItemReq,
)
from csrcqsf.modules.railway_parts.schemas.review_ticket import (
    SearchReviewTicketDetailRes,
    SearchReviewTicketItem,
    SearchReviewTicketListReq,
    SearchReviewTicketListRes,
    SearchReviewTicketSummaryRes,
    SearchReviewTicketUpdateRes,
)
from csrcqsf.modules.railway_parts.schemas.search import (
    SearchHistoryDeleteRes,
    SearchHistoryFeedbackRes,
    SearchHistoryListItem,
    SearchHistoryListReq,
    SearchHistoryListRes,
    SearchHistorySummaryRes,
    SearchHistoryVerifyRes,
    SearchItem,
    SearchRes,
)
from bfrcommon.common import date_to_str
from globals_vars import logger
from csrcqsf.models.sgo import SgoItemImages, SegmentedImage
from csrcqsf.modules.sgo.schemas import ImageSourceType, ListInqueryItem, SegmentStatus
import numpy as np
import cv2
from anyio.to_thread import run_sync
from csrcqsf.settings import minio_bucket,minio_search_history_bucket,temp_dir

try:
    from csrcqsf.data.minio import ensure_minio_bucket, minio_instance, parse_minio_path
except Exception:  # pragma: no cover - import-time fallback for test patching only
    ensure_minio_bucket = None
    minio_instance = None
    parse_minio_path = None

MilvusManagerV2 = None
MilvusStateManagerV2 = None


def _get_minio_helpers():
    return ensure_minio_bucket, minio_instance, parse_minio_path


def _get_milvus_manager_v2_cls():
    global MilvusManagerV2
    if MilvusManagerV2 is None:
        from csrcqsf.modules.railway_parts.vector_search.storage.milvus_manager import (
            MilvusManagerV2 as _MilvusManagerV2,
        )

        MilvusManagerV2 = _MilvusManagerV2
    return MilvusManagerV2


def _get_milvus_state_manager_v2_cls():
    global MilvusStateManagerV2
    if MilvusStateManagerV2 is None:
        from csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager import (
            MilvusStateManagerV2 as _MilvusStateManagerV2,
        )

        MilvusStateManagerV2 = _MilvusStateManagerV2
    return MilvusStateManagerV2


def _bind_parts_search_runtime():
    parts_search_service.bind_runtime_dependencies(sys.modules[__name__])


class RailwayPartsManager:
    """
    配件管理核心业务类
    
    职责：
    1. 配件CRUD操作
    2. 图片管理和索引
    3. 特征提取和检索
    4. 与Milvus向量数据库交互
    """

    @classmethod
    async def init(cls):
        """初始化配件管理器"""
        pass

    @classmethod
    async def create_item(
        cls,
        item_name: str,
        item_code: str,
        obj_url: str = None,
        height: float = None,
        length: float = None,
        width: float = None,
        weight: float = None,
        parent_item_id: int | None = None,
    ):
        """
        创建配件实体
        
        参数：
            item_name: 配件名称
            item_code: 配件编码
            obj_url: 3D模型URL（可选）
            height/length/width: 尺寸信息（可选）
        
        数据库操作：Items.create_item() in models/item.py
        """
        async with SessionLocal() as session:
            normalized_parent_item_id = cls._normalize_parent_item_id(parent_item_id)
            if normalized_parent_item_id > 0:
                parent_item = await Items.get_item_by_id(
                    session=session,
                    item_id=normalized_parent_item_id,
                )
                if parent_item is None:
                    raise Exception(f'id为{normalized_parent_item_id}的父配件不存在')

            item = Items(
                item_name=item_name,
                item_code=item_code,
                parent_item_id=normalized_parent_item_id,
                obj_url=obj_url,
                height=height,
                long=length,
                width=width,
                weight=weight,
                id=get_id()
            )
            await Items.create_item(session=session, item=item)
            await ItemsParent.replace_parent_relations(
                session=session,
                item_id=item.id,
                parent_item_id=normalized_parent_item_id,
            )
            # if len(pic_urls) > 0:
            #     await ItemImage.create_images(session=session, item_id=item.id, images=pic_urls)
            await session.commit()

    @staticmethod
    def _normalize_parent_item_id(parent_item_id: int | None) -> int:
        if parent_item_id is None or parent_item_id <= 0:
            return 0
        return parent_item_id

    @classmethod
    async def delete_pic(cls, image_id: int):
        async with SessionLocal() as session:
            await SgoItemImages.delete_image(session=session, image_id=image_id)
            await session.commit()

    @classmethod
    async def delete_item(cls, item_id_list: list[int]):
        async with SessionLocal() as session:
            await Items.delete_item_by_id_list(session=session, item_id_list=item_id_list)
            await session.commit()

    @classmethod
    async def update_item(
        cls,
        item_id: int,
        update_fields: set[str],
        item_name: str | None = None,
        item_code: str | None = None,
        parent_item_id: int | None = None,
        length: float | None = None,
        width: float | None = None,
        height: float | None = None,
        weight: float | None = None,
    ):
        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session=session, item_id=item_id)
            if item is None:
                raise Exception(f'id为{item_id}的配件不存在')

            normalized_parent_item_id = cls._normalize_parent_item_id(parent_item_id)

            if "item_name" in update_fields and (item_name is None or str(item_name).strip() == ""):
                raise Exception("配件名称不能为空")

            if "item_code" in update_fields and (item_code is None or str(item_code).strip() == ""):
                raise Exception("物料编码不能为空")

            if "item_code" in update_fields and item.item_code != item_code:
                item_by_code = await Items.get_item_by_item_code(session=session, item_code=item_code)
                if item_by_code is not None:
                    raise Exception(f"物料编码:{item_code}已经存在了")

            if "parent_item_id" in update_fields and normalized_parent_item_id > 0:
                parent_item = await Items.get_item_by_id(session=session, item_id=normalized_parent_item_id)
                if parent_item is None:
                    raise Exception(f'id为{normalized_parent_item_id}的父配件不存在')

            values = Items.build_item_updates(
                fields=update_fields,
                item_name=item_name,
                item_code=item_code,
                parent_item_id=normalized_parent_item_id,
                height=height,
                length=length,
                width=width,
                weight=weight,
            )
            await Items.update_item_fields(session=session, item_id=item_id, values=values)
            if "parent_item_id" in update_fields:
                await ItemsParent.replace_parent_relations(
                    session=session,
                    item_id=item_id,
                    parent_item_id=normalized_parent_item_id,
                )
            await session.commit()

    @classmethod
    async def list_item(cls, req: ListItemReq):
        item_code_list = []
        if req.has_inquery_code == 1:
            async with sgo_sessionLocal() as session:
                stmt = select(SgoCodeInquiryReturn.item_code.distinct())
                data = await session.scalars(stmt)
                item_code_list = list(data.all())

        async with SessionLocal() as session:
            item_id_list = []
            if req.parent_item_id != 0:
                data = await ItemsParent.list_item_by_parent_id(session, req.parent_item_id)
                for d in data:
                    item_id_list.append(d.item_id)  
            has_index_flag = True if req.only_has_index == 1 else False
            images_has = True if req.has_images == 1 else False
            items = await Items.list_items(
                session=session,
                query=req.query,
                page=req.page,
                per_page=req.per_page,
                has_images=images_has,
                item_id_list=item_id_list,
                item_code_list=item_code_list,
                need_index=False,
                need_v2_index=has_index_flag,
                has_source_video=req.has_source_video,
            )

            index_dict = _get_milvus_state_manager_v2_cls()().list_item_index([item.id for item in items.data])

            images = await RailwayPartsManager.list_item_images([item.id for item in items.data])
            images_dict: dict[int, list[SgoItemImages]] = {}

            for image in images:
                if image.item_id not in images_dict:
                    images_dict[image.item_id] = []
                images_dict[image.item_id].append(image)

            res = LisItemRes(
                total=items.total
            )
            for item in items.data:
                item_desc = ListItem(
                    item_name=item.item_name,
                    item_code=item.item_code,
                    ply_url=item.obj_url,
                    height=item.height,
                    width=item.width,
                    length=item.long,
                    weight=item.weight,
                    video_path=item.source_video_path,
                    has_index=1 if item.has_v2_index == 1 else 0,
                    has_source_video=1 if item.source_video_path else 0,
                    images_total_indexed_num=item.v2_indexed_image_num,
                    id=str(item.id),
                    created_at=date_to_str(item.time_created)
                )
                if item.id in images_dict:
                    item_desc.images_total_num = len(images_dict[item.id])

                index = index_dict.get(item.id)
                if index is not None:
                    item_desc.features = [f.feature for f in index.features]
                    item_desc.features_num = len(index.features)
                res.items.append(item_desc)
            return res

    @classmethod
    async def list_item_images(cls, item_id_list: list[int]):
        async with SessionLocal() as session:
            result = await SgoItemImages.list_item_images_by_item_id_list(session, item_id_list)
            return list(result) if result else []

    @classmethod
    async def delete_item_image_index(cls, item_id: int, image_url_list: list[str]):

        now_index_list = await MilvusManager.list_item_index([item_id])

        if item_id not in now_index_list:
            raise Exception(f'特征数据库并没有该配件的索引信息')

        index = now_index_list[item_id]

        image_url_set = set(image_url_list)

        new_image_index_list: list[ImageIndex] = []

        for image_index in index.images:
            if image_index.filename not in image_url_set:
                new_image_index_list.append(image_index)

        index.images = new_image_index_list  # 覆盖
        
        if len(index.images) > 0:
            await MilvusManager.upsert_data(index)
            async with SessionLocal() as session:
                await Items.update_items_index(session=session, item_id=item_id,
                                               image_index_num=len(index.images), feature_index_num=len(index.features))
                await session.commit()
        else:
            await MilvusManager.delete_part_index(item_id)
            async with SessionLocal() as session:
                await Items.update_items_index(session=session, item_id=item_id,
                                               image_index_num=0, feature_index_num=0)
                await session.commit()

    @classmethod
    async def _upload_v2_segmented_image(
        cls,
        image,
        item_id: int,
        source_image_id: int,
    ) -> str:
        """上传 V2 索引流程生成的分割图到 MinIO。"""
        ensure_minio_bucket(minio_bucket)
        Path(temp_dir).mkdir(parents=True, exist_ok=True)

        token = get_id()
        object_name = f"v2-segmented/{item_id}/{source_image_id}_{token}.jpg"
        local_path = os.path.join(temp_dir, f"v2_segmented_{token}.jpg")

        try:
            rgb_image = image.convert("RGB")
            await run_sync(rgb_image.save, local_path, "JPEG")
            await run_sync(
                minio_instance.upload_file,
                minio_bucket,
                object_name,
                local_path,
                "image/jpeg",
            )
            return f"{minio_bucket}/{object_name}"
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)

    @classmethod
    async def _upload_v2_search_query_image(
        cls,
        history_id: int,
        filename: str,
        content_bytes: bytes,
    ) -> str:
        _bind_parts_search_runtime()
        return await parts_search_service._upload_v2_search_query_image(
            cls,
            history_id=history_id,
            filename=filename,
            content_bytes=content_bytes,
        )

    @classmethod
    async def _persist_v2_search_history(
        cls,
        *,
        history_id: int,
        query_text: str | None,
        query_image: str | None,
        query_images: list[str] | None,
        search_equipment: str,
        search_items: list[SearchItem],
    ) -> None:
        _bind_parts_search_runtime()
        return await parts_search_service._persist_v2_search_history(
            cls,
            history_id=history_id,
            query_text=query_text,
            query_image=query_image,
            query_images=query_images,
            search_equipment=search_equipment,
            search_items=search_items,
        )

    @classmethod
    def _aggregate_v2_search_items(cls, search_items: list[SearchItem]) -> list[SearchItem]:
        _bind_parts_search_runtime()
        return parts_search_service._aggregate_v2_search_items(
            cls,
            search_items=search_items,
        )

    @classmethod
    def _build_search_item_from_hit(cls, hit: dict) -> SearchItem:
        _bind_parts_search_runtime()
        return parts_search_service._build_search_item_from_hit(
            cls,
            hit=hit,
        )

    @classmethod
    def _fuse_multi_image_search_results(cls, per_query_results: list[list[dict]], rrf_k: int = 60) -> list[dict]:
        _bind_parts_search_runtime()
        return parts_search_service._fuse_multi_image_search_results(
            cls,
            per_query_results=per_query_results,
            rrf_k=rrf_k,
        )

    @classmethod
    def _normalize_review_status(
        cls,
        status: str | None,
        latest_review_status: str | None = None,
    ) -> str:
        _bind_parts_search_runtime()
        return parts_search_service._normalize_review_status(
            cls,
            status=status,
            latest_review_status=latest_review_status,
        )

    @classmethod
    def _get_search_result_candidates(cls, history) -> list[SearchResultItem]:
        _bind_parts_search_runtime()
        return parts_search_service._get_search_result_candidates(
            cls,
            history=history,
        )

    @classmethod
    def _resolve_correct_result_from_history(cls, row) -> dict:
        _bind_parts_search_runtime()
        return parts_search_service._resolve_correct_result_from_history(
            cls,
            row=row,
        )

    @classmethod
    def _resolve_feedback_correct_fields(
        cls,
        history,
        *,
        feedback_result: str,
        resolved_selected: dict,
    ) -> dict:
        _bind_parts_search_runtime()
        return parts_search_service._resolve_feedback_correct_fields(
            cls,
            history=history,
            feedback_result=feedback_result,
            resolved_selected=resolved_selected,
        )

    @classmethod
    def _match_correct_item_in_history_results(
        cls,
        history,
        *,
        item_id: int | None = None,
        item_code: str | None = None,
    ):
        _bind_parts_search_runtime()
        return parts_search_service._match_correct_item_in_history_results(
            cls,
            history=history,
            item_id=item_id,
            item_code=item_code,
        )

    @classmethod
    async def _resolve_correct_image_url(
        cls,
        session,
        *,
        item_id: int,
        history=None,
        item_code: str | None = None,
    ):
        _bind_parts_search_runtime()
        return await parts_search_service._resolve_correct_image_url(
            cls,
            session=session,
            item_id=item_id,
            history=history,
            item_code=item_code,
        )

    @classmethod
    async def _resolve_system_top1_correct_fields(cls, session, history) -> dict:
        _bind_parts_search_runtime()
        return await parts_search_service._resolve_system_top1_correct_fields(
            cls,
            session=session,
            history=history,
        )

    @classmethod
    def _resolve_selected_feedback_candidate(
        cls,
        history,
        *,
        feedback_result: str,
        selected_item_id: str | None,
    ) -> dict:
        _bind_parts_search_runtime()
        return parts_search_service._resolve_selected_feedback_candidate(
            cls,
            history=history,
            feedback_result=feedback_result,
            selected_item_id=selected_item_id,
        )

    @classmethod
    def _build_search_history_item(cls, row, latest_ticket=None):
        _bind_parts_search_runtime()
        return parts_search_service._build_search_history_item(
            cls,
            row=row,
            latest_ticket=latest_ticket,
        )

    @classmethod
    def _build_search_review_ticket_item(cls, row):
        _bind_parts_search_runtime()
        return parts_search_service._build_search_review_ticket_item(
            cls,
            row=row,
        )

    @classmethod
    def _build_search_review_ticket_detail(cls, ticket, history):
        _bind_parts_search_runtime()
        return parts_search_service._build_search_review_ticket_detail(
            cls,
            ticket=ticket,
            history=history,
        )

    @classmethod
    async def _enrich_search_history_result_item_names(cls, session, rows) -> None:
        _bind_parts_search_runtime()
        return await parts_search_service._enrich_search_history_result_item_names(
            cls,
            session=session,
            rows=rows,
        )

    @classmethod
    async def list_v2_search_history(cls, req: SearchHistoryListReq):
        _bind_parts_search_runtime()
        return await parts_search_service.list_v2_search_history(
            cls,
            req=req,
        )

    @classmethod
    async def get_v2_search_history_detail(cls, history_id: int):
        _bind_parts_search_runtime()
        return await parts_search_service.get_v2_search_history_detail(
            cls,
            history_id=history_id,
        )

    @classmethod
    async def summary_v2_search_history(cls):
        _bind_parts_search_runtime()
        return await parts_search_service.summary_v2_search_history(cls)

    @classmethod
    async def list_v2_search_review_tickets(cls, req: SearchReviewTicketListReq):
        _bind_parts_search_runtime()
        return await parts_search_service.list_v2_search_review_tickets(
            cls,
            req=req,
        )

    @classmethod
    async def get_v2_search_review_ticket_detail(cls, ticket_id: int):
        _bind_parts_search_runtime()
        return await parts_search_service.get_v2_search_review_ticket_detail(
            cls,
            ticket_id=ticket_id,
        )

    @classmethod
    async def summary_v2_search_review_ticket(cls):
        _bind_parts_search_runtime()
        return await parts_search_service.summary_v2_search_review_ticket(cls)

    @classmethod
    async def update_v2_search_review_ticket(
        cls,
        *,
        ticket_id: int,
        review_status: str,
        issue_type: str | None = None,
        review_remark: str | None = None,
        resolution_remark: str | None = None,
        correct_item_code: str | None = None,
    ):
        _bind_parts_search_runtime()
        return await parts_search_service.update_v2_search_review_ticket(
            cls,
            ticket_id=ticket_id,
            review_status=review_status,
            issue_type=issue_type,
            review_remark=review_remark,
            resolution_remark=resolution_remark,
            correct_item_code=correct_item_code,
        )

    @classmethod
    async def verify_v2_search_history(
        cls,
        *,
        history_id: int,
        verify_status: str,
        correct_item_code: str | None,
        remark: str | None,
    ):
        _bind_parts_search_runtime()
        return await parts_search_service.verify_v2_search_history(
            cls,
            history_id=history_id,
            verify_status=verify_status,
            correct_item_code=correct_item_code,
            remark=remark,
        )

    @classmethod
    async def suggest_items(cls, keyword: str, limit: int = 10):
        _bind_parts_search_runtime()
        return await parts_search_service.suggest_items(
            cls,
            keyword=keyword,
            limit=limit,
        )

    @classmethod
    async def delete_v2_search_history(cls, history_id_list: list[int]):
        _bind_parts_search_runtime()
        return await parts_search_service.delete_v2_search_history(
            cls,
            history_id_list=history_id_list,
        )

    @classmethod
    async def search_v2_by_text(
        cls,
        query_text: str,
        top_k: int = 10,
        search_equipment: str = "web",
    ):
        _bind_parts_search_runtime()
        return await parts_search_service.search_v2_by_text(
            cls,
            query_text=query_text,
            top_k=top_k,
            search_equipment=search_equipment,
        )

    @classmethod
    async def search_v2_by_image(
        cls,
        file,
        top_k: int = 10,
        search_mode: str = "hybrid",
        search_equipment: str = "web",
    ):
        _bind_parts_search_runtime()
        return await parts_search_service.search_v2_by_image(
            cls,
            file=file,
            top_k=top_k,
            search_mode=search_mode,
            search_equipment=search_equipment,
        )

    @classmethod
    async def search_v2_by_images(
        cls,
        files: list,
        top_k: int = 10,
        search_mode: str = "hybrid",
        search_equipment: str = "web",
    ):
        _bind_parts_search_runtime()
        return await parts_search_service.search_v2_by_images(
            cls,
            files=files,
            top_k=top_k,
            search_mode=search_mode,
            search_equipment=search_equipment,
        )

    @classmethod
    async def submit_v2_search_feedback(
        cls,
        *,
        history_id: int,
        feedback_result: str,
        remark: str | None,
        selected_item_id: str | None = None,
    ):
        _bind_parts_search_runtime()
        return await parts_search_service.submit_v2_search_feedback(
            cls,
            history_id=history_id,
            feedback_result=feedback_result,
            remark=remark,
            selected_item_id=selected_item_id,
        )

    @classmethod
    async def update_item_size(cls, item_id: int, item_size_str: str):
        async with SessionLocal() as session:
            await Items.put_item_size_desc(session=session, item_id=item_id, size_desc=item_size_str)
            await session.commit()

    @classmethod
    async def get_item_detail(cls, item_id: int):
        state_manager = _get_milvus_state_manager_v2_cls()()
        index_detail = state_manager.list_item_index([item_id])
        indexed_image_dict = state_manager.get_indexed_images_by_item_id(item_id)

        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session=session, item_id=item_id)
            if item is None:
                raise Exception(f'id为{item_id}的配件不存在')
            parent_item = None
            # if item.parent_item_id is not None and item.parent_item_id > 0:
            #     parent_item = await Items.get_item_by_id(session=session, item_id=item.parent_item_id)
            #     if parent_item is None:
            #         raise Exception(f'父节点信息找不到')

            images = SgoItemImages.get_images(session=session, item_id=item_id)
            segmented_records = list(await SegmentedImage.list_by_item_id(session, item_id))
            segmented_image_dict: dict[int, str | None] = {}
            for record in segmented_records:
                source_image_id = int(record.source_image_id)
                if source_image_id in segmented_image_dict:
                    continue
                if record.status == SegmentStatus.SUCCESS and record.segmented_image_url:
                    segmented_image_dict[source_image_id] = record.segmented_image_url
                else:
                    segmented_image_dict[source_image_id] = None
            res = GetItemDetailRes(
                ply_url=item.obj_url,
                id=str(item.id),
                height=item.height,
                width=item.width,
                length=item.long,
                weight=item.weight,
                video_path=item.source_video_path,
                name=item.item_name,
                item_code=item.item_code,
                created_at=date_to_str(item.time_created),
                updated_at=date_to_str(item.time_updated),
                size_str=item.size_str,
            )
            if index_detail.get(item_id) is not None:
                for feature in index_detail.get(item_id).features:
                    res.features.append(feature.feature)
            # if parent_item is not None:
            #     res.parent_item_id = str(item.parent_item_id)
            #     res.parent_item_name = parent_item.item_name
            #     res.parent_item_code = parent_item.item_code
            for image_id, image_url in sorted(indexed_image_dict.items()):
                res.images_index_list.append(
                    ItemImageIndexInfo(
                        image_id=str(image_id),
                        image_url=segmented_image_dict.get(image_id) or image_url
                    )
                )
            async for image in images:
                image_item = ItemImageItem(
                    image_id=str(image.id),
                    has_indexed=1 if image.id in indexed_image_dict else 0,
                    image_url=image.image_url or indexed_image_dict.get(image.id),
                    source_type=image.image_source
                )
                res.images.append(image_item)
        return res

    @classmethod
    async def create_item_image(cls, item_id: int, image_url_list: list[str]):
        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session, item_id)
            if item is None:
                raise Exception(f'配件不存在')

            item_images_result = await SgoItemImages.list_item_images_by_item_id(session, item_id=item_id)
            item_images = list(item_images_result) if item_images_result else []

            image_url_set = set()
            for image in item_images:
                image_url_set.add(image.image_url)

            image_list = []
            for image_url in image_url_list:
                if image_url in image_url_set:
                    continue
                image = SgoItemImages(
                    item_id=item_id,
                    image_url=image_url,
                    image_source=ImageSourceType.CREATEBYSELF,
                    is_indexed=1,
                )
                image_list.append(image)

            if len(image_list) > 0:
                await SgoItemImages.create_item_images(session, image_list)
                await session.commit()

        return {
            "item_id": item_id,
            "uploaded_count": len(image_list),
            "records": [
                {
                    "image_id": image.id,
                    "image_url": image.image_url,
                    "filename": Path(image.image_url).name,
                }
                for image in image_list
            ],
            "message": "配件图片登记成功",
        }

    @classmethod
    def _safe_upload_filename(cls, filename: str | None, fallback: str = "image.bin") -> str:
        raw_name = Path(filename or fallback).name
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
        return safe_name or fallback

    @classmethod
    async def _delete_minio_object(cls, object_path: str) -> None:
        _, minio_instance, parse_minio_path = _get_minio_helpers()
        bucket, object_name = parse_minio_path(object_path, default_bucket=minio_bucket)

        def _delete():
            minio_instance.client.remove_object(bucket, object_name)

        await run_sync(_delete)

    @classmethod
    async def create_item_image_files(cls, item_id: int, files: list) -> dict:
        if len(files) == 0:
            raise Exception("未上传图片文件")

        ensure_minio_bucket, minio_instance, _ = _get_minio_helpers()
        ensure_minio_bucket(minio_bucket)

        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session, item_id)
            if item is None:
                raise Exception("配件不存在")

            uploaded_paths: list[str] = []
            image_rows: list[SgoItemImages] = []
            uploaded_filenames: list[str] = []

            try:
                for file in files:
                    safe_name = cls._safe_upload_filename(file.filename, fallback="image.jpg")
                    date_dir = datetime.now().strftime("%Y%m%d")
                    object_name = f"manual-upload/{item_id}/{date_dir}/{get_id()}_{safe_name}"
                    content_type = file.content_type or "application/octet-stream"

                    def _upload() -> int:
                        file.file.seek(0, os.SEEK_END)
                        size = file.file.tell()
                        file.file.seek(0)
                        minio_instance.client.put_object(
                            minio_bucket,
                            object_name,
                            file.file,
                            length=size,
                            content_type=content_type,
                        )
                        return size

                    await run_sync(_upload)
                    await file.close()

                    image_url = f"{minio_bucket}/{object_name}"
                    uploaded_paths.append(image_url)
                    uploaded_filenames.append(safe_name)
                    image_rows.append(
                        SgoItemImages(
                            item_id=item_id,
                            image_url=image_url,
                            raw_url=None,
                            image_source=ImageSourceType.CREATEBYSELF,
                            is_indexed=1,
                        )
                    )

                await SgoItemImages.create_item_images(session, image_rows)
                await session.commit()
            except Exception:
                await session.rollback()
                for image_url in uploaded_paths:
                    try:
                        await cls._delete_minio_object(image_url)
                    except Exception:
                        pass
                raise

        return {
            "item_id": item_id,
            "uploaded_count": len(image_rows),
            "records": [
                {
                    "image_id": image.id,
                    "image_url": image.image_url,
                    "filename": filename,
                }
                for image, filename in zip(image_rows, uploaded_filenames)
            ],
            "message": "配件图片上传成功",
        }

    @classmethod
    async def get_image_from_oss(cls, image_url: str):
        """
        image_url格式为 {bucket_name}/{file_name}的格式
        """
        _, minio_instance, _ = _get_minio_helpers()
        def _():
            file_name_arr = image_url.split("/")
            if len(file_name_arr) < 2:
                raise Exception(f'文件名格式不正确')

            aim_file_name = file_name_arr[1]

            try:
                response = minio_instance.client.get_object(
                    minio_bucket, aim_file_name)
                # Read data from response.
                if response.status != 200:
                    raise Exception(f'oss请求出错')

                if response.data:
                    nparr = np.frombuffer(response.data, np.uint8)
                    # 将数组解码为彩色图像
                    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    try:
                        image = cls.resize_image(image)
                        return image
                    except Exception as e:
                        pass

            finally:
                if response:
                    response.close()
                    response.release_conn()
        return await run_sync(_)

    @classmethod
    def resize_image(cls, image, max_size=1920):
        height, width = image.shape[:2]
        if max(height, width) > max_size:
            scale = max_size / max(height, width)
            new_height = int(height * scale)
            new_width = int(width * scale)
            image = cv2.resize(image, (new_width, new_height),
                               interpolation=cv2.INTER_AREA)
        return image

    @classmethod
    # rebuild_pic_index 方法已删除，请使用 rebuild_v2_index

    @classmethod
    async def statistics(cls):
        res = IndexStatisticsRes()
        async with SessionLocal() as session:
            res.total_item_num = await async_get_count(session, select(Items))

        state_manager = _get_milvus_state_manager_v2_cls()()
        snapshot = state_manager.get_statistics_snapshot()
        item_state_snapshot = state_manager.get_item_index_state_snapshot()

        res.total_image_index = int(snapshot.get("siglip_count", 0) or 0)
        res.total_feature_index = int(snapshot.get("dinov2_count", 0) or 0)
        res.total_index = res.total_image_index + res.total_feature_index
        res.total_indexed_item_num = sum(
            1
            for item_state in item_state_snapshot.values()
            if int(item_state.get("has_v2_index", 0) or 0) == 1
        )
        res.recognition_number = 0
        res.corrrect_recognition_number = 0
        res.recognition_ration = 0
        return res

    @classmethod
    def reciprocal_rank_fusion(search_results_list, k=60):
        """
        手动实现倒数排序融合（RRF）算法，合并多个搜索结果列表。

        :param search_results_list: 一个列表，每个元素是一次搜索返回的Hits对象列表。
        :param k: 平滑因子，默认为60。
        :return: 按RRF分数降序排列的 (文档ID, RRF分数) 元组列表。
        """
        fused_scores = {}

        # 遍历每一个独立的搜索结果列表
        for result_list in search_results_list:
            # 遍历当前列表中的每个结果及其排名（排名从1开始）
            for rank, hit in enumerate(result_list, start=1):
                doc_id = hit.id  # 假设hit.id是文档的唯一标识
                # 计算当前文档在当前列表中的RRF分数
                rrf_score = 1 / (rank + k)
                # 累加分数
                fused_scores[doc_id] = fused_scores.get(
                    doc_id, 0.0) + rrf_score

        # 根据融合后的总分进行降序排序
        final_ranking = sorted(fused_scores.items(),
                               key=lambda x: x[1], reverse=True)
        return final_ranking


    # ==================== 新向量数据库功能 (SigLIP + DINOv2) ====================
    
    @classmethod
    async def create_v2_collections(cls, drop_existing: bool = False):
        """
        创建新的向量数据库集合 (SigLIP + DINOv2)
        
        Args:
            drop_existing: 是否删除已存在的集合（默认 False）
        """
        manager = _get_milvus_state_manager_v2_cls()()
        
        if drop_existing:
            logger.warning("删除已存在的集合...")
            await run_sync(manager.drop_collections)
            logger.info("已存在的集合已删除")
        
        await run_sync(manager.create_collections)
        logger.info("V2 collections created successfully")
    
    
    
    @classmethod
    async def rebuild_v2_index(
        cls,
        item_id: int = None,
        limit: int = None,
        rebuild_existing: bool = False,
    ):
        """
        使用新算法重建索引 (SigLIP + DINOv2)
        
        Args:
            item_id: 指定配件ID（可选，为空则重建所有）
            limit: 限制处理数量（可选，用于测试）
            rebuild_existing: 是否重建已存在的索引
        """
        
        manager = _get_milvus_manager_v2_cls()()
        state_manager = _get_milvus_state_manager_v2_cls()()
        
        async with SessionLocal() as session:
            # 获取需要建库的配件
            if item_id:
                items = [await Items.get_item_by_id(session, item_id)]
                if items[0] is None:
                    raise Exception(f'配件不存在: {item_id}')
            else:
                item_id_stmt = select(SgoItemImages.item_id).distinct()
                stmt = select(Items).where(Items.id.in_(item_id_stmt))
                if not rebuild_existing:
                    stmt = stmt.where(Items.has_v2_index == 0)
                stmt = stmt.order_by(Items.time_created.desc()).order_by(Items.id.desc())
                if limit is not None:
                    stmt = stmt.limit(limit)
                items = list(await session.scalars(stmt))
            
            logger.info(f"开始为 {len(items)} 个配件建立 V2 索引")
            
            success_count = 0
            fail_count = 0
            processed_item_count = 0
            skipped_existing_count = 0
            from tqdm import tqdm
            for item in tqdm(items):
                if item is None:
                    continue
                if not rebuild_existing and getattr(item, "has_v2_index", 0) == 1:
                    skipped_existing_count += 1
                    logger.info(f"跳过已存在索引的配件: item={item.id}")
                    continue

                try:
                    # 获取配件的图片
                    images_result = await SgoItemImages.list_item_images_by_item_id(session, item.id)
                    # 将 ScalarResult 转换为列表
                    images = list(images_result) if images_result else []
                    item_success_count = 0
                    success_image_ids: list[int] = []
                    segmented_records_to_create: list[SegmentedImage] = []
                    deleted_existing = False
                    image_status_changed = False
                    
                    if len(images) == 0:
                        logger.warning(f"配件 {item.id} 没有图片，跳过")
                        continue

                    if rebuild_existing and getattr(item, "has_v2_index", 0) == 1:
                        delete_result = state_manager.delete_item_index(item.id)
                        await SgoItemImages.un_indexed_image(
                            session=session,
                            image_id_list=[img.id for img in images],
                        )
                        await SegmentedImage.delete_by_item_id(session, item.id)
                        deleted_existing = True
                        image_status_changed = True
                        logger.info(
                            "强制重建前已删除旧索引: item=%s, siglip=%s, dinov2=%s",
                            item.id,
                            int(delete_result.get("siglip_deleted", 0) or 0),
                            int(delete_result.get("dinov2_deleted", 0) or 0),
                        )

                    processed_item_count += 1
                    
                    # 为每张图片建立索引
                    for img in images:
                        try:
                            # 从 MinIO 加载图片
                            image_array = await cls.get_image_from_oss(img.image_url)
                            if image_array is None:
                                logger.warning(f"图片加载失败: {img.image_url}")
                                continue
                            
                            # 转换 numpy array 为 PIL Image
                            from PIL import Image
                            import cv2
                            # cv2 读取的是 BGR 格式，需要转换为 RGB
                            image_rgb = cv2.cvtColor(image_array, cv2.COLOR_BGR2RGB)
                            pil_image = Image.fromarray(image_rgb)
                            
                            # 建立索引
                            siglip_ok, dinov2_ok = await manager.index_image(
                                image=pil_image,
                                item_id=item.id,
                                item_name=item.item_name,
                                item_code=item.item_code,
                                image_id=img.id,
                                image_url=img.image_url,
                                description=item.item_name
                            )

                            preprocess_outcome = getattr(
                                manager,
                                "last_preprocess_outcome",
                                None,
                            )
                            if preprocess_outcome is not None:
                                if preprocess_outcome.result_image is not None:
                                    try:
                                        segmented_url = await cls._upload_v2_segmented_image(
                                            preprocess_outcome.result_image,
                                            item.id,
                                            img.id,
                                        )
                                        segmented_records_to_create.append(
                                            SegmentedImage(
                                                id=get_id(),
                                                item_id=item.id,
                                                source_image_id=img.id,
                                                source_image_url=img.image_url,
                                                segmented_image_url=segmented_url,
                                                status=SegmentStatus.SUCCESS,
                                                is_indexed=1 if siglip_ok and dinov2_ok else 0,
                                            )
                                        )
                                    except Exception as e:
                                        logger.warning(
                                            "保存分割图失败: item=%s, image=%s, error=%s",
                                            item.id,
                                            img.id,
                                            e,
                                        )
                                        segmented_records_to_create.append(
                                            SegmentedImage(
                                                id=get_id(),
                                                item_id=item.id,
                                                source_image_id=img.id,
                                                source_image_url=img.image_url,
                                                status=SegmentStatus.FAILED,
                                                is_indexed=0,
                                                error_message=str(e),
                                            )
                                        )
                                else:
                                    segmented_records_to_create.append(
                                        SegmentedImage(
                                            id=get_id(),
                                            item_id=item.id,
                                            source_image_id=img.id,
                                            source_image_url=img.image_url,
                                            status=SegmentStatus.FAILED,
                                            is_indexed=0,
                                            error_message="SAM3 preprocessing returned no segmented image",
                                        )
                                    )
                            
                            if siglip_ok and dinov2_ok:
                                success_count += 1
                                item_success_count += 1
                                success_image_ids.append(img.id)
                                logger.info(f"索引成功: item={item.id}, image={img.id}")
                            else:
                                fail_count += 1
                                logger.warning(f"索引部分失败: item={item.id}, siglip={siglip_ok}, dinov2={dinov2_ok}")
                        
                        except Exception as e:
                            fail_count += 1
                            logger.error(f"索引失败: item={item.id}, image={img.id}, error={e}")
                
                except Exception as e:
                    fail_count += 1
                    logger.error(f"处理配件失败: item={item.id}, error={e}")
                    continue

                if len(success_image_ids) > 0:
                    await SgoItemImages.indexed_image(
                        session=session,
                        image_id_list=success_image_ids,
                    )
                    image_status_changed = True

                if len(segmented_records_to_create) > 0:
                    await SegmentedImage.batch_create(session, segmented_records_to_create)
                    image_status_changed = True

                if image_status_changed:
                    await session.commit()

                if item_success_count > 0 or deleted_existing:
                    await cls.sync_item_v2_index_state(
                        item.id, state_manager=state_manager
                    )
            
            logger.info(f"V2 索引重建完成: 成功={success_count}, 失败={fail_count}")
            
            return {
                'success_count': success_count,
                'fail_count': fail_count,
                'total': success_count + fail_count,
                'processed_item_count': processed_item_count,
                'skipped_existing_count': skipped_existing_count,
            }

    @classmethod
    async def delete_v2_index(cls, item_id: int) -> dict:
        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session=session, item_id=item_id)
            if item is None:
                raise Exception(f'配件不存在: {item_id}')

        delete_result = _get_milvus_state_manager_v2_cls()().delete_item_index(item_id)
        async with SessionLocal() as session:
            await Items.update_v2_index_state(
                session=session,
                item_id=item_id,
                has_v2_index=False,
                v2_indexed_image_num=0,
                updated_at=datetime.now(),
            )
            await session.commit()
        return {
            "item_id": item_id,
            "siglip_deleted": int(delete_result.get("siglip_deleted", 0) or 0),
            "dinov2_deleted": int(delete_result.get("dinov2_deleted", 0) or 0),
            "message": "V2索引删除成功",
        }

    @classmethod
    async def sync_all_v2_index_state(cls) -> dict:
        snapshot = _get_milvus_state_manager_v2_cls()().get_item_index_state_snapshot()
        updated_at = datetime.now()
        rows = [
            {
                "item_id": item_id,
                "has_v2_index": state["has_v2_index"],
                "v2_indexed_image_num": state["v2_indexed_image_num"],
                "updated_at": updated_at,
            }
            for item_id, state in snapshot.items()
        ]

        async with SessionLocal() as session:
            await Items.reset_v2_index_state(session=session, updated_at=updated_at)
            if len(rows) > 0:
                await Items.bulk_update_v2_index_state(session=session, rows=rows)
            await session.commit()

        return {
            "indexed_item_count": len(rows),
            "updated_at": date_to_str(updated_at),
        }

    @classmethod
    async def sync_item_v2_index_state(
        cls,
        item_id: int,
        state_manager=None,
    ):
        manager = state_manager or _get_milvus_state_manager_v2_cls()()
        snapshot = manager.get_item_index_state_snapshot()
        state = snapshot.get(item_id, {"has_v2_index": 0, "v2_indexed_image_num": 0})
        updated_at = datetime.now()
        async with SessionLocal() as session:
            await Items.update_v2_index_state(
                session=session,
                item_id=item_id,
                has_v2_index=bool(state["has_v2_index"]),
                v2_indexed_image_num=state["v2_indexed_image_num"],
                updated_at=updated_at,
            )
            await session.commit()
