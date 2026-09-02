"""Viewer360 持久化任务、当前发布版本和失败明细。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import BIGINT, Boolean, DateTime, Index, Integer, JSON, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from csrcqsf.infra.db.main_db import Base, PlainBase, SessionLocal


class Viewer360TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


ACTIVE_VIEWER360_TASK_STATUSES = (
    Viewer360TaskStatus.PENDING.value,
    Viewer360TaskStatus.RUNNING.value,
    Viewer360TaskStatus.CANCELLING.value,
)


def classify_viewer360_startup_recovery(status: str) -> Viewer360TaskStatus:
    normalized = Viewer360TaskStatus(status)
    if normalized.value in ACTIVE_VIEWER360_TASK_STATUSES:
        return Viewer360TaskStatus.INTERRUPTED
    return normalized


class Viewer360Task(Base):
    __tablename__ = "viewer360_task"
    __table_args__ = (
        Index("ix_viewer360_task_status_created", "status", "time_created"),
        Index("ix_viewer360_task_item_created", "item_id", "time_created"),
        Index("ix_viewer360_task_root_created", "root_task_id", "time_created"),
    )

    task_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    root_task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    retry_from_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    item_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    source_video_object: Mapped[str] = mapped_column(String(700), nullable=False)
    source_video_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rebuild_existing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retry_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    retry_rows_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    retry_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    current_stage: Mapped[str] = mapped_column(String(30), nullable=False, default="preparing")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_frames: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_frames: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reused_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_states_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    output_bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    output_prefix: Mapped[str] = mapped_column(String(700), nullable=False)
    manifest_object: Mapped[str | None] = mapped_column(String(700), nullable=True)
    amount_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pipeline_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @classmethod
    async def recover_active_tasks(cls, session: AsyncSession) -> int:
        result = await session.scalars(select(cls).where(cls.status.in_(ACTIVE_VIEWER360_TASK_STATUSES)))
        records = list(result)
        now = datetime.now()
        for record in records:
            # 后台协程不能跨进程恢复，旧任务只转为可重试中断态，当前发布版本不受影响。
            record.status = Viewer360TaskStatus.INTERRUPTED.value
            record.current_stage = "cleanup"
            record.error_message = "服务重启，Viewer360 任务执行上下文已丢失"
            record.completed_at = now
            record.heartbeat_at = now
        await session.flush()
        return len(records)


class ItemViewer360Current(PlainBase):
    __tablename__ = "item_viewer360_current"

    item_id: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    manifest_object: Mapped[str] = mapped_column(String(700), nullable=False)
    amount_x: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_y: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    time_created: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    time_updated: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now,
        onupdate=datetime.now,
    )


class Viewer360TaskFailure(Base):
    __tablename__ = "viewer360_task_failure"
    __table_args__ = (
        Index("ix_viewer360_failure_task_created", "task_id", "time_created"),
    )

    task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)


async def recover_viewer360_tasks() -> dict[str, int]:
    async with SessionLocal() as session:
        interrupted = await Viewer360Task.recover_active_tasks(session)
        await session.commit()
        return {"interrupted": interrupted}
