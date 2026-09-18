"""配件 V2 检索、历史记录、反馈和复核工单业务。"""
from __future__ import annotations

from datetime import datetime
import io
import re
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any, TypeAlias
from csrcqsf.modules.railway_parts.services import review_ticket_service, search_service
from csrcqsf.modules.railway_parts.utils.assets import asset_url_from_internal_path

if TYPE_CHECKING:
    from csrcqsf.modules.railway_parts.schemas.search import SearchItem as SearchItemType
else:
    SearchItemType: TypeAlias = Any

# 依赖由 parts_service 兼容门面注入，拆分实现仍支持原有测试替换和调用入口。
SessionLocal: Any = None
Items: Any = None
MatchedImage: Any = None
MilvusManagerV2: Any = None
SearchHistory: Any = None
SearchResultItem: Any = None
SearchResults: Any = None
SearchReviewTicket: Any = None
SearchHistoryRepository: Any = None
ContextualSearchRepository: Any = None
ItemSuggestItem: Any = None
ItemSuggestRes: Any = None
SearchReviewTicketDeleteRes: Any = None
SearchReviewTicketDetailRes: Any = None
SearchReviewTicketItem: Any = None
SearchReviewTicketListRes: Any = None
SearchReviewTicketSummaryRes: Any = None
SearchReviewTicketUpdateRes: Any = None
SearchHistoryDeleteRes: Any = None
SearchHistoryFeedbackRes: Any = None
SearchHistoryListItem: Any = None
SearchHistoryListReq: Any = None
SearchHistoryListRes: Any = None
SearchHistorySummaryRes: Any = None
SearchHistoryVerifyRes: Any = None
SearchItem: Any = None
SearchRes: Any = None
SearchReviewTicketListReq: Any = None
SgoItemImages: Any = None
date_to_str: Any = None
logger: Any = None
get_id: Any = None
run_sync: Any = None
select: Any = None
_get_milvus_manager_v2_cls: Any = None
_get_minio_helpers: Any = None
minio_search_history_bucket: Any = None


def bind_runtime_dependencies(parts_service_module: ModuleType | None = None) -> None:
    """绑定兼容门面中的数据库、模型和外部存储依赖。"""
    if parts_service_module is None:
        from csrcqsf.modules.railway_parts.services import parts_service as parts_service_module

    globals().update(
        {
            "datetime": parts_service_module.datetime,
            "SessionLocal": parts_service_module.SessionLocal,
            "Items": parts_service_module.Items,
            "MatchedImage": parts_service_module.MatchedImage,
            "MilvusManagerV2": getattr(parts_service_module, "MilvusManagerV2", None),
            "SearchHistory": parts_service_module.SearchHistory,
            "SearchResultItem": parts_service_module.SearchResultItem,
            "SearchResults": parts_service_module.SearchResults,
            "SearchReviewTicket": parts_service_module.SearchReviewTicket,
            "SearchHistoryRepository": parts_service_module.SearchHistoryRepository,
            "ContextualSearchRepository": parts_service_module.ContextualSearchRepository,
            "ItemSuggestItem": parts_service_module.ItemSuggestItem,
            "ItemSuggestRes": parts_service_module.ItemSuggestRes,
            "SearchReviewTicketDeleteRes": parts_service_module.SearchReviewTicketDeleteRes,
            "SearchReviewTicketDetailRes": parts_service_module.SearchReviewTicketDetailRes,
            "SearchReviewTicketItem": parts_service_module.SearchReviewTicketItem,
            "SearchReviewTicketListRes": parts_service_module.SearchReviewTicketListRes,
            "SearchReviewTicketSummaryRes": parts_service_module.SearchReviewTicketSummaryRes,
            "SearchReviewTicketUpdateRes": parts_service_module.SearchReviewTicketUpdateRes,
            "SearchHistoryDeleteRes": parts_service_module.SearchHistoryDeleteRes,
            "SearchHistoryFeedbackRes": parts_service_module.SearchHistoryFeedbackRes,
            "SearchHistoryListItem": parts_service_module.SearchHistoryListItem,
            "SearchHistoryListRes": parts_service_module.SearchHistoryListRes,
            "SearchHistorySummaryRes": parts_service_module.SearchHistorySummaryRes,
            "SearchHistoryVerifyRes": parts_service_module.SearchHistoryVerifyRes,
            "SearchItem": parts_service_module.SearchItem,
            "SearchRes": parts_service_module.SearchRes,
            "SgoItemImages": parts_service_module.SgoItemImages,
            "date_to_str": parts_service_module.date_to_str,
            "logger": parts_service_module.logger,
            "get_id": parts_service_module.get_id,
            "run_sync": parts_service_module.run_sync,
            "select": parts_service_module.select,
            "_get_milvus_manager_v2_cls": parts_service_module._get_milvus_manager_v2_cls,
            "_get_minio_helpers": parts_service_module._get_minio_helpers,
            "minio_search_history_bucket": parts_service_module.minio_search_history_bucket,
        }
    )


