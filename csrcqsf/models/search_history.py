
from __future__ import annotations
from datetime import datetime, timedelta
from enum import Enum
from urllib.parse import quote_plus
from sqlalchemy import String, delete, func, insert, select, update, and_, INT, BIGINT, Text, or_, DECIMAL, DateTime, case
from sqlalchemy.orm import relationship, Mapped, mapped_column, Session, selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from bfrcommon.common import get_pinyin
from typing import TYPE_CHECKING, Iterator, List
from bfrcommon.db import PageQueryResult, get_abbr_fn, get_count, async_get_count
from pydantic import BaseModel
from bfrcommon.db import PydanticType
from csrcqsf.data.pg import Base
from csrcqsf.models.sgo import ListInqueryItem


class SearchParameters(BaseModel):
    features: list[str] = []
    images: list[str] = []
    vechile: str | None = ''
    parent_item_id: int | None = 0
    lower_rate: float = 0.8


class SearchResultItem(BaseModel):
    item_id: str
    item_code: str
    item_name: str | None = None
    similar: float
    image_url: str | None = None


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
    correct_item_name: str | None
    correct_item_code: str | None
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
    verify_status: Mapped[str] = mapped_column(String(50), nullable=True)
    verify_remark: Mapped[str] = mapped_column(String(500), nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    correct_item_name: Mapped[str] = mapped_column(String(200), nullable=True)
    correct_item_code: Mapped[str] = mapped_column(String(200), nullable=True)
    search_results: Mapped[SearchResults] = mapped_column(
        PydanticType(SearchResults), nullable=True)

    @classmethod
    async def list_search_history(
        cls,
        session: AsyncSession,
        page: int,
        per_page: int,
        search_type: str = "all",
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
            stmt = stmt.where(cls.query_image.is_not(None))

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
            func.sum(case((cls.verify_status == "wrong", 1), else_=0)),
            func.sum(case((cls.verify_status == "partial", 1), else_=0)),
        )
        return await session.execute(stmt)

    @classmethod
    async def update_review_result(
        cls,
        session: AsyncSession,
        history_id: int,
        *,
        verify_status: str,
        correct_item_code: str | None,
        correct_item_name: str | None,
        verify_remark: str | None,
        verified_at: datetime,
    ):
        stmt = update(cls).where(cls.id == history_id).values(
            verify_status=verify_status,
            correct_item_code=correct_item_code,
            correct_item_name=correct_item_name,
            verify_remark=verify_remark,
            verified_at=verified_at,
        )
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def delete_history_with_query_images(cls, session: AsyncSession, history_id_list: list[int]):
        stmt = select(cls.id, cls.query_image).where(cls.id.in_(history_id_list))
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
