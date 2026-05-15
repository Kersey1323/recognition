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
    storage_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="remote")
    local_status: Mapped[str] = mapped_column(String(50), nullable=False, default="initiated")
    remote_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    local_dir: Mapped[str] = mapped_column(String(700), nullable=True)
    merged_file_path: Mapped[str] = mapped_column(String(700), nullable=True)
    remote_upload_id: Mapped[str] = mapped_column(String(200), nullable=True, index=True)
    remote_object_name: Mapped[str] = mapped_column(String(500), nullable=True)
    remote_video_path: Mapped[str] = mapped_column(String(700), nullable=True)
    sync_attempts: Mapped[int] = mapped_column(INT, nullable=False, default=0)
    last_sync_error: Mapped[str] = mapped_column(String(1000), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
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

    @classmethod
    async def list_local_sessions_pending_remote_sync(cls, session: AsyncSession):
        stmt = (
            select(cls)
            .where(
                cls.storage_mode == "local",
                cls.local_status == "completed",
                cls.remote_status.in_(["pending", "failed", "syncing"]),
            )
            .order_by(cls.id.asc())
        )
        result = await session.scalars(stmt)
        return list(result)

    @classmethod
    async def update_sync_state(cls, session: AsyncSession, session_id: int, **values):
        stmt = update(cls).where(cls.id == session_id).values(**values)
        await session.execute(stmt)
        await session.flush()
