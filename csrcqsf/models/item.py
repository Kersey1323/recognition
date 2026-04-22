
from __future__ import annotations
from datetime import datetime
from enum import Enum
from urllib.parse import quote_plus
from sqlalchemy import String, delete, func, insert, select, update, and_, INT, BIGINT, Text, or_, DECIMAL, DateTime
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
    weight: Mapped[float] = mapped_column(DECIMAL, nullable=True)
    source_video_path: Mapped[str] = mapped_column(String(500), nullable=True)
    source_video_filename: Mapped[str] = mapped_column(String(255), nullable=True)
    source_video_size: Mapped[int] = mapped_column(BIGINT, nullable=True)
    source_video_content_type: Mapped[str] = mapped_column(String(100), nullable=True)
    source_video_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
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
                       width: float, height: float, item_name: str, weight: float = None):
        stmt = update(cls).where(cls.id == item_id).values(
            obj_url=obj_url,
            item_code=item_code,
            long=length,
            width=width,
            height=height,
            item_name=item_name,
            weight=weight,
        )
        await session.execute(stmt)
        await session.flush()

    @classmethod
    def build_measurement_updates(
        cls,
        height: float | None = None,
        length: float | None = None,
        width: float | None = None,
        weight: float | None = None,
    ) -> dict:
        values = {}
        if height is not None:
            values["height"] = height
        if length is not None:
            values["long"] = length
        if width is not None:
            values["width"] = width
        if weight is not None:
            values["weight"] = weight
        return values

    @classmethod
    def build_source_video_updates(
        cls,
        video_path: str,
        filename: str,
        size: int,
        content_type: str,
        height: float | None = None,
        length: float | None = None,
        width: float | None = None,
        weight: float | None = None,
        updated_at=None,
    ) -> dict:
        values = {
            "source_video_path": video_path,
            "source_video_filename": filename,
            "source_video_size": size,
            "source_video_content_type": content_type,
            "source_video_updated_at": updated_at,
        }
        values.update(cls.build_measurement_updates(
            height=height,
            length=length,
            width=width,
            weight=weight,
        ))
        return values

    @classmethod
    def build_clear_source_video_values(cls) -> dict:
        return {
            "source_video_path": None,
            "source_video_filename": None,
            "source_video_size": None,
            "source_video_content_type": None,
            "source_video_updated_at": None,
            "height": None,
            "long": None,
            "width": None,
            "weight": None,
        }

    @classmethod
    def build_obj_url_update(cls, obj_url: str | None) -> dict:
        return {"obj_url": obj_url}

    @classmethod
    async def update_obj_url(cls, session: AsyncSession, item_id: int, obj_url: str | None):
        stmt = update(cls).where(cls.id == item_id).values(**cls.build_obj_url_update(obj_url))
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def update_measurements(
        cls,
        session: AsyncSession,
        item_id: int,
        height: float | None = None,
        length: float | None = None,
        width: float | None = None,
        weight: float | None = None,
    ):
        values = cls.build_measurement_updates(
            height=height,
            length=length,
            width=width,
            weight=weight,
        )
        if len(values) == 0:
            return
        stmt = update(cls).where(cls.id == item_id).values(**values)
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def list_source_videos(
        cls,
        session: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ):
        count_stmt = select(func.count(cls.id)).where(cls.source_video_path.is_not(None))
        total = await session.scalar(count_stmt)
        stmt = (
            select(cls)
            .where(cls.source_video_path.is_not(None))
            .order_by(cls.source_video_updated_at.desc(), cls.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.scalars(stmt)
        return list(result), total or 0

    @classmethod
    async def update_source_video(
        cls,
        session: AsyncSession,
        item_id: int,
        video_path: str,
        filename: str,
        size: int,
        content_type: str,
        height: float | None = None,
        length: float | None = None,
        width: float | None = None,
        weight: float | None = None,
        updated_at=None,
    ):
        values = cls.build_source_video_updates(
            video_path=video_path,
            filename=filename,
            size=size,
            content_type=content_type,
            height=height,
            length=length,
            width=width,
            weight=weight,
            updated_at=updated_at,
        )
        stmt = update(cls).where(cls.id == item_id).values(**values)
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def clear_source_video(cls, session: AsyncSession, item_id: int):
        stmt = update(cls).where(cls.id == item_id).values(**cls.build_clear_source_video_values())
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
