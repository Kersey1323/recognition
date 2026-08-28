"""Persistent lifecycle records for SGO synchronization tasks."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Index, Integer, JSON, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from csrcqsf.infra.db.main_db import Base, SessionLocal


class SgoSyncTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


ACTIVE_SGO_SYNC_TASK_STATUSES = (
    SgoSyncTaskStatus.PENDING.value,
    SgoSyncTaskStatus.RUNNING.value,
    SgoSyncTaskStatus.CANCELLING.value,
)


def classify_sgo_sync_startup_recovery(status: str) -> str:
    if status in ACTIVE_SGO_SYNC_TASK_STATUSES:
        return SgoSyncTaskStatus.INTERRUPTED.value
    return status


class SgoSyncTask(Base):
    __tablename__ = "sgo_sync_task"
    __table_args__ = (
        Index("ix_sgo_sync_task_status_created", "status", "time_created"),
        Index("ix_sgo_sync_task_type_created", "task_type", "time_created"),
        Index("ix_sgo_sync_task_root_created", "root_task_id", "time_created"),
    )

    task_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    root_task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    retry_from_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    task_params_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SgoSyncTaskStatus.PENDING.value,
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    synced_image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_item_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    estimated_remaining_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    semantic_index_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    semantic_index_warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    @classmethod
    async def recover_active_tasks(cls, session: AsyncSession) -> dict[str, int]:
        records = list(
            await session.scalars(
                select(cls).where(cls.status.in_(ACTIVE_SGO_SYNC_TASK_STATUSES))
            )
        )
        interrupted = 0
        now = datetime.now()
        for record in records:
            target = classify_sgo_sync_startup_recovery(record.status)
            if target == record.status:
                continue
            record.status = target
            record.current_item_id = None
            record.completed_at = now
            record.heartbeat_at = now
            record.error_message = "服务重启，原 SGO 同步任务执行上下文已丢失"
            record.estimated_remaining_seconds = None
            interrupted += 1
        await session.flush()
        return {"interrupted": interrupted}


class SgoSyncTaskFailure(Base):
    __tablename__ = "sgo_sync_task_failure"
    __table_args__ = (
        Index("ix_sgo_sync_task_failure_task_created", "task_id", "time_created"),
        Index("ix_sgo_sync_task_failure_task_item", "task_id", "item_id"),
    )

    task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    item_id: Mapped[str] = mapped_column(String(100), nullable=False)
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)


async def recover_sgo_sync_tasks() -> dict[str, int]:
    async with SessionLocal() as session:
        recovered = await SgoSyncTask.recover_active_tasks(session)
        await session.commit()
        return recovered
