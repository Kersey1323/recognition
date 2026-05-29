
from __future__ import annotations
from datetime import datetime, timedelta
from enum import Enum
from types import SimpleNamespace
from urllib.parse import quote_plus
from sqlalchemy import String, delete, func, insert, select, update, and_, INT, BIGINT, Text, or_, DECIMAL, DateTime, case, JSON
from sqlalchemy.orm import relationship, Mapped, mapped_column, selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from bfrcommon.common import get_pinyin
from typing import TYPE_CHECKING, Iterator, List
from bfrcommon.db import PageQueryResult, get_abbr_fn, async_get_count
from pydantic import BaseModel, Field
from bfrcommon.db import PydanticType
from csrcqsf.infra.db.main_db import Base
from csrcqsf.modules.sgo.schemas import ListInqueryItem


class SearchParameters(BaseModel):
    features: list[str] = []
    images: list[str] = []
    query_images: list[str] = []
    vechile: str | None = ''
    parent_item_id: int | None = 0
    lower_rate: float = 0.8


class MatchedImage(BaseModel):
    image_url: str
    rate: float
    matched_query_indexes: list[int] = Field(default_factory=list)


class SearchResultItem(BaseModel):
    item_id: str
    item_code: str
    item_name: str | None = None
    similar: float
    image_url: str | None = None
    matched_images: list[MatchedImage] = []


class SearchResults(BaseModel):
    items: list[SearchResultItem] = []


class SearchHistoryItem(BaseModel):
    parameters: SearchParameters | None
    inquery_info: ListInqueryItem | None
    result: SearchResults | None
    inquery_id: str | None
    inquery_num: str | None
    search_item_name: str | None
    search_item_code: str | None
    correct_item_id: str | None = None
    correct_item_name: str | None
    correct_item_code: str | None
    correct_image_url: str | None = None
    correct_rank: int | None = None
    correct_source: str | None = None
    history_id: str