def _get_bound_milvus_manager_v2_cls():
    manager_cls = globals().get("MilvusManagerV2")
    if manager_cls is not None:
        return manager_cls
    return _get_milvus_manager_v2_cls()


def _runtime_context():
    return SimpleNamespace(**globals())


async def _upload_v2_search_query_image(
    cls,
    history_id: int,
    filename: str,
    content_bytes: bytes,
) -> str:
    # 查询原图按历史 ID 独立保存，支持关闭弹窗后在历史详情中复现检索输入。
    ensure_minio_bucket, minio_instance, _ = _get_minio_helpers()
    ensure_minio_bucket(minio_search_history_bucket)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", (filename or "query.jpg").strip())
    if not safe_name:
        safe_name = "query.jpg"

    date_prefix = datetime.now().strftime("%Y%m%d")
    object_name = f"query-images/{date_prefix}/{history_id}_{safe_name}"
    await run_sync(
        minio_instance.client.put_object,
        minio_search_history_bucket,
        object_name,
        io.BytesIO(content_bytes),
        len(content_bytes),
    )
    return f"{minio_search_history_bucket}/{object_name}"


async def _persist_v2_search_history(
    cls,
    *,
    history_id: int,
    query_text: str | None,
    query_image: str | None,
    query_images: list[str] | None,
    search_equipment: str,
    search_items: list[SearchItemType],
) -> None:
    """保存完整候选快照；历史写入失败不反向中断已完成的检索响应。"""
    top1 = search_items[0] if search_items else None
    search_results = SearchResults(
        items=[
            SearchResultItem(
                item_id=str(item.item_id),
                item_code=item.item_code,
                item_name=item.item_name,
                similar=item.rate,
                image_url=item.image_url,
                matched_images=[
                    MatchedImage(
                        image_url=matched.image_url,
                        rate=matched.rate,
                        matched_query_indexes=list(
                            getattr(matched, "matched_query_indexes", []) or []
                        ),
                    )
                    for matched in item.matched_images
                ],
                matched_description=getattr(item, "matched_description", None),
                matched_inquiry_id=getattr(item, "matched_inquiry_id", None),
            )
            for item in search_items
        ]
    )

    try:
        async with SessionLocal() as session:
            session.add(
                SearchHistory(
                    id=history_id,
                    inquery_id=None,
                    inquery_num=None,
                    search_result_item_name=top1.item_name if top1 else None,
                    search_result_item_code=top1.item_code if top1 else "",
                    search_parameter=None,
                    query_text=query_text,
                    query_image=query_image,
                    query_images_json=query_images or None,
                    search_equipment=search_equipment,
                    verify_status="pending",
                    verify_remark=None,
                    verified_at=None,
                    correct_item_name=None,
                    correct_item_code=None,
                    search_results=search_results,
                )
            )
            await session.commit()
    except Exception:
        logger.exception("V2检索历史写入失败")


