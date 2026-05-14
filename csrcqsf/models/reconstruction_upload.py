from __future__ import annotations

from datetime import datetime

from sqlalchemy import BIGINT, DateTime, Float, INT, String, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from csrcqsf.data.pg import Base


class ReconstructionVideoUploadSession(Base):
    __tablename__ = "reconstruction_video_upload_session"

    item_id: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)
    bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    object_name: Mapped[str] = mapped_column(String(500), nullable=False)
    video_path: Mapped[str] = mapped_column(String(700), nullable=False)
    upload_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(BIGINT, nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="application/octet-stream",
    )
    part_size: Mapped[int] = mapped_column(BIGINT, nullable=False)
    total_parts: Mapped[int] = mapped_column(INT, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=True)
    length: Mapped[float] = mapped_column(Float, nullable=True)
    width: Mapped[float] = mapped_column(Float, nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="initiated")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    @classmethod
    async def create_session(
        cls,
        session: AsyncSession,
        record: "ReconstructionVideoUploadSession",
    ) -> "ReconstructionVideoUploadSession":
        session.add(record)
        await session.flush()
        return record

    @classmethod
    async def get_by_id(cls, session: AsyncSession, session_id: int):
        stmt = select(cls).where(cls.id == session_id)
        return await session.scalar(stmt)

    @classmethod
    async def get_active_by_item_id(cls, session: AsyncSession, item_id: int):
        stmt = (
            select(cls)
            .where(cls.item_id == item_id, cls.status == "initiated")
            .order_by(cls.id.desc())
        )
        return await session.scalar(stmt)

    @classmethod
    async def mark_completed(
        cls,
        session: AsyncSession,
        session_id: int,
        completed_at: datetime,
    ):
        stmt = (
            update(cls)
            .where(cls.id == session_id)
            .values(status="completed", completed_at=completed_at)
        )
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def mark_aborted(cls, session: AsyncSession, session_id: int):
        stmt = update(cls).where(cls.id == session_id).values(status="aborted")
        await session.execute(stmt)
        await session.flush()
