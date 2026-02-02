
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


class Files(Base):
    __tablename__ = 'zcsf_parts_files'
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[str] = mapped_column(String(255), nullable=False)
    table_num: Mapped[int] = mapped_column(INT)

    @classmethod
    async def create_file(cls, session: AsyncSession, file_name: str, file_url: str, table_num: int = 0):
        data = Files(
            file_name=file_name,
            file_url=file_url,
            table_num=table_num
        )
        session.add(data)
        await session.flush()

    @classmethod
    async def update_file(cls, session: AsyncSession, file_id: int, table_num: int = 0):
        stmt = update(cls).where(cls.id == file_id).values(table_num=table_num)
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def delete_file(cls, session: AsyncSession, file_id_list: list[int]):
        if len(file_id_list) == 0:
            return
        stmt = delete(cls).where(cls.id.in_(file_id_list))
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def list_files(cls, session: AsyncSession, query: str = None, page: int = 0, per_page: int = 20):
        offset = (page-1) * per_page
        stmt = select(cls)
        if query is not None and query != '':
            stmt = stmt.where(cls.file_name.like(f"%{query}%"))

        if page == -1:
            datas = await session.scalars(stmt)
            return PageQueryResult(total=len(datas), data=datas.all())

        count = await async_get_count(session, stmt)
        stmt = stmt.order_by(cls.created_by.desc())
        if page != -1:
            stmt = stmt.limit(
                per_page).offset(offset)
        datas = await session.scalars(stmt)
        return PageQueryResult(total=count, data=datas.all())

    @classmethod
    async def get_file(cls, session: AsyncSession, file_id: int):
        stmt = select(cls).where(cls.id == file_id)
        return await session.scalar(stmt)


class FileTables(Base):
    __tablename__ = 'zcsf_parts_tables'
    file_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    table_data: Mapped[str] = mapped_column(Text)
    table_name: Mapped[str] = mapped_column(String(500))

    @classmethod
    async def create_tables(cls, session: AsyncSession, file_id: int, data_list: list[str], table_name: str):
        datas = []
        for data in data_list:
            datas.append(
                cls(
                    file_id=file_id,
                    table_name=table_name,
                    table_data=data
                )
            )
        if len(datas) > 0:
            session.add_all(datas)

        await session.flush()

    @classmethod
    async def delete_tables(cls, session: AsyncSession, table_id_list: list[int]):
        if len(table_id_list) == 0:
            return

        stmt = delete(cls).where(cls.id.in_(table_id_list))
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def list_tables(cls, session: AsyncSession, file_id: int, query: str = None, page: int = 0, per_page: int = 20):
        offset = (page-1) * per_page
        stmt = select(cls).where(cls.file_id == file_id)
        if query is not None and query != '':
            stmt = stmt.where(cls.table_name.like(f'%{query}%').__or__(
                cls.table_data.like(f'%{query}%')))

        if page == -1:
            count = await async_get_count(session, stmt)
            datas = await session.scalars(stmt)
            return PageQueryResult(total=count, data=datas.all())

        count = await async_get_count(session, stmt)
        stmt = stmt.order_by(cls.created_by.desc()).limit(
            per_page).offset(offset)
        datas = await session.scalars(stmt)
        return PageQueryResult(total=count, data=datas.all())
