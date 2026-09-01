"""V2 图片索引任务的持久化状态与启动恢复规则。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import BIGINT, Boolean, DateTime, Index, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from csrcqsf.infra.db.main_db import Base, SessionLocal


class IndexRebuildTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class IndexRebuildTaskScope(str, Enum):
    SINGLE = "single"
    BATCH = "batch"


ACTIVE_INDEX_TASK_STATUSES = (
    IndexRebuildTaskStatus.PENDING,
    IndexRebuildTaskStatus.RUNNING,
    IndexRebuildTaskStatus.CANCELLING,
)


def classify_startup_recovery(
    *,
    status: str,
    total_items: int,
    completed_item_count: int,
) -> IndexRebuildTaskStatus:
    """根据持久化的配件级检查点判定重启后的任务终态。"""
    normalized_status = IndexRebuildTaskStatus(status)
    if normalized_status not in ACTIVE_INDEX_TASK_STATUSES:
        return normalized_status
    if total_items > 0 and completed_item_count >= total_items:
        return IndexRebuildTaskStatus.SUCCESS
    return IndexRebuildTaskStatus.INTERRUPTED


class IndexRebuildTask(Base):
    """记录单配件或批量索引任务，支持取消、重试和进度回看。"""
    __tablename__ = "index_rebuild_task"
    __table_args__ = (
        Index("ix_index_rebuild_task_status_created", "status", "time_created"),
        Index("ix_index_rebuild_task_scope_status", "task_scope", "status"),
        Index("ix_index_rebuild_task_item_created", "item_id", "time_created"),
        Index("ix_index_rebuild_task_root_created", "root_task_id", "time_created"),
    )

    task_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    root_task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    retry_from_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    task_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    item_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rebuild_existing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=IndexRebuildTaskStatus.PENDING,
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    segmented_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallback_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_item_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    last_completed_item_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    last_completed_item_created_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    estimated_remaining_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    @classmethod
    async def recover_active_tasks(cls, session: AsyncSession) -> dict[str, int]:
        # 后台协程无法跨进程恢复；只有全部配件检查点完成的任务可补记为成功。
        result = await session.scalars(select(cls).where(cls.status.in_(ACTIVE_INDEX_TASK_STATUSES)))
        records = list(result)
        recovered = {"success": 0, "interrupted": 0}
        now = datetime.now()
        for record in records:
            target = classify_startup_recovery(
                status=record.status,
                total_items=record.total_items,
                completed_item_count=record.completed_item_count,
            )
            record.status = target.value
            record.current_item_id = None
            record.completed_at = now
            record.heartbeat_at = now
            if target == IndexRebuildTaskStatus.SUCCESS:
                # 最后一个配件检查点已持久化时，重启仅丢失终态写入，可安全补记成功。
                record.progress = 100
                record.processed_items = record.total_items
                record.estimated_remaining_seconds = 0
                recovered["success"] += 1
            else:
                record.error_message = "服务重启，原索引任务执行上下文已丢失"
                record.estimated_remaining_seconds = None
                recovered["interrupted"] += 1
        await session.flush()
        return recovered


async def recover_index_rebuild_tasks() -> dict[str, int]:
    async with SessionLocal() as session:
        recovered = await IndexRebuildTask.recover_active_tasks(session)
        await session.commit()
        return recovered
