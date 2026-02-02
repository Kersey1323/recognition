
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
from .sgo_models import SgoCodeInquiry, SgoCodeInquiryReturn
from .sgo import SgoItemImages


class ItemType(str, Enum):
    REAL = 'real'
    VIRTUAL = 'virtual'


class ItemsVechile(Base):
    __tablename__ = 'item_vechile_info'
    vechile_id: Mapped[str] = mapped_column(
        BIGINT, nullable=False)  # 对应sgo数据库的车型字段
    item_id: Mapped[int] = mapped_column(BIGINT, nullable=False)

    @classmethod
    async def list_item_vechile_info_by_item_id(cls, session: AsyncSession, item_id: int):
        stmt = select(cls).where(cls.item_id == item_id)
        res = await session.scalars(stmt)
        return res

    @classmethod
    async def list_item_vechile_info_by_vechile_id(cls, session: AsyncSession, vechile_id: int):
        stmt = select(cls).where(cls.vechile_id == vechile_id)
        res = await session.scalars(stmt)
        return res


class ItemsParent(Base):
    __tablename__ = 'item_relation'
    item_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    parent_item_id: Mapped[int] = mapped_column(BIGINT, nullable=False)

    @classmethod
    async def list_parent_item_by_item_id(cls, session: AsyncSession, item_id: int):
        stmt = select(cls).where(cls.item_id == item_id)
        res = await session.scalars(stmt)
        return res

    @classmethod
    async def list_item_by_parent_id(cls, session: AsyncSession, parent_item_id: int):
        stmt = select(cls).where(cls.parent_item_id == parent_item_id)
        res = await session.scalars(stmt)
        return res


class Items(Base):
    __tablename__ = 'item_info'
    item_name: Mapped[str] = mapped_column(String(100), nullable=False)
    item_code: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True)
    obj_url: Mapped[str] = mapped_column(String(200), nullable=True)
    height: Mapped[float] = mapped_column(DECIMAL, nullable=True)
    long: Mapped[float] = mapped_column(DECIMAL, nullable=True)
    width: Mapped[float] = mapped_column(DECIMAL, nullable=True)
    size_str: Mapped[str] = mapped_column(Text, nullable=True)
    item_type: Mapped[ItemType] = mapped_column(
        String(200), nullable=False, default='real')
    parent_num: Mapped[int] = mapped_column(INT, nullable=False, default=0)
    son_num: Mapped[int] = mapped_column(INT, nullable=False, default=0)
    image_index_num: Mapped[int] = mapped_column(
        INT, nullable=False, default=0)
    feature_index_num: Mapped[int] = mapped_column(
        INT, nullable=False, default=0)

    @classmethod
    async def update_items_index(cls, session: AsyncSession, item_id: int, image_index_num: int, feature_index_num: int):
        stmt = update(cls).where(cls.id == item_id).values(
            image_index_num=image_index_num,feature_index_num=feature_index_num)
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def update_parent_num(cls, session: AsyncSession, item_id: int, parent_num: int):
        stmt = update(cls).where(cls.id == item_id).values(
            parent_num=parent_num)
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def update_son_num(cls, session: AsyncSession, item_id: int, son_num: int):
        stmt = update(cls).where(cls.id == item_id).values(son_num=son_num)
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def create_item(cls, session: AsyncSession, item: Items):
        session.add(item)
        await session.flush()

    @classmethod
    async def get_item_by_id(cls, session: AsyncSession, item_id: int):
        stmt = select(cls).where(cls.id == item_id)
        return await session.scalar(stmt)

    @classmethod
    async def get_item_by_item_code(cls, session: AsyncSession, item_code: str):
        stmt = select(cls).where(cls.item_code == item_code)
        return await session.scalar(stmt)

    @classmethod
    async def get_item_by_id_list(cls, session: AsyncSession, item_id_list: list[int]):
        stmt = select(cls).where(cls.id.in_(item_id_list))
        item_list = await session.scalars(stmt)
        for item in item_list:
            yield item

    @classmethod
    async def delete_item_by_id(cls, session: AsyncSession, item_id: int):
        stmt = delete(cls).where(cls.id == item_id)
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def delete_item_by_id_list(cls, session: AsyncSession, item_id_list: list[int]):
        stmt = delete(cls).where(cls.id.in_(item_id_list))
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def get_item_parent_by_id(cls, session: AsyncSession, item_id: int):
        stmt = select(cls).where(cls.id == item_id)
        return await session.scalar(stmt)

    @classmethod
    async def put_item(cls, session: AsyncSession, item_id: int, obj_url: str, item_code: str, length: float,
                       parent_item_id: int,
                       width: float, height: float, item_name: str):
        stmt = update(cls).where(cls.id == item_id).values(obj_url=obj_url)
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def list_all_items(cls, session: AsyncSession):
        stmt = select(cls)
        return await session.scalars(stmt)

    @classmethod
    async def list_items(cls, session: AsyncSession, query: str = None, page: int = 0, per_page: int = 20,
                         has_images: bool = False,
                         item_id_list: list[int] = [], item_code_list: list[str] = [],need_index:bool = False):
        offset = (page-1) * per_page
        stmt = select(cls)
        if len(item_id_list) > 0:
            stmt = stmt.where(cls.id.in_(item_id_list))
        if query is not None and query != '':
            stmt = stmt.where(cls.item_name.like(f'%{query}%').__or__(
                cls.item_code.like(f'%{query}%')))
        if has_images:
            item_id_stmt = select(SgoItemImages.item_id.distinct())
            stmt = stmt.where(cls.id.in_(item_id_stmt))
        if len(item_code_list) > 0:
            stmt = stmt.where(cls.item_code.in_(item_code_list))
        if need_index:
            stmt = stmt.where(cls.image_index_num.__gt__(0).__and__(cls.feature_index_num.__gt__(0)))
        count = await async_get_count(session, stmt)
        stmt = stmt.order_by(cls.time_created.desc()).order_by(cls.id.desc())
        if page != -1:
            stmt = stmt.limit(
                per_page).offset(offset)
        datas = await session.scalars(stmt)
        return PageQueryResult(total=count, data=datas.all())

    @classmethod
    async def put_item_size_desc(cls, session: AsyncSession, item_id: int, size_desc: str):
        stmt = update(cls).where(cls.id == item_id).values(size_str=size_desc)
        await session.execute(stmt)
        await session.flush()

    # @classmethod
    # async def get_item_images(cls,session:AsyncSession,item_id:int):
    #     stmt = select(cls).where(cls.item_id == item_id)
    #     datas = await session.scalars(stmt)
    #     for data in datas:
    #         yield data
