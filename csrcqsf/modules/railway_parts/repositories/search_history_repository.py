from __future__ import annotations

from csrcqsf.models.orm.search_history import SearchHistory, SearchReviewTicket


class SearchHistoryRepository:
    """统一隔离检索历史与人工复核工单的数据访问入口。"""

    @classmethod
    def _get_history_model(cls, history_model=None):
        return history_model or SearchHistory

    @classmethod
    def _get_review_ticket_model(cls, review_ticket_model=None):
        return review_ticket_model or SearchReviewTicket

    @classmethod
    async def list_search_history(cls, session, *, history_model=None, **kwargs):
        return await cls._get_history_model(history_model).list_search_history(
            session=session,
            **kwargs,
        )

    @classmethod
    async def get_history_by_id(cls, session, history_id: int, *, history_model=None):
        return await cls._get_history_model(history_model).get_history_by_id(session, history_id)

    @classmethod
    async def summarize_review_status(cls, session, *, history_model=None):
        return await cls._get_history_model(history_model).summarize_review_status(session)

    @classmethod
    async def update_review_result(cls, session, history_id: int, *, history_model=None, **kwargs):
        return await cls._get_history_model(history_model).update_review_result(session, history_id, **kwargs)

    @classmethod
    async def update_feedback(cls, session, history_id: int, *, history_model=None, **kwargs):
        return await cls._get_history_model(history_model).update_feedback(session, history_id, **kwargs)

    @classmethod
    async def delete_history_with_query_images(
        cls,
        session,
        history_id_list: list[int],
        *,
        history_model=None,
    ):
        return await cls._get_history_model(history_model).delete_history_with_query_images(
            session,
            history_id_list,
        )

    @classmethod
    async def get_pending_history_cleanup_upper_bound(cls, session, *, history_model=None):
        return await cls._get_history_model(history_model).get_pending_history_cleanup_upper_bound(session)

    @classmethod
    async def delete_pending_history_batch_with_query_images(
        cls, session, *, upper_bound: int, batch_size: int, history_model=None,
    ):
        return await cls._get_history_model(history_model).delete_pending_history_batch_with_query_images(
            session, upper_bound=upper_bound, batch_size=batch_size,
        )

    @classmethod
    async def list_latest_by_history_ids(
        cls,
        session,
        history_id_list: list[int],
        *,
        review_ticket_model=None,
    ):
        # 列表页一次批量读取各历史的最新工单，避免逐条查询造成 N+1 数据库请求。
        return await cls._get_review_ticket_model(review_ticket_model).list_latest_by_history_ids(
            session,
            history_id_list,
        )

    @classmethod
    async def count_open_tickets(cls, session, *, review_ticket_model=None):
        return await cls._get_review_ticket_model(review_ticket_model).count_open_tickets(session)

    @classmethod
    async def list_tickets(cls, session, *, review_ticket_model=None, **kwargs):
        return await cls._get_review_ticket_model(review_ticket_model).list_tickets(session, **kwargs)

    @classmethod
    async def get_ticket_by_id(cls, session, ticket_id: int, *, review_ticket_model=None):
        return await cls._get_review_ticket_model(review_ticket_model).get_by_id(session, ticket_id)

    @classmethod
    async def summarize_tickets(cls, session, *, review_ticket_model=None):
        return await cls._get_review_ticket_model(review_ticket_model).summarize_tickets(session)

    @classmethod
    async def update_ticket(cls, session, ticket_id: int, *, review_ticket_model=None, **kwargs):
        return await cls._get_review_ticket_model(review_ticket_model).update_ticket(
            session,
            ticket_id,
            **kwargs,
        )

    @classmethod
    async def create_ticket(
        cls,
        session,
        *,
        ticket_id: int,
        history_id: int,
        review_ticket_model=None,
    ):
        return await cls._get_review_ticket_model(review_ticket_model).create_ticket(
            session,
            ticket_id=ticket_id,
            history_id=history_id,
        )

    @classmethod
    async def get_active_by_history_id(cls, session, history_id: int, *, review_ticket_model=None):
        return await cls._get_review_ticket_model(review_ticket_model).get_active_by_history_id(
            session,
            history_id,
        )
