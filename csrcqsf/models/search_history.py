
from __future__ import annotations
from enum import Enum
from urllib.parse import quote_plus
from sqlalchemy import String, delete, func, insert, select, update, and_, INT, BIGINT, Text, or_, DECIMAL
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
    correct_item_name: Mapped[str] = mapped_column(String(200), nullable=True)
    correct_item_code: Mapped[str] = mapped_column(String(200), nullable=True)
    search_results: Mapped[SearchResults] = mapped_column(
        PydanticType(SearchResults), nullable=True)

    @classmethod
    async def list_search_history(cls, session: AsyncSession, page: int, per_page: int):
        offset = (page-1) * per_page
        stmt = select(cls)
        count = await async_get_count(session, stmt)
        stmt = stmt.order_by(cls.time_created.desc())
        if page != -1:
            stmt = stmt.limit(
                per_page).offset(offset)
        datas = await session.scalars(stmt)
        return PageQueryResult(total=count, data=datas.all())

    @classmethod
    async def delete_history(cls, session: AsyncSession, history_id_list: list[int]):
        if len(history_id_list) == 0:
            return
        stmt = delete(cls).where(cls.id.in_(history_id_list))
        return await session.execute(stmt)