class SearchHistory(Base):
    __tablename__ = 'search_history'
    inquery_id: Mapped[str] = mapped_column(String(500), nullable=True)
    inquery_num: Mapped[str] = mapped_column(String(500), nullable=True)
    search_result_item_name: Mapped[str] = mapped_column(
        String(500), nullable=True)
    search_result_item_code: Mapped[str] = mapped_column(String(200))
    search_parameter: Mapped[SearchParameters] = mapped_column(
        PydanticType(SearchParameters), nullable=True)
    query_text: Mapped[str] = mapped_column(String(1000), nullable=True)
    query_image: Mapped[str] = mapped_column(String(1000), nullable=True)
    query_images_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    search_equipment: Mapped[str] = mapped_column(String(50), nullable=True)
    verify_status: Mapped[str] = mapped_column(String(50), nullable=True)
    verify_remark: Mapped[str] = mapped_column(String(500), nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    ranking_feedback_type: Mapped[str] = mapped_column(String(50), nullable=True)
    selected_item_id: Mapped[int] = mapped_column(BIGINT, nullable=True)
    selected_item_code: Mapped[str] = mapped_column(String(200), nullable=True)
    selected_item_name: Mapped[str] = mapped_column(String(200), nullable=True)
    selected_rank: Mapped[int] = mapped_column(INT, nullable=True)
    selected_image_url: Mapped[str] = mapped_column(String(1000), nullable=True)
    correct_item_id: Mapped[int] = mapped_column(BIGINT, nullable=True)
    correct_item_name: Mapped[str] = mapped_column(String(200), nullable=True)
    correct_item_code: Mapped[str] = mapped_column(String(200), nullable=True)
    correct_image_url: Mapped[str] = mapped_column(String(1000), nullable=True)
    correct_rank: Mapped[int] = mapped_column(INT, nullable=True)
    correct_source: Mapped[str] = mapped_column(String(50), nullable=True)
    search_results: Mapped[SearchResults] = mapped_column(
        PydanticType(SearchResults), nullable=True)

    @classmethod
    async def list_search_history(
        cls,
        session: AsyncSession,
        page: int,
        per_page: int,
        search_type: str = "all",
        search_equipment: str = "all",
        keyword: str | None = None,
        status: str = "all",
        date_from: str | None = None,
        date_to: str | None = None,
    ):
        offset = (page-1) * per_page
        stmt = select(cls)

        if search_type == "text":
            stmt = stmt.where(cls.query_text.is_not(None))
        elif search_type == "image":
            stmt = stmt.where(
                or_(
                    cls.query_image.is_not(None),
                    cls.query_images_json.is_not(None),
                )
            )

        if search_equipment != "all":
            stmt = stmt.where(cls.search_equipment == search_equipment)

        if keyword:
            stmt = stmt.where(
                or_(
                    cls.query_text.like(f"%{keyword}%"),
                    cls.search_result_item_name.like(f"%{keyword}%"),
                    cls.search_result_item_code.like(f"%{keyword}%"),
                    cls.correct_item_code.like(f"%{keyword}%"),
                )
            )

        if status != "all":
            if status == "pending":
                stmt = stmt.where(
                    or_(cls.verify_status.is_(None), cls.verify_status == "pending")
                )
            elif status == "wrong":
                stmt = stmt.where(
                    or_(cls.verify_status == "wrong", cls.verify_status == "partial")
                )
            else:
                stmt = stmt.where(cls.verify_status == status)

        if date_from:
            start = datetime.strptime(date_from, "%Y-%m-%d")
            stmt = stmt.where(cls.time_created >= start)

        if date_to:
            end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            stmt = stmt.where(cls.time_created < end)

        count = await async_get_count(session, stmt)
        stmt = stmt.order_by(cls.time_created.desc())
        if page != -1:
            stmt = stmt.limit(
                per_page).offset(offset)
        datas = await session.scalars(stmt)
        return PageQueryResult(total=count, data=datas.all())

    @classmethod
    async def get_history_by_id(cls, session: AsyncSession, history_id: int):
        stmt = select(cls).where(cls.id == history_id)
        return await session.scalar(stmt)

    @classmethod
    async def summarize_review_status(cls, session: AsyncSession):
        pending_expr = or_(cls.verify_status.is_(None), cls.verify_status == "pending")
        stmt = select(
            func.count(cls.id),
            func.sum(case((pending_expr, 1), else_=0)),
            func.sum(case((cls.verify_status == "correct", 1), else_=0)),
            func.sum(case((or_(cls.verify_status == "wrong", cls.verify_status == "partial"), 1), else_=0)),
            func.sum(case((cls.verify_status == "user_misjudged", 1), else_=0)),
        )
        return await session.execute(stmt)

    @classmethod
    async def update_review_result(
        cls,
        session: AsyncSession,
        history_id: int,
        *,
        verify_status: str,
        correct_item_id: int | None,
        correct_item_code: str | None,
        correct_item_name: str | None,
        correct_image_url: str | None,
        correct_rank: int | None,
        correct_source: str | None,
        verify_remark: str | None,
        verified_at: datetime,
    ):
        stmt = update(cls).where(cls.id == history_id).values(
            verify_status=verify_status,
            correct_item_id=correct_item_id,
            correct_item_code=correct_item_code,
            correct_item_name=correct_item_name,
            correct_image_url=correct_image_url,
            correct_rank=correct_rank,
            correct_source=correct_source,
            verify_remark=verify_remark,
            verified_at=verified_at,
        )
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def update_feedback(
        cls,
        session: AsyncSession,
        history_id: int,
        *,
        verify_status: str | None,
        verify_remark: str | None,
        verified_at: datetime | None,
        ranking_feedback_type: str | None,
        selected_item_id: int | None,
        selected_item_code: str | None,
        selected_item_name: str | None,
        selected_rank: int | None,
        selected_image_url: str | None,
        correct_item_id: int | None,
        correct_item_code: str | None,
        correct_item_name: str | None,
        correct_image_url: str | None,
        correct_rank: int | None,
        correct_source: str | None,
    ):
        stmt = update(cls).where(cls.id == history_id).values(
            verify_status=verify_status,
            verify_remark=verify_remark,
            verified_at=verified_at,
            ranking_feedback_type=ranking_feedback_type,
            selected_item_id=selected_item_id,
            selected_item_code=selected_item_code,
            selected_item_name=selected_item_name,
            selected_rank=selected_rank,
            selected_image_url=selected_image_url,
            correct_item_id=correct_item_id,
            correct_item_code=correct_item_code,
            correct_item_name=correct_item_name,
            correct_image_url=correct_image_url,
            correct_rank=correct_rank,
            correct_source=correct_source,
        )
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def delete_history_with_query_images(cls, session: AsyncSession, history_id_list: list[int]):
        stmt = select(cls.id, cls.query_image, cls.query_images_json).where(cls.id.in_(history_id_list))
        rows = (await session.execute(stmt)).all()
        await session.execute(delete(cls).where(cls.id.in_(history_id_list)))
        await session.flush()
        return rows

    @classmethod
    async def delete_history(cls, session: AsyncSession, history_id_list: list[int]):
        if len(history_id_list) == 0:
            return
        stmt = delete(cls).where(cls.id.in_(history_id_list))
        return await session.execute(stmt)


class SearchReviewTicket(Base):
    __tablename__ = 'search_review_ticket'

    history_id: Mapped[int] = mapped_column(BIGINT, index=True, nullable=False)
    review_status: Mapped[str] = mapped_column(String(50), nullable=False, default="open")
    issue_type: Mapped[str] = mapped_column(String(50), nullable=True)
    review_remark: Mapped[str] = mapped_column(String(500), nullable=True)
    resolution_remark: Mapped[str] = mapped_column(String(500), nullable=True)
    review_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    @classmethod
    async def get_active_by_history_id(cls, session: AsyncSession, history_id: int):
        stmt = select(cls).where(
            and_(cls.history_id == history_id, cls.review_status != "closed")
        ).order_by(cls.id.desc())
        return await session.scalar(stmt)

    @classmethod
    async def create_ticket(cls, session: AsyncSession, *, ticket_id: int, history_id: int):
        ticket = cls(id=ticket_id, history_id=history_id, review_status="open")
        session.add(ticket)
        await session.flush()
        return ticket

    @classmethod
    async def get_by_id(cls, session: AsyncSession, ticket_id: int):
        stmt = select(cls).where(cls.id == ticket_id)
        return await session.scalar(stmt)

    @classmethod
    async def list_tickets(
        cls,
        session: AsyncSession,
        *,
        page: int,
        per_page: int,
        review_status: str = "all",
        issue_type: str = "all",
        search_equipment: str = "all",
        keyword: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ):
        offset = (page - 1) * per_page
        stmt = select(
            cls,
            SearchHistory.query_text.label("query_text"),
            SearchHistory.query_image.label("query_image"),
            SearchHistory.query_images_json.label("query_images_json"),
            SearchHistory.query_text.label("history_query_text"),
            SearchHistory.search_equipment.label("search_equipment"),
            SearchHistory.search_result_item_name.label("search_result_item_name"),
            SearchHistory.search_result_item_code.label("search_result_item_code"),
            SearchHistory.verify_remark.label("verify_remark"),
            SearchHistory.correct_item_id.label("correct_item_id"),
            SearchHistory.correct_item_name.label("correct_item_name"),
            SearchHistory.correct_item_code.label("correct_item_code"),
            SearchHistory.correct_image_url.label("correct_image_url"),
            SearchHistory.correct_rank.label("correct_rank"),
            SearchHistory.correct_source.label("correct_source"),
        ).join(SearchHistory, SearchHistory.id == cls.history_id)
        if review_status != "all":
            stmt = stmt.where(cls.review_status == review_status)
        if issue_type != "all":
            stmt = stmt.where(cls.issue_type == issue_type)
        if search_equipment != "all":
            stmt = stmt.where(SearchHistory.search_equipment == search_equipment)
        if keyword:
            like_value = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    cls.id.cast(String).like(like_value),
                    cls.history_id.cast(String).like(like_value),
                    SearchHistory.query_text.like(like_value),
                    SearchHistory.search_result_item_code.like(like_value),
                    SearchHistory.search_result_item_name.like(like_value),
                )
            )
        if date_from:
            start = datetime.strptime(date_from, "%Y-%m-%d")
            stmt = stmt.where(cls.time_created >= start)
        if date_to:
            end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            stmt = stmt.where(cls.time_created < end)
        total = await async_get_count(session, stmt)
        stmt = stmt.order_by(cls.time_created.desc()).limit(per_page).offset(offset)
        rows = (await session.execute(stmt)).all()
        merged_rows = []
        for (
            ticket,
            query_text,
            query_image,
            query_images_json,
            history_query_text,
            history_search_equipment,
            search_item_name,
            search_item_code,
            verify_remark,
            correct_item_id,
            correct_item_name,
            correct_item_code,
            correct_image_url,
            correct_rank,
            correct_source,
        ) in rows:
            merged_rows.append(
                SimpleNamespace(
                    id=ticket.id,
                    history_id=ticket.history_id,
                    review_status=ticket.review_status,
                    issue_type=ticket.issue_type,
                    review_remark=ticket.review_remark,
                    resolution_remark=ticket.resolution_remark,
                    review_started_at=ticket.review_started_at,
                    resolved_at=ticket.resolved_at,
                    closed_at=ticket.closed_at,
                    time_created=ticket.time_created,
                    time_updated=ticket.time_updated,
                    query_text=query_text,
                    query_image=query_image,
                    query_images_json=query_images_json,
                    search_type="image" if (query_image or (query_images_json or [])) else ("text" if history_query_text else "unknown"),
                    search_equipment=history_search_equipment,
                    search_result_item_name=search_item_name,
                    search_result_item_code=search_item_code,
                    verify_remark=verify_remark,
                    correct_item_id=correct_item_id,
                    correct_item_name=correct_item_name,
                    correct_item_code=correct_item_code,
                    correct_image_url=correct_image_url,
                    correct_rank=correct_rank,
                    correct_source=correct_source,
                )
            )
        return PageQueryResult(total=total, data=merged_rows)

    @classmethod
    async def update_ticket(
        cls,
        session: AsyncSession,
        ticket_id: int,
        *,
        review_status: str,
        issue_type: str | None,
        review_remark: str | None,
        resolution_remark: str | None,
        review_started_at: datetime | None,
        resolved_at: datetime | None,
        closed_at: datetime | None,
    ):
        stmt = update(cls).where(cls.id == ticket_id).values(
            review_status=review_status,
            issue_type=issue_type,
            review_remark=review_remark,
            resolution_remark=resolution_remark,
            review_started_at=review_started_at,
            resolved_at=resolved_at,
            closed_at=closed_at,
        )
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def count_open_tickets(cls, session: AsyncSession):
        stmt = select(func.count(cls.id)).where(cls.review_status != "closed")
        count = await session.scalar(stmt)
        return int(count or 0)

    @classmethod
    async def list_latest_by_history_ids(
        cls,
        session: AsyncSession,
        history_id_list: list[int],
    ):
        if not history_id_list:
            return {}

        stmt = select(cls).where(cls.history_id.in_(history_id_list)).order_by(
            cls.history_id.asc(),
            cls.id.desc(),
        )
        rows = (await session.scalars(stmt)).all()
        latest_map = {}
        for row in rows:
            if row.history_id not in latest_map:
                latest_map[row.history_id] = row
        return latest_map

    @classmethod
    async def summarize_tickets(cls, session: AsyncSession):
        stmt = select(
            func.count(cls.id),
            func.sum(case((cls.review_status == "open", 1), else_=0)),
            func.sum(case((cls.review_status == "reviewing", 1), else_=0)),
            func.sum(case((cls.review_status == "resolved", 1), else_=0)),
            func.sum(case((cls.review_status == "closed", 1), else_=0)),
            func.sum(case((cls.issue_type == "missing_index", 1), else_=0)),
            func.sum(case((cls.issue_type == "precision_issue", 1), else_=0)),
            func.sum(case((cls.issue_type == "system_bug", 1), else_=0)),
            func.sum(case((cls.issue_type == "user_misjudged", 1), else_=0)),
        )
        return await session.execute(stmt)
