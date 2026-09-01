from __future__ import annotations

import io
from typing import Any

from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
    get_inquiry_semantic_index_service,
)


SearchHistoryListReq: Any = None

def _runtime():
    from csrcqsf.modules.railway_parts.services import parts_search_service

    return parts_search_service


async def list_v2_search_history(cls, req: SearchHistoryListReq, runtime=None): # type: ignore
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        page_result = await runtime.SearchHistoryRepository.list_search_history(
            session=session,
            history_model=runtime.SearchHistory,
            page=req.page,
            per_page=req.per_page,
            search_type=req.search_type,
            search_equipment=req.search_equipment,
            keyword=req.keyword,
            status=req.status,
            date_from=req.date_from,
            date_to=req.date_to,
        )
        await cls._enrich_search_history_result_item_names(session, page_result.data)
        latest_ticket_map = await runtime.SearchHistoryRepository.list_latest_by_history_ids(
            session,
            [int(row.id) for row in page_result.data],
            review_ticket_model=runtime.SearchReviewTicket,
        )

    return runtime.SearchHistoryListRes(
        total=page_result.total,
        page=req.page,
        pageSize=req.per_page,
        items=[
            cls._build_search_history_item(row, latest_ticket_map.get(int(row.id)))
            for row in page_result.data
        ],
    )


async def get_v2_search_history_detail(cls, history_id: int, runtime=None):
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        row = await runtime.SearchHistoryRepository.get_history_by_id(
            session,
            history_id,
            history_model=runtime.SearchHistory,
        )
        if row is not None:
            await cls._enrich_search_history_result_item_names(session, [row])
            latest_ticket_map = await runtime.SearchHistoryRepository.list_latest_by_history_ids(
                session,
                [history_id],
                review_ticket_model=runtime.SearchReviewTicket,
            )
            latest_ticket = latest_ticket_map.get(history_id)
        else:
            latest_ticket = None

    if row is None:
        raise Exception(f"history_id={history_id} 的记录不存在")

    return cls._build_search_history_item(row, latest_ticket)


async def summary_v2_search_history(cls, runtime=None):
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        result = await runtime.SearchHistoryRepository.summarize_review_status(
            session,
            history_model=runtime.SearchHistory,
        )
        open_ticket_count = await runtime.SearchHistoryRepository.count_open_tickets(
            session,
            review_ticket_model=runtime.SearchReviewTicket,
        )

    total, pending_count, correct_count, wrong_count, user_misjudged_count = result.one()
    total = int(total or 0)
    pending_count = int(pending_count or 0)
    correct_count = int(correct_count or 0)
    wrong_count = int(wrong_count or 0)
    user_misjudged_count = int(user_misjudged_count or 0)
    open_ticket_count = int(open_ticket_count or 0)
    denominator = correct_count + wrong_count
    recognition_accuracy = (correct_count / denominator) if denominator else 0
    return runtime.SearchHistorySummaryRes(
        total=total,
        pending_count=pending_count,
        correct_count=correct_count,
        wrong_count=wrong_count,
        user_misjudged_count=user_misjudged_count,
        open_ticket_count=open_ticket_count,
        recognition_accuracy=recognition_accuracy,
    )


async def suggest_items(cls, keyword: str, limit: int = 10, runtime=None):
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        rows = await runtime.Items.suggest_items(session, keyword=keyword, limit=limit)

    return runtime.ItemSuggestRes(
        items=[
            runtime.ItemSuggestItem(
                item_id=str(row.id),
                item_code=row.item_code,
                item_name=row.item_name,
            )
            for row in rows
        ]
    )


async def delete_v2_search_history(cls, history_id_list: list[int], runtime=None):
    # 数据库先提交删除，MinIO 清理失败只记录告警，避免残留对象阻塞历史管理。
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        rows = await runtime.SearchHistoryRepository.delete_history_with_query_images(
            session,
            history_id_list,
            history_model=runtime.SearchHistory,
        )
        await session.commit()

    _, minio_instance, parse_minio_path = runtime._get_minio_helpers()
    for row in rows:
        history_id, query_image = row[0], row[1]
        query_images_json = row[2] if len(row) > 2 else None
        previous_snapshot = row[3] if len(row) > 3 else None
        delete_paths = []
        if query_image:
            delete_paths.append(query_image)
        for image_path in list(query_images_json or []):
            if image_path:
                delete_paths.append(image_path)
        for image_path in list(
            getattr(previous_snapshot, "query_images", None) or []
        ):
            if image_path:
                delete_paths.append(image_path)

        for image_path in dict.fromkeys(delete_paths):
            try:
                bucket, object_name = parse_minio_path(
                    image_path,
                    default_bucket=runtime.minio_search_history_bucket,
                )
                minio_instance.client.remove_object(bucket, object_name)
            except Exception as exc:
                runtime.logger.warning(
                    "删除检索历史查询图失败: history_id=%s, path=%s, error=%s",
                    history_id,
                    image_path,
                    exc,
                )

    return runtime.SearchHistoryDeleteRes(
        deleted_count=len(rows),
        message="检索历史删除成功",
    )


