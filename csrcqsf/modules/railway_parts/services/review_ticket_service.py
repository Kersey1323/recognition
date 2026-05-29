from __future__ import annotations


def _runtime():
    from csrcqsf.modules.railway_parts.services import parts_search_service

    return parts_search_service


async def list_v2_search_review_tickets(cls, req: SearchReviewTicketListReq, runtime=None):
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        page_result = await runtime.SearchHistoryRepository.list_tickets(
            session,
            review_ticket_model=runtime.SearchReviewTicket,
            page=req.page,
            per_page=req.per_page,
            review_status=req.review_status,
            issue_type=req.issue_type,
            search_equipment=req.search_equipment,
            keyword=req.keyword,
            date_from=req.date_from,
            date_to=req.date_to,
        )

    return runtime.SearchReviewTicketListRes(
        total=page_result.total,
        page=req.page,
        pageSize=req.per_page,
        items=[cls._build_search_review_ticket_item(row) for row in page_result.data],
    )


async def get_v2_search_review_ticket_detail(cls, ticket_id: int, runtime=None):
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        ticket = await runtime.SearchHistoryRepository.get_ticket_by_id(
            session,
            ticket_id,
            review_ticket_model=runtime.SearchReviewTicket,
        )
        if ticket is None:
            raise Exception(f"ticket_id={ticket_id} 的记录不存在")

        history = await runtime.SearchHistoryRepository.get_history_by_id(
            session,
            int(ticket.history_id),
            history_model=runtime.SearchHistory,
        )
        if history is None:
            raise Exception(f"history_id={ticket.history_id} 的记录不存在")

        await cls._enrich_search_history_result_item_names(session, [history])

    return cls._build_search_review_ticket_detail(ticket, history)


async def summary_v2_search_review_ticket(cls, runtime=None):
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        result = await runtime.SearchHistoryRepository.summarize_tickets(
            session,
            review_ticket_model=runtime.SearchReviewTicket,
        )

    (
        total,
        open_count,
        reviewing_count,
        resolved_count,
        closed_count,
        missing_index_count,
        precision_issue_count,
        system_bug_count,
        user_misjudged_count,
    ) = result.one()
    return runtime.SearchReviewTicketSummaryRes(
        total=int(total or 0),
        open_count=int(open_count or 0),
        reviewing_count=int(reviewing_count or 0),
        resolved_count=int(resolved_count or 0),
        closed_count=int(closed_count or 0),
        missing_index_count=int(missing_index_count or 0),
        precision_issue_count=int(precision_issue_count or 0),
        system_bug_count=int(system_bug_count or 0),
        user_misjudged_count=int(user_misjudged_count or 0),
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
    runtime=None,
):
    runtime = runtime or _runtime()
    allowed_review_status = {"reviewing", "resolved", "closed"}
    allowed_issue_types = {
        None,
        "missing_index",
        "precision_issue",
        "system_bug",
        "user_misjudged",
    }
    if review_status not in allowed_review_status:
        raise Exception(f"review_status={review_status} 不支持")
    if issue_type not in allowed_issue_types:
        raise Exception(f"issue_type={issue_type} 不支持")

    now = runtime.datetime.now()
    resolved_verify_status = "user_misjudged" if issue_type == "user_misjudged" else None
    correct_item_id = None
    correct_item_name = None
    correct_image_url = None
    correct_rank = None
    correct_source = None

    async with runtime.SessionLocal() as session:
        ticket = await runtime.SearchHistoryRepository.get_ticket_by_id(
            session,
            ticket_id,
            review_ticket_model=runtime.SearchReviewTicket,
        )
        if ticket is None:
            raise Exception(f"ticket_id={ticket_id} 的记录不存在")

        history = await runtime.SearchHistoryRepository.get_history_by_id(
            session,
            int(ticket.history_id),
            history_model=runtime.SearchHistory,
        )
        if history is None:
            raise Exception(f"history_id={ticket.history_id} 的记录不存在")

        if review_status == "resolved" and resolved_verify_status == "user_misjudged":
            correct_fields = await cls._resolve_system_top1_correct_fields(session, history)
            correct_item_id = correct_fields["correct_item_id"]
            correct_item_code = correct_fields["correct_item_code"]
            correct_item_name = correct_fields["correct_item_name"]
            correct_image_url = correct_fields["correct_image_url"]
            correct_rank = correct_fields["correct_rank"]
            correct_source = correct_fields["correct_source"]
            await runtime.SearchHistoryRepository.update_review_result(
                session,
                int(ticket.history_id),
                history_model=runtime.SearchHistory,
                verify_status="user_misjudged",
                correct_item_id=correct_item_id,
                correct_item_code=correct_item_code,
                correct_item_name=correct_item_name,
                correct_image_url=correct_image_url,
                correct_rank=correct_rank,
                correct_source=correct_source,
                verify_remark=resolution_remark or review_remark,
                verified_at=now,
            )
        elif correct_item_code:
            resolved_verify_status = resolved_verify_status or "wrong"
            item = await runtime.Items.get_item_by_item_code(session, correct_item_code)
            if item is None:
                raise Exception(f"物料编码 {correct_item_code} 不存在")
            item_id = getattr(item, "id", None)
            if item_id is None:
                matched_candidate, _ = cls._match_correct_item_in_history_results(
                    history,
                    item_code=correct_item_code,
                )
                if matched_candidate is not None:
                    item_id = int(matched_candidate.item_id)
            correct_item_id = int(item_id) if item_id is not None else None
            correct_item_name = item.item_name
            correct_image_url, correct_rank = await cls._resolve_correct_image_url(
                session,
                item_id=correct_item_id,
                history=history,
                item_code=correct_item_code,
            ) if correct_item_id is not None else (None, None)
            correct_source = "review_resolved"

            await runtime.SearchHistoryRepository.update_review_result(
                session,
                int(ticket.history_id),
                history_model=runtime.SearchHistory,
                verify_status=resolved_verify_status,
                correct_item_id=correct_item_id,
                correct_item_code=correct_item_code,
                correct_item_name=correct_item_name,
                correct_image_url=correct_image_url,
                correct_rank=correct_rank,
                correct_source=correct_source,
                verify_remark=resolution_remark or review_remark,
                verified_at=now,
            )

        review_started_at = ticket.review_started_at
        resolved_at = ticket.resolved_at
        closed_at = ticket.closed_at
        if review_status == "reviewing":
            review_started_at = review_started_at or now
            resolved_at = None
            closed_at = None
        elif review_status == "resolved":
            review_started_at = review_started_at or now
            resolved_at = now
            closed_at = None
        elif review_status == "closed":
            closed_at = now

        await runtime.SearchHistoryRepository.update_ticket(
            session,
            ticket_id,
            review_ticket_model=runtime.SearchReviewTicket,
            review_status=review_status,
            issue_type=issue_type,
            review_remark=review_remark,
            resolution_remark=resolution_remark,
            review_started_at=review_started_at,
            resolved_at=resolved_at,
            closed_at=closed_at,
        )
        await session.commit()

    return runtime.SearchReviewTicketUpdateRes(
        ticket_id=ticket_id,
        review_status=review_status,
        verify_status=resolved_verify_status,
        issue_type=issue_type,
        review_remark=review_remark,
        resolution_remark=resolution_remark,
        correct_item_id=correct_item_id,
        correct_item_code=correct_item_code,
        correct_item_name=correct_item_name,
        correct_image_url=correct_image_url,
        correct_rank=correct_rank,
        correct_source=correct_source,
        message="核验单更新成功",
    )


