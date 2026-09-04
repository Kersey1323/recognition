"""询码语义索引任务及失败明细。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import BIGINT, DateTime, Index, Integer, JSON, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from csrcqsf.infra.db.main_db import Base, SessionLocal


class InquiryTextIndexTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class InquiryTextIndexTaskScope(str, Enum):
    INCREMENTAL = "incremental"
    FULL = "full"


ACTIVE_INQUIRY_TEXT_INDEX_TASK_STATUSES = (
    InquiryTextIndexTaskStatus.PENDING.value,
    InquiryTextIndexTaskStatus.RUNNING.value,
    InquiryTextIndexTaskStatus.CANCELLING.value,
)


def classify_inquiry_text_index_startup_recovery(status: str) -> str:
    if status in ACTIVE_INQUIRY_TEXT_INDEX_TASK_STATUSES:
        return InquiryTextIndexTaskStatus.INTERRUPTED.value
    return status


class InquiryTextIndexTask(Base):
    """记录询码描述语义索引的全量或增量构建过程。"""
    __tablename__ = "inquiry_text_index_task"
    __table_args__ = (
        Index("ix_inquiry_text_index_task_status_created", "status", "time_created"),
        Index("ix_inquiry_text_index_task_scope_created", "task_scope", "time_created"),
        Index("ix_inquiry_text_index_task_root_created", "root_task_id", "time_created"),
        Index("ix_inquiry_text_index_task_source_sync", "source_sync_task_id"),
    )

    task_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    root_task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    retry_from_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_sync_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_sync_task_ids_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    trigger_source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="manual",
    )
    # 增量任务保存来源同步任务，便于从同步记录追溯后续语义索引结果。
    task_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    history_ids_json: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_inquiry_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    @classmethod
    async def recover_active_tasks(cls, session: AsyncSession) -> dict[str, int]:
        records = list(
            await session.scalars(
                select(cls).where(cls.status.in_(ACTIVE_INQUIRY_TEXT_INDEX_TASK_STATUSES))
            )
        )
        interrupted = 0
        now = datetime.now()
        for record in records:
            target = classify_inquiry_text_index_startup_recovery(record.status)
            if target == record.status:
                continue
            # 进程内执行上下文无法跨服务重启恢复，持久化记录保留为可重试终态。
            record.status = target
            record.current_inquiry_id = None
            record.completed_at = now
            record.heartbeat_at = now
            record.error_message = "服务重启，原询码语义索引任务执行上下文已丢失"
            interrupted += 1
        await session.flush()
        return {"interrupted": interrupted}


class InquiryTextIndexFailure(Base):
    """按询码样本保存失败阶段，支持仅重试失败数据。"""
    __tablename__ = "inquiry_text_index_failure"
    __table_args__ = (
        Index("ix_inquiry_text_index_failure_task_created", "task_id", "time_created"),
        Index("ix_inquiry_text_index_failure_task_history", "task_id", "history_id"),
    )

    task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    history_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    inquiry_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    item_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)


async def recover_inquiry_text_index_tasks() -> dict[str, int]:
    async with SessionLocal() as session:
        recovered = await InquiryTextIndexTask.recover_active_tasks(session)
        await session.commit()
        return recovered
