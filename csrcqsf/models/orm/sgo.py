"""
数据模型层 - SGO系统相关模型
职责：定义数据库表结构、提供基础CRUD方法
注意：此层不包含业务逻辑，仅提供数据访问接口
"""

from __future__ import annotations
from datetime import datetime
from urllib.parse import quote_plus
from sqlalchemy import String, delete, func, insert, select, update, and_, INT, BIGINT, Text, or_, DECIMAL, DateTime
from sqlalchemy.orm import relationship, Mapped, mapped_column, Session, selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from bfrcommon.common import get_pinyin
from typing import TYPE_CHECKING, Iterator, List
from bfrcommon.db import PageQueryResult, get_abbr_fn, get_count, async_get_count
from bfrcommon.db import PydanticType
from csrcqsf.infra.db.main_db import Base, PlainBase
from csrcqsf.modules.sgo.schemas import ImageSourceType, ListInqueryItem, SegmentStatus


class SegmentedImage(PlainBase):
    """自动分割后的图片记录"""
    __tablename__ = 'segmented_image_info'
    
    item_id: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)
    source_image_id: Mapped[int] = mapped_column(BIGINT, nullable=False)  # 原图 ID (SgoItemImages.id)
    source_image_url: Mapped[str] = mapped_column(String(500), nullable=False)  # 原图 URL
    segmented_image_url: Mapped[str] = mapped_column(String(500), nullable=True)  # 分割后图片 URL
    status: Mapped[SegmentStatus] = mapped_column(String(50), nullable=False, default=SegmentStatus.PENDING)
    
    # 分割信息
    mask_area: Mapped[int] = mapped_column(INT, nullable=True)  # 掩码面积
    bbox_x: Mapped[int] = mapped_column(INT, nullable=True)
    bbox_y: Mapped[int] = mapped_column(INT, nullable=True)
    bbox_w: Mapped[int] = mapped_column(INT, nullable=True)
    bbox_h: Mapped[int] = mapped_column(INT, nullable=True)
    
    # 索引信息
    is_indexed: Mapped[int] = mapped_column(INT, default=0)  # 0=未索引 1=已索引
    
    error_message: Mapped[str] = mapped_column(Text, nullable=True)  # 错误信息
    id: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    
    @classmethod
    async def create_record(cls, session: AsyncSession, record: 'SegmentedImage'):
        session.add(record)
        await session.flush()
    
    @classmethod
    async def batch_create(cls, session: AsyncSession, records: list['SegmentedImage']):
        if len(records) == 0:
            return
        session.add_all(records)
        await session.flush()
    
    @classmethod
    async def list_by_item_id(cls, session: AsyncSession, item_id: int):
        stmt = select(cls).where(cls.item_id == item_id).order_by(cls.id.desc())
        return await session.scalars(stmt)
    
    @classmethod
    async def list_pending_by_item_id(cls, session: AsyncSession, item_id: int):
        """获取待处理的分割记录"""
        stmt = select(cls).where(
            and_(cls.item_id == item_id, cls.status == SegmentStatus.PENDING)
        )
        return await session.scalars(stmt)

    @classmethod
    async def get_latest_success(
        cls,
        session: AsyncSession,
        item_id: int,
        source_image_id: int,
    ):
        stmt = (
            select(cls)
            .where(
                cls.item_id == item_id,
                cls.source_image_id == source_image_id,
                cls.status == SegmentStatus.SUCCESS,
            )
            .order_by(cls.id.desc())
            .limit(1)
        )
        result = await session.scalars(stmt)
        return result.first()

    @classmethod
    async def list_by_source_image(
        cls,
        session: AsyncSession,
        item_id: int,
        source_image_id: int,
    ) -> list['SegmentedImage']:
        stmt = select(cls).where(
            cls.item_id == item_id,
            cls.source_image_id == source_image_id,
        )
        result = await session.scalars(stmt)
        return list(result.all())
    
    @classmethod
    async def update_status(cls, session: AsyncSession, record_id: int, 
                            status: SegmentStatus, segmented_url: str = None,
                            mask_area: int = None, bbox: tuple = None, error: str = None):
        values = {'status': status}
        if segmented_url:
            values['segmented_image_url'] = segmented_url
        if mask_area is not None:
            values['mask_area'] = mask_area
        if bbox:
            values['bbox_x'] = bbox[0]
            values['bbox_y'] = bbox[1]
            values['bbox_w'] = bbox[2]
            values['bbox_h'] = bbox[3]
        if error:
            values['error_message'] = error
        
        stmt = update(cls).where(cls.id == record_id).values(**values)
        await session.execute(stmt)
        await session.flush()
    
    @classmethod
    async def mark_indexed(cls, session: AsyncSession, record_ids: list[int]):
        """标记为已索引"""
        if len(record_ids) == 0:
            return
        stmt = update(cls).where(cls.id.in_(record_ids)).values(is_indexed=1)
        await session.execute(stmt)
        await session.flush()
    
    @classmethod
    async def delete_by_item_id(cls, session: AsyncSession, item_id: int):
        stmt = delete(cls).where(cls.item_id == item_id)
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def delete_by_source_image(
        cls,
        session: AsyncSession,
        item_id: int,
        source_image_id: int,
    ) -> None:
        stmt = delete(cls).where(
            cls.item_id == item_id,
            cls.source_image_id == source_image_id,
        )
        await session.execute(stmt)
        await session.flush()



