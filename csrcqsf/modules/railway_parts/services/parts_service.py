"""业务逻辑层 - 配件管理兼容门面。"""
# ruff: noqa: F401
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace

from anyio.to_thread import run_sync
import cv2
import numpy as np
from bfrcommon.db import async_get_count
from bfrcommon.common import date_to_str
from bfrcommon.snowflake import get_id
from sqlalchemy import select

from csrcqsf.modules.railway_parts.integrations.milvus_state_manager import (
    ImageIndex,
    MilvusManager,
)
from csrcqsf.infra.db.mdp_db import sgo_sessionLocal
from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.models.orm.item import Items, ItemsParent
from csrcqsf.models.orm.search_history import MatchedImage, SearchHistory, SearchResultItem, SearchResults, SearchReviewTicket
from csrcqsf.models.orm.sgo import SgoItemImages, SegmentedImage
from csrcqsf.models.orm.sgo_external import SgoCodeInquiryReturn
from csrcqsf.modules.railway_parts.repositories.search_history_repository import SearchHistoryRepository
from csrcqsf.modules.railway_parts.schemas.parts import (
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
    SearchReviewTicketDeleteRes,
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
from csrcqsf.modules.railway_parts.services import item_service, parts_index_service, parts_search_service
from csrcqsf.modules.railway_parts.services.segmented_image_service import SegmentedImageService
from csrcqsf.infra.external.model_client import ModelServiceError, get_model_client
from csrcqsf.modules.sgo.schemas import ImageSourceType, SegmentStatus
from csrcqsf.core.settings import minio_bucket, minio_search_history_bucket, temp_dir
from globals_vars import logger

# These names are consumed by split service modules through `_runtime_context()`.
try:
    from csrcqsf.infra.storage.minio import ensure_minio_bucket, minio_instance, parse_minio_path
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


def _bind_item_runtime():
    item_service.bind_runtime_dependencies(sys.modules[__name__])


def _bind_parts_index_runtime():
    parts_index_service.bind_runtime_dependencies(sys.modules[__name__])


def _runtime_context():
    return SimpleNamespace(**globals())


class RailwayPartsManager:
    @classmethod
    async def init(cls):
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
        _bind_item_runtime()
        return await item_service.create_item(
            cls,
            item_name=item_name,
            item_code=item_code,
            obj_url=obj_url,
            height=height,
            length=length,
            width=width,
            weight=weight,
            parent_item_id=parent_item_id,
            runtime=_runtime_context(),
        )

    @staticmethod
    def _normalize_parent_item_id(parent_item_id: int | None) -> int:
        _bind_item_runtime()
        return item_service._normalize_parent_item_id(
            parent_item_id=parent_item_id,
            runtime=_runtime_context(),
        )

    @classmethod
    async def delete_pic(cls, image_id: int):
        _bind_item_runtime()
        return await item_service.delete_pic(cls, image_id=image_id, runtime=_runtime_context())

    @classmethod
    async def delete_item_image(
        cls,
        item_id: int,
        image_id: int,
        delete_reason: str | None = None,
    ):
        _bind_item_runtime()
        return await item_service.delete_item_image(
            cls,
            item_id=item_id,
            image_id=image_id,
            delete_reason=delete_reason,
            runtime=_runtime_context(),
        )

    @classmethod
    async def delete_item(cls, item_id_list: list[int]):
        _bind_item_runtime()
        return await item_service.delete_item(
            cls,
            item_id_list=item_id_list,
            runtime=_runtime_context(),
        )

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
        _bind_item_runtime()
        return await item_service.update_item(
            cls,
            item_id=item_id,
            update_fields=update_fields,
            item_name=item_name,
            item_code=item_code,
            parent_item_id=parent_item_id,
            length=length,
            width=width,
            height=height,
            weight=weight,
            runtime=_runtime_context(),
        )

    @classmethod
    async def list_item(cls, req: ListItemReq):
        _bind_item_runtime()
        return await item_service.list_item(cls, req=req, runtime=_runtime_context())

    @classmethod
    async def list_item_images(cls, item_id_list: list[int]):
        _bind_item_runtime()
        return await item_service.list_item_images(
            cls,
            item_id_list=item_id_list,
            runtime=_runtime_context(),
        )

    @classmethod
    async def delete_item_image_index(cls, item_id: int, image_url_list: list[str]):
        _bind_parts_index_runtime()
        return await parts_index_service.delete_item_image_index(
            cls,
            item_id=item_id,
            image_url_list=image_url_list,
            runtime=_runtime_context(),
        )

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
        return parts_search_service._aggregate_v2_search_items(cls, search_items=search_items)

    @classmethod
    def _build_search_item_from_hit(cls, hit: dict) -> SearchItem:
        _bind_parts_search_runtime()
        return parts_search_service._build_search_item_from_hit(cls, hit=hit)

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
        return parts_search_service._get_search_result_candidates(cls, history=history)

    @classmethod
    def _resolve_correct_result_from_history(cls, row) -> dict:
        _bind_parts_search_runtime()
        return parts_search_service._resolve_correct_result_from_history(cls, row=row)

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
        return parts_search_service._build_search_review_ticket_item(cls, row=row)

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
        return await parts_search_service.list_v2_search_history(cls, req=req)

    @classmethod
    async def get_v2_search_history_detail(cls, history_id: int):
        _bind_parts_search_runtime()
        return await parts_search_service.get_v2_search_history_detail(cls, history_id=history_id)

    @classmethod
    async def summary_v2_search_history(cls):
        _bind_parts_search_runtime()
        return await parts_search_service.summary_v2_search_history(cls)

    @classmethod
    async def list_v2_search_review_tickets(cls, req: SearchReviewTicketListReq):
        _bind_parts_search_runtime()
        return await parts_search_service.list_v2_search_review_tickets(cls, req=req)

    @classmethod
    async def get_v2_search_review_ticket_detail(cls, ticket_id: int):
        _bind_parts_search_runtime()
        return await parts_search_service.get_v2_search_review_ticket_detail(cls, ticket_id=ticket_id)

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
    async def delete_v2_search_review_ticket(
        cls,
        *,
        ticket_id_list: list[int],
        delete_remark: str | None = None,
    ):
        _bind_parts_search_runtime()
        return await parts_search_service.delete_v2_search_review_ticket(
            cls,
            ticket_id_list=ticket_id_list,
            delete_remark=delete_remark,
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
        return await parts_search_service.suggest_items(cls, keyword=keyword, limit=limit)

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
        _bind_item_runtime()
        return await item_service.update_item_size(
            cls,
            item_id=item_id,
            item_size_str=item_size_str,
            runtime=_runtime_context(),
        )

    @classmethod
    async def get_item_detail(cls, item_id: int):
        _bind_item_runtime()
        return await item_service.get_item_detail(cls, item_id=item_id, runtime=_runtime_context())

    @classmethod
    async def create_item_image(cls, item_id: int, image_url_list: list[str]):
        _bind_item_runtime()
        return await item_service.create_item_image(
            cls,
            item_id=item_id,
            image_url_list=image_url_list,
            runtime=_runtime_context(),
        )

    @classmethod
    def _safe_upload_filename(cls, filename: str | None, fallback: str = "image.bin") -> str:
        _bind_item_runtime()
        return item_service._safe_upload_filename(
            filename=filename,
            fallback=fallback,
            runtime=_runtime_context(),
        )

    @classmethod
    async def _delete_minio_object(cls, object_path: str) -> None:
        _bind_item_runtime()
        return await item_service._delete_minio_object(
            object_path=object_path,
            runtime=_runtime_context(),
        )

    @classmethod
    async def create_item_image_files(cls, item_id: int, files: list) -> dict:
        _bind_item_runtime()
        return await item_service.create_item_image_files(
            cls,
            item_id=item_id,
            files=files,
            runtime=_runtime_context(),
        )

    @classmethod
    async def get_image_from_oss(cls, image_url: str):
        _bind_item_runtime()
        return await item_service.get_image_from_oss(
            cls,
            image_url=image_url,
            runtime=_runtime_context(),
        )

    @classmethod
    def resize_image(cls, image, max_size=1920):
        _bind_item_runtime()
        return item_service.resize_image(
            cls,
            image=image,
            max_size=max_size,
            runtime=_runtime_context(),
        )

    @classmethod
    async def statistics(cls):
        _bind_parts_index_runtime()
        return await parts_index_service.statistics(cls, runtime=_runtime_context())

    @classmethod
    def reciprocal_rank_fusion(search_results_list, k=60):
        fused_scores = {}
        for result_list in search_results_list:
            for rank, hit in enumerate(result_list, start=1):
                doc_id = hit.id
                fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + 1 / (rank + k)
        return sorted(fused_scores.items(), key=lambda value: value[1], reverse=True)

    @classmethod
    async def create_v2_collections(cls, drop_existing: bool = False):
        _bind_parts_index_runtime()
        return await parts_index_service.create_v2_collections(
            cls,
            drop_existing=drop_existing,
            runtime=_runtime_context(),
        )

    @classmethod
    async def rebuild_v2_index(
        cls,
        item_id: int = None,
        limit: int = None,
        rebuild_existing: bool = False,
        progress_callback=None,
        resume_after_created_at=None,
        resume_after_item_id: int = None,
        initial_completed_item_count: int = 0,
        initial_success_count: int = 0,
        initial_fail_count: int = 0,
        initial_segmented_count: int = 0,
        initial_fallback_count: int = 0,
        total_items_override: int = None,
    ):
        _bind_parts_index_runtime()
        return await parts_index_service.rebuild_v2_index(
            cls,
            item_id=item_id,
            limit=limit,
            rebuild_existing=rebuild_existing,
            progress_callback=progress_callback,
            resume_after_created_at=resume_after_created_at,
            resume_after_item_id=resume_after_item_id,
            initial_completed_item_count=initial_completed_item_count,
            initial_success_count=initial_success_count,
            initial_fail_count=initial_fail_count,
            initial_segmented_count=initial_segmented_count,
            initial_fallback_count=initial_fallback_count,
            total_items_override=total_items_override,
            runtime=_runtime_context(),
        )

    @classmethod
    async def delete_v2_index(cls, item_id: int) -> dict:
        _bind_parts_index_runtime()
        return await parts_index_service.delete_v2_index(
            cls,
            item_id=item_id,
            runtime=_runtime_context(),
        )

    @classmethod
    async def sync_all_v2_index_state(cls) -> dict:
        _bind_parts_index_runtime()
        return await parts_index_service.sync_all_v2_index_state(
            cls,
            runtime=_runtime_context(),
        )

    @classmethod
    async def sync_item_v2_index_state(cls, item_id: int, state_manager=None):
        _bind_parts_index_runtime()
        return await parts_index_service.sync_item_v2_index_state(
            cls,
            item_id=item_id,
            state_manager=state_manager,
            runtime=_runtime_context(),
        )