async def search_v2_by_text(
    cls,
    query_text: str,
    top_k: int = 10,
    search_equipment: str = "web",
    runtime=None,
):
    """对询码描述做文本对文本语义检索，不再使用 SigLIP 文本找图片。"""
    runtime = runtime or _runtime()
    history_id = runtime.get_id()
    semantic_service = get_inquiry_semantic_index_service()
    # 多取一批语义候选，主库中配件已删除时继续向后补足，API 的 top_k
    # 始终表示最终返回的配件数，而不是 Milvus 样本窗口大小。
    enrichment_limit = min(200, max(30, int(top_k) * 5))
    results = await semantic_service.search(
        query_text=query_text,
        top_k=enrichment_limit,
        item_ids=None,
    )

    search_items = []
    item_ids = [int(result["entity"]["item_id"]) for result in results]
    if item_ids:
        async with runtime.SessionLocal() as session:
            items = await runtime.ContextualSearchRepository.list_items_by_ids(
                session, item_ids
            )
            first_images = (
                await runtime.ContextualSearchRepository.list_first_images_by_item_ids(
                    session, item_ids
                )
            )
        item_map = {int(item.id): item for item in items}
        image_map = {int(image.item_id): image.image_url for image in first_images}
        for result in results:
            entity = result.get("entity", {})
            item_id = int(entity["item_id"])
            item = item_map.get(item_id)
            if item is None:
                continue
            search_items.append(
                runtime.SearchItem(
                    item_id=str(item.id),
                    item_code=item.item_code,
                    item_name=item.item_name,
                    image_url=image_map.get(item_id, "") or "",
                    rate=float(result.get("distance", 0) or 0),
                    matched_images=[],
                    matched_description=entity.get("description"),
                    matched_inquiry_id=(
                        str(entity["inquiry_id"])
                        if entity.get("inquiry_id") is not None
                        else None
                    ),
                )
            )
            if len(search_items) >= top_k:
                break
    await cls._persist_v2_search_history(
        history_id=history_id,
        query_text=query_text,
        query_image=None,
        query_images=None,
        search_equipment=search_equipment,
        search_items=search_items,
    )
    return runtime.SearchRes(history_id=str(history_id), data=search_items, message=None)


async def search_v2_by_image(
    cls,
    file,
    top_k: int = 10,
    search_mode: str = "hybrid",
    search_equipment: str = "web",
    runtime=None,
):
    from PIL import Image

    runtime = runtime or _runtime()
    history_id = runtime.get_id()
    upload_filename = getattr(file, "filename", "") or ""

    contents = await file.read()
    query_image = None
    try:
        query_image = await cls._upload_v2_search_query_image(
            history_id=history_id,
            filename=upload_filename,
            content_bytes=contents,
        )
    except Exception as exc:
        runtime.logger.warning(
            "保存V2检索查询图失败: filename=%s, error=%s",
            upload_filename,
            exc,
        )

    pil_image = Image.open(io.BytesIO(contents)).convert("RGB")

    manager = runtime._get_bound_milvus_manager_v2_cls()()
    results = await manager.search_by_image(
        image=pil_image,
        top_k=top_k,
        mode=search_mode,
        coarse_top_k=50,
        alpha=0.6,
    )

    search_items = []
    async with runtime.SessionLocal() as session:
        for result in results:
            item_id = result["entity"]["item_id"]
            image_url = result["entity"].get("image_url", "")
            item_name = result["entity"].get("item_name", "")
            item_code = result["entity"].get("item_code", "")

            if not item_name:
                item = await runtime.Items.get_item_by_id(session, item_id)
                if item:
                    item_name = item.item_name
                    item_code = item.item_code

            search_items.append(
                runtime.SearchItem(
                    item_id=str(item_id),
                    item_code=item_code,
                    item_name=item_name,
                    image_url=image_url,
                    rate=result["distance"],
                )
            )
    search_items = cls._aggregate_v2_search_items(search_items)
    await cls._persist_v2_search_history(
        history_id=history_id,
        query_text=None,
        query_image=query_image,
        query_images=None,
        search_equipment=search_equipment,
        search_items=search_items,
    )
    return runtime.SearchRes(history_id=str(history_id), data=search_items)