def _aggregate_v2_search_items(
    cls,
    search_items: list[SearchItemType],
) -> list[SearchItemType]:
    # 向量命中以图片为单位，接口响应按配件聚合并保留每张命中图片及分数。
    grouped: dict[str, dict] = {}

    for index, item in enumerate(search_items):
        base_matched = item.matched_images[0] if item.matched_images else None
        bucket = grouped.setdefault(
            str(item.item_id),
            {
                "best_item": item,
                "first_index": index,
                "matched_images": [],
            },
        )
        bucket["matched_images"].append(
            (
                index,
                MatchedImage(
                    image_url=item.image_url,
                    rate=item.rate,
                    matched_query_indexes=list(
                        getattr(base_matched, "matched_query_indexes", []) or []
                    ),
                ),
            )
        )
        if item.rate > bucket["best_item"].rate:
            bucket["best_item"] = item

    aggregated_items: list[SearchItemType] = []
    for item_id, bucket in grouped.items():
        best_item = bucket["best_item"]
        matched_images = [
            image
            for _, image in sorted(
                bucket["matched_images"],
                key=lambda pair: (-pair[1].rate, pair[0]),
            )
        ]
        aggregated_items.append(
            SearchItem(
                item_id=str(item_id),
                item_code=best_item.item_code,
                item_name=best_item.item_name,
                image_url=best_item.image_url,
                rate=best_item.rate,
                matched_images=matched_images,
                matched_description=getattr(best_item, "matched_description", None),
                matched_inquiry_id=getattr(best_item, "matched_inquiry_id", None),
            )
        )

    aggregated_items.sort(
        key=lambda item: (-item.rate, grouped[str(item.item_id)]["first_index"])
    )
    return aggregated_items


def _build_search_item_from_hit(cls, hit: dict) -> SearchItemType:
    entity = hit.get("entity", {})
    rate = float(hit.get("best_similarity", hit.get("distance", 0)) or 0)
    image_url = entity.get("image_url", "")
    matched_query_indexes = list(hit.get("matched_query_indexes", []) or [])
    return SearchItem(
        item_id=str(entity.get("item_id", "")),
        item_code=entity.get("item_code", "") or "",
        item_name=entity.get("item_name", "") or "",
        image_url=image_url,
        rate=rate,
        matched_images=[
            MatchedImage(
                image_url=image_url,
                rate=rate,
                matched_query_indexes=matched_query_indexes,
            )
        ],
    )

def _fuse_multi_image_search_results(cls, per_query_results: list[list[dict]], rrf_k: int = 60) -> list[dict]:
    # 多张查询图按图片 ID 做 RRF，兼顾各视角名次并记录由哪些查询图命中。
    fused_by_image_id: dict[int, dict] = {}
    next_order = 0

    for query_index, result_list in enumerate(per_query_results):
        for rank, hit in enumerate(result_list, start=1):
            entity = hit.get("entity", {})
            image_id = entity.get("image_id")
            if image_id is None:
                continue
            image_id = int(image_id)
            bucket = fused_by_image_id.get(image_id)
            if bucket is None:
                bucket = {
                    "entity": dict(entity),
                    "distance": float(hit.get("distance", 0) or 0),
                    "best_similarity": float(hit.get("distance", 0) or 0),
                    "rrf_score": 0.0,
                    "matched_query_indexes": set(),
                    "first_seen_order": next_order,
                }
                fused_by_image_id[image_id] = bucket
                next_order += 1

            similarity = float(hit.get("distance", 0) or 0)
            if similarity > bucket["best_similarity"]:
                bucket["best_similarity"] = similarity
                bucket["distance"] = similarity
                bucket["entity"] = dict(entity)

            bucket["rrf_score"] += 1 / (rank + rrf_k)
            bucket["matched_query_indexes"].add(query_index)

    fused_results = [
        {
            "entity": bucket["entity"],
            "distance": bucket["distance"],
            "best_similarity": bucket["best_similarity"],
            "rrf_score": bucket["rrf_score"],
            "matched_query_indexes": sorted(bucket["matched_query_indexes"]),
            "first_seen_order": bucket["first_seen_order"],
        }
        for bucket in fused_by_image_id.values()
    ]
    fused_results.sort(
        key=lambda item: (
            -item["rrf_score"],
            -item["best_similarity"],
            item["first_seen_order"],
        )
    )
    return fused_results

def _normalize_review_status(
    cls,
    status: str | None,
    latest_review_status: str | None = None,
) -> str:
    # 错误结果在复核工单闭环前仍对用户显示待处理，避免提前视为已纠正。
    if status in {"correct", "user_misjudged"}:
        return "correct"
    if status == "wrong" and latest_review_status in {"resolved", "closed"}:
        return "wrong"
    return "pending"

def _get_search_result_candidates(cls, history) -> list[SearchResultItem]:
    search_results = getattr(history, "search_results", None)
    if search_results is None:
        return []
    return list(search_results.items or [])

