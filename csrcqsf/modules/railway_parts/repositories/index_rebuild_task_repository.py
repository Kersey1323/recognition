"""V2 图片索引任务的持久化访问层。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update

from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.models.orm.index_rebuild_task import (
    ACTIVE_INDEX_TASK_STATUSES,
    IndexRebuildTask,
)


def task_record_to_dict(record: IndexRebuildTask) -> dict[str, Any]:
    return {
        column.name: getattr(record, column.name)
        for column in IndexRebuildTask.__table__.columns
    }


class IndexRebuildTaskRepository:
    async def create(self, **values) -> dict[str, Any]:
        async with SessionLocal() as session:
            record = IndexRebuildTask(**values)
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return task_record_to_dict(record)

    async def update(self, task_id: str, **values) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            record = await session.scalar(
                select(IndexRebuildTask).where(IndexRebuildTask.task_id == task_id)
            )
            if record is None:
                return None
            for field, value in values.items():
                setattr(record, field, value)
            await session.commit()
            await session.refresh(record)
            return task_record_to_dict(record)

    async def transition(
        self,
        task_id: str,
        from_statuses: tuple[str, ...],
        **values,
    ) -> dict[str, Any] | None:
        """仅在允许的源状态下原子更新任务，避免取消与完成互相覆盖。"""
        async with SessionLocal() as session:
            result = await session.execute(
                update(IndexRebuildTask)
                .where(
                    IndexRebuildTask.task_id == task_id,
                    IndexRebuildTask.status.in_(from_statuses),
                )
                .values(**values)
            )
            if result.rowcount != 1:
                await session.rollback()
                return None
            await session.commit()
            record = await session.scalar(
                select(IndexRebuildTask).where(IndexRebuildTask.task_id == task_id)
            )
            return task_record_to_dict(record) if record is not None else None

    async def get(self, task_id: str) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            record = await session.scalar(
                select(IndexRebuildTask).where(IndexRebuildTask.task_id == task_id)
            )
            return task_record_to_dict(record) if record is not None else None

    async def list(
        self,
        *,
        page: int = 1,
        per_page: int = 20,
        status: str = "all",
        task_scope: str = "all",
        item_id: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(IndexRebuildTask)
        if status == "active":
            stmt = stmt.where(IndexRebuildTask.status.in_(ACTIVE_INDEX_TASK_STATUSES))
        elif status != "all":
            stmt = stmt.where(IndexRebuildTask.status == status)
        if task_scope != "all":
            stmt = stmt.where(IndexRebuildTask.task_scope == task_scope)
        if item_id is not None:
            stmt = stmt.where(IndexRebuildTask.item_id == item_id)

        async with SessionLocal() as session:
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = int((await session.scalar(count_stmt)) or 0)
            result = await session.scalars(
                stmt.order_by(IndexRebuildTask.time_created.desc())
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            return [task_record_to_dict(record) for record in result], total

    async def mark_missing_active_task_interrupted(
        self,
        task_id: str,
    ) -> dict[str, Any] | None:
        now = datetime.now()
        return await self.update(
            task_id,
            status="interrupted",
            current_item_id=None,
            completed_at=now,
            heartbeat_at=now,
            error_message="活动任务在当前服务进程中不存在",
            estimated_remaining_seconds=None,
        )