async def search_v2_by_images(
    cls,
    files: list,
    top_k: int = 10,
    search_mode: str = "hybrid",
    search_equipment: str = "web",
    runtime=None,
):
    from PIL import Image

    runtime = runtime or _runtime()
    if not files:
        raise Exception("至少上传一张图片")

    history_id = runtime.get_id()
    manager = runtime._get_bound_milvus_manager_v2_cls()()
    per_query_results: list[list[dict]] = []
    query_images: list[str] = []

    for file in files:
        upload_filename = getattr(file, "filename", "") or ""
        contents = await file.read()
        uploaded_query_image = None
        try:
            uploaded_query_image = await cls._upload_v2_search_query_image(
                history_id=history_id,
                filename=upload_filename,
                content_bytes=contents,
            )
        except Exception as exc:
            runtime.logger.warning(
                "保存V2多图检索查询图失败: filename=%s, error=%s",
                upload_filename,
                exc,
            )
        query_images.append(uploaded_query_image)

        pil_image = Image.open(io.BytesIO(contents)).convert("RGB")
        results = await manager.search_by_image(
            image=pil_image,
            top_k=top_k,
            mode=search_mode,
            coarse_top_k=50,
            alpha=0.6,
        )
        per_query_results.append(results)

    fused_hits = cls._fuse_multi_image_search_results(per_query_results)
    search_items = [cls._build_search_item_from_hit(hit) for hit in fused_hits]
    search_items = cls._aggregate_v2_search_items(search_items)
    await cls._persist_v2_search_history(
        history_id=history_id,
        query_text=None,
        query_image=None,
        query_images=query_images,
        search_equipment=search_equipment,
        search_items=search_items,
    )
    return runtime.SearchRes(history_id=str(history_id), data=search_items, message=None)


async def submit_v2_search_feedback(
    cls,
    *,
    history_id: int,
    feedback_result: str,
    remark: str | None,
    selected_item_id: str | None = None,
    runtime=None,
):
    runtime = runtime or _runtime()
    if feedback_result not in {"correct", "wrong"}:
        raise Exception("feedback_result 仅支持 correct 或 wrong")

    feedback_at = runtime.datetime.now()

    async with runtime.SessionLocal() as session:
        history = await runtime.SearchHistoryRepository.get_history_by_id(
            session,
            history_id,
            history_model=runtime.SearchHistory,
        )
        if history is None:
            raise Exception(f"history_id={history_id} 的记录不存在")

        resolved = cls._resolve_selected_feedback_candidate(
            history,
            feedback_result=feedback_result,
            selected_item_id=selected_item_id,
        )
        correct_fields = cls._resolve_feedback_correct_fields(
            history,
            feedback_result=feedback_result,
            resolved_selected=resolved,
        )

        active_ticket = await runtime.SearchHistoryRepository.get_active_by_history_id(
            session,
            history_id,
            review_ticket_model=runtime.SearchReviewTicket,
        )

        await runtime.SearchHistoryRepository.update_feedback(
            session,
            history_id,
            history_model=runtime.SearchHistory,
            verify_status=feedback_result,
            verify_remark=remark,
            verified_at=feedback_at,
            ranking_feedback_type=resolved["ranking_feedback_type"],
            selected_item_id=resolved["selected_item_id"],
            selected_item_code=resolved["selected_item_code"],
            selected_item_name=resolved["selected_item_name"],
            selected_rank=resolved["selected_rank"],
            selected_image_url=resolved["selected_image_url"],
            correct_item_id=correct_fields["correct_item_id"],
            correct_item_code=correct_fields["correct_item_code"],
            correct_item_name=correct_fields["correct_item_name"],
            correct_image_url=correct_fields["correct_image_url"],
            correct_rank=correct_fields["correct_rank"],
            correct_source=correct_fields["correct_source"],
        )

        ticket_id = None
        ticket_created = False
        if feedback_result == "wrong":
            if active_ticket is None:
                active_ticket = await runtime.SearchHistoryRepository.create_ticket(
                    session,
                    ticket_id=runtime.get_id(),
                    history_id=history_id,
                    review_ticket_model=runtime.SearchReviewTicket,
                )
                ticket_created = True
            ticket_id = active_ticket.id
        elif active_ticket is not None and getattr(active_ticket, "review_status", None) not in {"closed", "deleted"}:
            await runtime.SearchHistoryRepository.update_ticket(
                session,
                int(active_ticket.id),
                review_ticket_model=runtime.SearchReviewTicket,
                review_status="closed",
                issue_type=getattr(active_ticket, "issue_type", None),
                review_remark=getattr(active_ticket, "review_remark", None),
                resolution_remark=getattr(active_ticket, "resolution_remark", None)
                or "用户反馈改为正确，自动关闭核验单",
                review_started_at=getattr(active_ticket, "review_started_at", None),
                resolved_at=getattr(active_ticket, "resolved_at", None) or feedback_at,
                closed_at=feedback_at,
            )

        await session.commit()

    return runtime.SearchHistoryFeedbackRes(
        history_id=history_id,
        verify_status=feedback_result,
        ranking_feedback_type=resolved["ranking_feedback_type"],
        feedback_remark=remark,
        feedback_at=runtime.date_to_str(feedback_at),
        correct_item_id=(
            str(correct_fields["correct_item_id"])
            if correct_fields["correct_item_id"] is not None
            else None
        ),
        correct_item_code=correct_fields["correct_item_code"],
        correct_item_name=correct_fields["correct_item_name"],
        correct_image_url=correct_fields["correct_image_url"],
        correct_rank=correct_fields["correct_rank"],
        correct_source=correct_fields["correct_source"],
        ticket_id=ticket_id,
        ticket_created=ticket_created,
        message="用户反馈提交成功",
    )