class SgoItemImages(Base):
    """
    配件图片信息表
    
    表名：sgo_item_image_info
    Schema：parts
    
    字段说明：
    - item_id: 配件ID（外键关联Items表）
    - image_url: 图片URL（MinIO存储路径）
    - raw_url: 原始URL（SGO系统URL）
    - image_source: 图片来源（INQUERY=询码记录, BASEINFO=基本信息, CREATEBYSELF=手动上传）
    - is_indexed: 索引状态（0=未索引, 1=已索引, 2=初始状态）
    
    用途：
    1. 存储配件的所有图片信息
    2. 跟踪图片的索引状态（是否已提取特征并存入Milvus）
    3. 关联SGO系统的原始图片
    """
    __tablename__ = 'sgo_item_image_info'

    item_id:  Mapped[int] = mapped_column(BIGINT,nullable=False)
    image_url: Mapped[str] = mapped_column(String(200),nullable=False)
    raw_url: Mapped[str] = mapped_column(String(1000),nullable=True)
    image_source:Mapped[ImageSourceType] = mapped_column(String(200),nullable=False)
    is_indexed: Mapped[int] = mapped_column(INT,default=2) # 是否进行了索引
    is_deleted: Mapped[int] = mapped_column(INT, nullable=False, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    @classmethod
    def active_filter(cls, stmt):
        return stmt.where(cls.is_deleted == 0)

    @classmethod
    async def get_all_image(cls,session:AsyncSession):
        """
        获取所有图片记录（生成器）
        
        用途：重建索引时获取所有图片
        返回：异步生成器，逐条返回图片记录
        """
        stmt = cls.active_filter(select(cls))
        datas = await session.scalars(stmt)
        for d in datas:
            yield d
    
    @classmethod
    async def make_image_unindexed(cls,session:AsyncSession):
        """
        标记所有图片为未索引状态
        
        用途：重建索引前，将所有图片标记为未索引（is_indexed=0）
        注意：此操作会影响所有图片记录
        """
        stmt = update(cls).values(is_indexed=0)
        await session.execute(stmt)
        await session.flush()
    
    @classmethod
    async def make_image_indexed(cls,session:AsyncSession):
        """
        标记所有图片为已索引状态
        
        用途：重建索引完成后，将所有图片标记为已索引（is_indexed=1）
        注意：此操作会影响所有图片记录
        """
        stmt = update(cls).values(is_indexed=1)
        await session.execute(stmt)
        await session.flush()
       

    @classmethod
    async def get_images(cls, session: AsyncSession, item_id: int):
        stmt = cls.active_filter(select(cls).where(cls.item_id == item_id))
        datas = await session.scalars(stmt)
        for data in datas:
            yield data

    @classmethod
    async def get_first_image_by_item_id(cls, session: AsyncSession, item_id: int):
        stmt = cls.active_filter(select(cls).where(cls.item_id == item_id)).order_by(cls.id.asc()).limit(1)
        return await session.scalar(stmt)

    @classmethod
    async def create_images(cls, session: AsyncSession, item_id: int, images: list[str]):
        datas = []
        for image in images:
            data = cls(
                item_id=item_id,
                image_url=image,
                image_source=ImageSourceType.CREATEBYSELF,
                is_indexed=0
            )
            datas.append(data)

        session.add_all(datas)
        await session.flush()

    @classmethod
    async def delete_image(cls, session: AsyncSession, image_id: int):
        stmt = delete(cls).where(cls.id == image_id)
        await session.execute(stmt)

    @classmethod
    async def delete_image_by_id_list(cls, session: AsyncSession, image_id_list: list[int]):
        stmt = delete(cls).where(cls.id.in_(image_id_list))
        await session.execute(stmt)

    @classmethod
    async def indexed_image(cls, session: AsyncSession, image_id_list: list[int]):
        stmt = update(cls).where(cls.id.in_(
            image_id_list)).values(is_indexed=1)
        await session.execute(stmt)
        await session.flush()
    
    @classmethod
    async def un_indexed_image(cls, session: AsyncSession, image_id_list: list[int]):
        stmt = update(cls).where(cls.id.in_(
            image_id_list)).values(is_indexed=2)
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def get_image_by_id_list(cls, session: AsyncSession, image_id_list: list[int]):
        stmt = cls.active_filter(select(cls).where(cls.id.in_(image_id_list)))
        return  await session.scalars(stmt)


    @classmethod
    async def create_item_images(cls,session:AsyncSession,images:list[SgoItemImages]):
        if len(images) == 0:
            return 
        session.add_all(images)
        await session.flush()

    @classmethod
    async def list_item_images_by_item_id(cls,session:AsyncSession,item_id:int):
        stmt = cls.active_filter(select(cls).where(cls.item_id == item_id))
        return await session.scalars(stmt)
    

    @classmethod
    async def list_item_images_by_item_id_list(cls,session:AsyncSession,item_id_list:list[int]):
        stmt = cls.active_filter(select(cls).where(cls.item_id.in_(item_id_list)))
        return await session.scalars(stmt)

    @classmethod
    async def list_item_images_by_raw_url(
        cls,
        session: AsyncSession,
        raw_url_list: list[str],
        include_deleted: bool = False,
    ):
        stmt = select(cls).where(cls.raw_url.in_(raw_url_list))
        if not include_deleted:
            stmt = cls.active_filter(stmt)
        return await session.scalars(stmt)

    @classmethod
    def get_item_image_stmt(cls, item_id: int, image_id: int, include_deleted: bool = False):
        stmt = select(cls).where(cls.item_id == item_id, cls.id == image_id)
        if not include_deleted:
            stmt = cls.active_filter(stmt)
        return stmt

    @classmethod
    async def get_item_image(
        cls,
        session: AsyncSession,
        item_id: int,
        image_id: int,
        include_deleted: bool = False,
    ):
        stmt = cls.get_item_image_stmt(item_id, image_id, include_deleted=include_deleted)
        return await session.scalar(stmt)

    @classmethod
    def mark_deleted_stmt(cls, item_id: int, image_id: int, delete_reason: str | None = None):
        return (
            update(cls)
            .where(cls.item_id == item_id, cls.id == image_id)
            .values(
                is_deleted=1,
                deleted_at=datetime.now(),
                delete_reason=delete_reason,
            )
        )

    @classmethod
    async def mark_deleted(
        cls,
        session: AsyncSession,
        item_id: int,
        image_id: int,
        delete_reason: str | None = None,
    ) -> None:
        await session.execute(cls.mark_deleted_stmt(item_id, image_id, delete_reason))
        await session.flush()
    

# class IndexedImage(Base):
#     __tablename__ = 'indexed_item_image_info'
#     item_id:  Mapped[int] = mapped_column(BIGINT,nullable=False)
#     image_url: Mapped[str] = mapped_column(String(200),nullable=False)
#     source_image_id: Mapped[int] = mapped_column(BIGINT,nullable=False)
#     index_id: Mapped[int] =  mapped_column(BIGINT,nullable=False)

#     @classmethod
#     async def create_indexed_image(cls,session:AsyncSession,images: list[IndexedImage]):
#         if len(images) == 0:
#             return 
#         session.add(images)
#         await session.flush()

#     @classmethod
#     async def list_indexed_image(cls,session:AsyncSession,item_id:int):
#         stmt = select(cls).where(cls.item_id == item_id)
#         return await session.scalars(stmt)
    
#     @classmethod 
#     async def list_indexed_image_set(cls,session:AsyncSession,item_id:int):
#         indexed_images = await cls.list_indexed_image(session,item_id)
#         indexed_images_set = set()
#         for img in indexed_images:
#             indexed_images_set.add(img.image_url)
#         return indexed_images_set

#     @classmethod 
#     async def delete_indexed_image(cls,session:AsyncSession,index_id_list:list[int]):
#         if len(index_id_list) == 0:
#             return 
#         stmt = delete(cls).where(cls.index_id.in_(index_id_list))
#         session.execute(stmt)
#         await session.flush()
    