def _resolve_correct_result_from_history(cls, row) -> dict:
    correct_item_id = getattr(row, "correct_item_id", None)
    return {
        "correct_item_id": str(correct_item_id) if correct_item_id is not None else None,
        "correct_item_code": getattr(row, "correct_item_code", None),
        "correct_item_name": getattr(row, "correct_item_name", None),
        "correct_image_url": asset_url_from_internal_path(getattr(row, "correct_image_url", None)),
        "correct_rank": getattr(row, "correct_rank", None),
        "correct_source": getattr(row, "correct_source", None) or "none",
    }

def _resolve_feedback_correct_fields(
    cls,
    history,
    *,
    feedback_result: str,
    resolved_selected: dict,
) -> dict:
    # 用户反馈错误时不覆盖已由人工复核确认的正确配件。
    if feedback_result == "correct":
        return {
            "correct_item_id": resolved_selected["selected_item_id"],
            "correct_item_code": resolved_selected["selected_item_code"],
            "correct_item_name": resolved_selected["selected_item_name"],
            "correct_image_url": resolved_selected["selected_image_url"],
            "correct_rank": resolved_selected["selected_rank"],
            "correct_source": "user_selected",
        }

    if getattr(history, "correct_source", None) == "review_resolved":
        return {
            "correct_item_id": getattr(history, "correct_item_id", None),
            "correct_item_code": getattr(history, "correct_item_code", None),
            "correct_item_name": getattr(history, "correct_item_name", None),
            "correct_image_url": getattr(history, "correct_image_url", None),
            "correct_rank": getattr(history, "correct_rank", None),
            "correct_source": "review_resolved",
        }

    return {
        "correct_item_id": None,
        "correct_item_code": None,
        "correct_item_name": None,
        "correct_image_url": None,
        "correct_rank": None,
        "correct_source": "none",
    }

def _match_correct_item_in_history_results(
    cls,
    history,
    *,
    item_id: int | None = None,
    item_code: str | None = None,
):
    for index, candidate in enumerate(cls._get_search_result_candidates(history), start=1):
        if item_id is not None and str(candidate.item_id) == str(item_id):
            return candidate, index
        if item_code is not None and candidate.item_code == item_code:
            return candidate, index
    return None, None

async def _resolve_correct_image_url(
    cls,
    session,
    *,
    item_id: int,
    history=None,
    item_code: str | None = None,
):
    # 优先复用当次候选图；候选外正确项再回退到配件第一张有效图片。
    candidate, rank = cls._match_correct_item_in_history_results(
        history,
        item_id=item_id,
        item_code=item_code,
    )
    if candidate is not None:
        return candidate.image_url, rank

    first_image = await SgoItemImages.get_first_image_by_item_id(session, item_id)
    return (first_image.image_url if first_image else None), None

async def _resolve_system_top1_correct_fields(cls, session, history) -> dict:
    correct_item_code = getattr(history, "search_result_item_code", None)
    correct_item_name = getattr(history, "search_result_item_name", None)
    if not correct_item_code:
        raise Exception("当前记录没有系统推荐结果，无法标记为用户误判")

    correct_item_id = None
    correct_image_url = None
    correct_rank = None

    matched_candidate, matched_rank = cls._match_correct_item_in_history_results(
        history,
        item_code=correct_item_code,
    )
    if matched_candidate is not None:
        correct_item_id = int(matched_candidate.item_id)
        correct_item_name = correct_item_name or matched_candidate.item_name
        correct_image_url = matched_candidate.image_url
        correct_rank = matched_rank
    else:
        item = await Items.get_item_by_item_code(session, correct_item_code)
        if item is not None:
            correct_item_id = int(item.id)
            correct_item_name = correct_item_name or item.item_name
            correct_image_url, correct_rank = await cls._resolve_correct_image_url(
                session,
                item_id=correct_item_id,
                history=history,
                item_code=correct_item_code,
            )

    return {
        "correct_item_id": correct_item_id,
        "correct_item_code": correct_item_code,
        "correct_item_name": correct_item_name,
        "correct_image_url": correct_image_url,
        "correct_rank": correct_rank,
        "correct_source": "review_resolved",
    }