async def verify_v2_search_history(
    cls,
    *,
    history_id: int,
    verify_status: str,
    correct_item_code: str | None,
    remark: str | None,
    runtime=None,
):
    runtime = runtime or _runtime()
    verified_at = runtime.datetime.now()

    async with runtime.SessionLocal() as session:
        history = await runtime.SearchHistoryRepository.get_history_by_id(
            session,
            history_id,
            history_model=runtime.SearchHistory,
        )
        if history is None:
            raise Exception(f"history_id={history_id} 的记录不存在")

        correct_item_id = None
        correct_item_name = None
        correct_image_url = None
        correct_rank = None
        correct_source = None
        if verify_status == "user_misjudged":
            correct_fields = await cls._resolve_system_top1_correct_fields(session, history)
            correct_item_id = correct_fields["correct_item_id"]
            correct_item_code = correct_fields["correct_item_code"]
            correct_item_name = correct_fields["correct_item_name"]
            correct_image_url = correct_fields["correct_image_url"]
            correct_rank = correct_fields["correct_rank"]
            correct_source = correct_fields["correct_source"]
        elif verify_status == "correct" and not correct_item_code:
            correct_item_code = history.search_result_item_code
            correct_item_name = history.search_result_item_name
            matched_candidate, matched_rank = cls._match_correct_item_in_history_results(
                history,
                item_code=correct_item_code,
            )
            if matched_candidate is not None:
                correct_item_id = int(matched_candidate.item_id)
                correct_image_url = matched_candidate.image_url
                correct_rank = matched_rank
            elif correct_item_code:
                item = await runtime.Items.get_item_by_item_code(session, correct_item_code)
                if item is not None:
                    correct_item_id = int(item.id)
                    correct_item_name = item.item_name
                    correct_image_url, correct_rank = await cls._resolve_correct_image_url(
                        session,
                        item_id=correct_item_id,
                        history=history,
                        item_code=correct_item_code,
                    )
            correct_source = "review_resolved" if correct_item_code else None
        elif correct_item_code:
            item = await runtime.Items.get_item_by_item_code(session, correct_item_code)
            if item is None:
                raise Exception(f"物料编码 {correct_item_code} 不存在")
            correct_item_id = int(item.id)
            correct_item_name = item.item_name
            correct_image_url, correct_rank = await cls._resolve_correct_image_url(
                session,
                item_id=correct_item_id,
                history=history,
                item_code=correct_item_code,
            )
            correct_source = "review_resolved"
        else:
            correct_item_name = None

        await runtime.SearchHistoryRepository.update_review_result(
            session,
            history_id,
            history_model=runtime.SearchHistory,
            verify_status=verify_status,
            correct_item_id=correct_item_id,
            correct_item_code=correct_item_code,
            correct_item_name=correct_item_name,
            correct_image_url=correct_image_url,
            correct_rank=correct_rank,
            correct_source=correct_source,
            verify_remark=remark,
            verified_at=verified_at,
        )
        await session.commit()

    return runtime.SearchHistoryVerifyRes(
        history_id=str(history_id),
        status=verify_status,
        correct_item_id=correct_item_id,
        correct_item_code=correct_item_code,
        correct_item_name=correct_item_name,
        correct_image_url=correct_image_url,
        correct_rank=correct_rank,
        correct_source=correct_source,
        verify_remark=remark,
        verified_at=runtime.date_to_str(verified_at),
        message="校验提交成功",
    )