def _resolve_selected_feedback_candidate(
    cls,
    history,
    *,
    feedback_result: str,
    selected_item_id: str | None,
) -> dict:
    # correct 必须指向当次候选，防止反馈记录引用无法复现的外部配件。
    if feedback_result == "wrong":
        return {
            "ranking_feedback_type": "no_correct_match",
            "selected_item_id": None,
            "selected_item_code": None,
            "selected_item_name": None,
            "selected_rank": None,
            "selected_image_url": None,
        }

    candidates = cls._get_search_result_candidates(history)
    if not candidates:
        raise Exception("当前检索结果为空，无法提交 correct 排序反馈")

    rank = 1
    candidate = candidates[0]
    if selected_item_id is not None:
        matched_candidate = None
        for index, row in enumerate(candidates, start=1):
            if str(row.item_id) == str(selected_item_id):
                matched_candidate = row
                rank = index
                break
        if matched_candidate is None:
            raise Exception(f"selected_item_id={selected_item_id} 不在该次检索候选结果中")
        candidate = matched_candidate

    resolved_item_id = str(candidate.item_id)
    resolved_item_code = candidate.item_code
    resolved_item_name = candidate.item_name
    resolved_image_url = candidate.image_url

    return {
        "ranking_feedback_type": "top1_correct" if rank == 1 else "topk_correct",
        "selected_item_id": int(resolved_item_id),
        "selected_item_code": resolved_item_code,
        "selected_item_name": resolved_item_name,
        "selected_rank": rank,
        "selected_image_url": resolved_image_url,
    }

def _build_search_history_item(cls, row, latest_ticket=None):
    query_images = [
        asset_url_from_internal_path(image_path) or image_path
        for image_path in list(getattr(row, "query_images_json", None) or [])
    ]
    if row.query_image or query_images:
        search_type = "image"
    elif row.query_text:
        search_type = "text"
    else:
        search_type = "unknown"

    has_open_review_ticket = False
    latest_ticket_id = None
    latest_review_status = None
    latest_issue_type = None
    if latest_ticket is not None:
        has_open_review_ticket = getattr(latest_ticket, "review_status", None) not in {"closed", "deleted"}
        latest_ticket_id = getattr(latest_ticket, "id", None)
        latest_review_status = getattr(latest_ticket, "review_status", None)
        latest_issue_type = getattr(latest_ticket, "issue_type", None)

    correct_fields = cls._resolve_correct_result_from_history(row)
    previous_snapshot = getattr(row, "previous_search_snapshot", None)
    previous_query_images = []
    previous_search_parameter = None
    previous_result = None
    previous_searched_at = None
    if previous_snapshot is not None:
        previous_query_images = [
            asset_url_from_internal_path(image_path) or image_path
            for image_path in list(previous_snapshot.query_images or [])
        ]
        previous_search_parameter = previous_snapshot.parameters
        previous_result = previous_snapshot.results
        previous_searched_at = date_to_str(previous_snapshot.searched_at)

    return SearchHistoryListItem(
        history_id=row.id,
        search_type=search_type,
        time_created=date_to_str(row.time_created),
        query_text=row.query_text,
        query_image=asset_url_from_internal_path(row.query_image) or row.query_image,
        query_images=query_images,
        search_parameter=getattr(row, "search_parameter", None),
        previous_query_images=previous_query_images,
        previous_search_parameter=previous_search_parameter,
        previous_result=previous_result,
        previous_searched_at=previous_searched_at,
        search_revision=int(getattr(row, "search_revision", 0) or 0),
        search_equipment=getattr(row, "search_equipment", None),
        status=cls._normalize_review_status(
            getattr(row, "verify_status", None),
            latest_review_status,
        ),
        result=row.search_results,
        inquery_id=row.inquery_id,
        inquery_num=row.inquery_num,
        search_item_name=row.search_result_item_name,
        search_item_code=row.search_result_item_code,
        ranking_feedback_type=getattr(row, "ranking_feedback_type", None),
        feedback_remark=getattr(row, "verify_remark", None),
        feedback_at=date_to_str(row.verified_at) if getattr(row, "verified_at", None) else None,
        verify_remark=getattr(row, "verify_remark", None),
        verified_at=date_to_str(row.verified_at) if getattr(row, "verified_at", None) else None,
        has_open_review_ticket=has_open_review_ticket,
        latest_ticket_id=str(latest_ticket_id) if latest_ticket_id is not None else None,
        latest_review_status=latest_review_status,
        latest_issue_type=latest_issue_type,
        **correct_fields,
    )

def _build_search_review_ticket_item(cls, row):
    return SearchReviewTicketItem(
        ticket_id=row.id,
        history_id=row.history_id,
        review_status=row.review_status,
        issue_type=row.issue_type,
        time_created=date_to_str(row.time_created),
        time_updated=date_to_str(row.time_updated),
        search_type=getattr(row, "search_type", None),
        query_text=getattr(row, "query_text", None),
        query_image=asset_url_from_internal_path(getattr(row, "query_image", None)) or getattr(row, "query_image", None),
        query_images=[
            asset_url_from_internal_path(image_path) or image_path
            for image_path in list(getattr(row, "query_images_json", None) or [])
        ],
        search_equipment=getattr(row, "search_equipment", None),
        search_item_name=getattr(row, "search_result_item_name", None),
        search_item_code=getattr(row, "search_result_item_code", None),
        feedback_remark=getattr(row, "verify_remark", None),
        correct_item_id=getattr(row, "correct_item_id", None),
        correct_item_name=getattr(row, "correct_item_name", None),
        correct_item_code=getattr(row, "correct_item_code", None),
        correct_image_url=asset_url_from_internal_path(getattr(row, "correct_image_url", None)) or getattr(row, "correct_image_url", None),
        correct_rank=getattr(row, "correct_rank", None),
        correct_source=getattr(row, "correct_source", None) or "none",
    )

def _build_search_review_ticket_detail(cls, ticket, history):
    query_images = [
        asset_url_from_internal_path(image_path) or image_path
        for image_path in list(getattr(history, "query_images_json", None) or [])
    ]
    if getattr(history, "query_image", None) or query_images:
        search_type = "image"
    elif getattr(history, "query_text", None):
        search_type = "text"
    else:
        search_type = "unknown"

    return SearchReviewTicketDetailRes(
        ticket_id=ticket.id,
        history_id=ticket.history_id,
        review_status=ticket.review_status,
        issue_type=ticket.issue_type,
        time_created=date_to_str(ticket.time_created) if getattr(ticket, "time_created", None) else None,
        time_updated=date_to_str(ticket.time_updated) if getattr(ticket, "time_updated", None) else None,
        review_remark=ticket.review_remark,
        resolution_remark=ticket.resolution_remark,
        review_started_at=date_to_str(ticket.review_started_at) if ticket.review_started_at else None,
        resolved_at=date_to_str(ticket.resolved_at) if ticket.resolved_at else None,
        closed_at=date_to_str(ticket.closed_at) if ticket.closed_at else None,
        search_type=search_type,
        query_text=getattr(history, "query_text", None),
        query_image=asset_url_from_internal_path(getattr(history, "query_image", None)) or getattr(history, "query_image", None),
        query_images=query_images,
        search_equipment=getattr(history, "search_equipment", None),
        result=getattr(history, "search_results", None),
        search_item_name=getattr(history, "search_result_item_name", None),
        search_item_code=getattr(history, "search_result_item_code", None),
        feedback_remark=getattr(history, "verify_remark", None),
        correct_item_id=getattr(history, "correct_item_id", None),
        correct_item_name=getattr(history, "correct_item_name", None),
        correct_item_code=getattr(history, "correct_item_code", None),
        correct_image_url=asset_url_from_internal_path(getattr(history, "correct_image_url", None)) or getattr(history, "correct_image_url", None),
        correct_rank=getattr(history, "correct_rank", None),
        correct_source=getattr(history, "correct_source", None) or "none",
    )

async def _enrich_search_history_result_item_names(cls, session, rows) -> None:
    missing_items = []
    item_id_set = set()

    for row in rows:
        search_results = getattr(row, "search_results", None)
        if search_results is None:
            continue

        for result_item in search_results.items:
            if getattr(result_item, "item_name", None):
                continue
            try:
                item_id = int(result_item.item_id)
            except (TypeError, ValueError):
                continue
            item_id_set.add(item_id)
            missing_items.append(result_item)

    if not item_id_set:
        return

    item_name_map = {}
    async for item in Items.get_item_by_id_list(session=session, item_id_list=list(item_id_set)):
        item_name_map[int(item.id)] = item.item_name

    for result_item in missing_items:
        try:
            item_id = int(result_item.item_id)
        except (TypeError, ValueError):
            continue
        item_name = item_name_map.get(item_id)
        if item_name:
            result_item.item_name = item_name

async def list_v2_search_history(cls, req: SearchHistoryListReq):
    return await search_service.list_v2_search_history(
        cls,
        req=req,
        runtime=_runtime_context(),
    )

async def get_v2_search_history_detail(cls, history_id: int):
    return await search_service.get_v2_search_history_detail(
        cls,
        history_id=history_id,
        runtime=_runtime_context(),
    )

async def summary_v2_search_history(cls):
    return await search_service.summary_v2_search_history(
        cls,
        runtime=_runtime_context(),
    )

async def list_v2_search_review_tickets(cls, req: SearchReviewTicketListReq):
    return await review_ticket_service.list_v2_search_review_tickets(
        cls,
        req=req,
        runtime=_runtime_context(),
    )

async def get_v2_search_review_ticket_detail(cls, ticket_id: int):
    return await review_ticket_service.get_v2_search_review_ticket_detail(
        cls,
        ticket_id=ticket_id,
        runtime=_runtime_context(),
    )

async def summary_v2_search_review_ticket(cls):
    return await review_ticket_service.summary_v2_search_review_ticket(
        cls,
        runtime=_runtime_context(),
    )

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
    return await review_ticket_service.update_v2_search_review_ticket(
        cls,
        ticket_id=ticket_id,
        review_status=review_status,
        issue_type=issue_type,
        review_remark=review_remark,
        resolution_remark=resolution_remark,
        correct_item_code=correct_item_code,
        runtime=_runtime_context(),
    )

async def delete_v2_search_review_ticket(
    cls,
    *,
    ticket_id_list: list[int],
    delete_remark: str | None = None,
):
    return await review_ticket_service.delete_v2_search_review_ticket(
        cls,
        ticket_id_list=ticket_id_list,
        delete_remark=delete_remark,
        runtime=_runtime_context(),
    )

async def verify_v2_search_history(
    cls,
    *,
    history_id: int,
    verify_status: str,
    correct_item_code: str | None,
    remark: str | None,
):
    return await review_ticket_service.verify_v2_search_history(
        cls,
        history_id=history_id,
        verify_status=verify_status,
        correct_item_code=correct_item_code,
        remark=remark,
        runtime=_runtime_context(),
    )

async def suggest_items(cls, keyword: str, limit: int = 10):
    return await search_service.suggest_items(
        cls,
        keyword=keyword,
        limit=limit,
        runtime=_runtime_context(),
    )

async def delete_v2_search_history(cls, history_id_list: list[int]):
    return await search_service.delete_v2_search_history(
        cls,
        history_id_list=history_id_list,
        runtime=_runtime_context(),
    )

async def search_v2_by_text(
    cls,
    query_text: str,
    top_k: int = 10,
    search_equipment: str = "web",
    source_inquiry_id: str | None = None,
    source_inquiry_time=None,
):
    return await search_service.search_v2_by_text(
        cls,
        query_text=query_text,
        top_k=top_k,
        search_equipment=search_equipment,
        source_inquiry_id=source_inquiry_id,
        source_inquiry_time=source_inquiry_time,
        runtime=_runtime_context(),
    )

async def search_v2_by_image(
    cls,
    file,
    top_k: int = 10,
    search_mode: str = "siglip",
    search_equipment: str = "web",
):
    return await search_service.search_v2_by_image(
        cls,
        file=file,
        top_k=top_k,
        search_mode=search_mode,
        search_equipment=search_equipment,
        runtime=_runtime_context(),
    )

async def search_v2_by_images(
    cls,
    files: list,
    top_k: int = 10,
    search_mode: str = "siglip",
    search_equipment: str = "web",
):
    return await search_service.search_v2_by_images(
        cls,
        files=files,
        top_k=top_k,
        search_mode=search_mode,
        search_equipment=search_equipment,
        runtime=_runtime_context(),
    )

async def submit_v2_search_feedback(
    cls,
    *,
    history_id: int,
    feedback_result: str,
    remark: str | None,
    selected_item_id: str | None = None,
):
    return await search_service.submit_v2_search_feedback(
        cls,
        history_id=history_id,
        feedback_result=feedback_result,
        remark=remark,
        selected_item_id=selected_item_id,
        runtime=_runtime_context(),
    )
