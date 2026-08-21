"""Database access for persistent SGO synchronization tasks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update

from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.models.orm.sgo_sync_task import (
    ACTIVE_SGO_SYNC_TASK_STATUSES,
    SgoSyncTask,
    SgoSyncTaskFailure,
)


def _record_to_dict(record) -> dict[str, Any]:
    return {
        column.name: getattr(record, column.name)
        for column in record.__table__.columns
    }


class SgoSyncTaskRepository:
    async def create(self, **values) -> dict[str, Any]:
        async with SessionLocal() as session:
            record = SgoSyncTask(**values)
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return _record_to_dict(record)

    async def get(self, task_id: str) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            record = await session.scalar(
                select(SgoSyncTask).where(SgoSyncTask.task_id == task_id)
            )
            return _record_to_dict(record) if record is not None else None

    async def has_active(self) -> bool:
        async with SessionLocal() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(SgoSyncTask)
                .where(SgoSyncTask.status.in_(ACTIVE_SGO_SYNC_TASK_STATUSES))
            )
            return bool(count)

    async def update(self, task_id: str, **values) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            record = await session.scalar(
                select(SgoSyncTask).where(SgoSyncTask.task_id == task_id)
            )
            if record is None:
                return None
            for field, value in values.items():
                setattr(record, field, value)
            await session.commit()
            await session.refresh(record)
            return _record_to_dict(record)

    async def transition(
        self,
        task_id: str,
        from_statuses: tuple[str, ...],
        **values,
    ) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            result = await session.execute(
                update(SgoSyncTask)
                .where(
                    SgoSyncTask.task_id == task_id,
                    SgoSyncTask.status.in_(from_statuses),
                )
                .values(**values)
            )
            if result.rowcount != 1:
                await session.rollback()
                return None
            await session.commit()
            record = await session.scalar(
                select(SgoSyncTask).where(SgoSyncTask.task_id == task_id)
            )
            return _record_to_dict(record) if record is not None else None

    async def list(
        self,
        *,
        page: int = 1,
        per_page: int = 20,
        status: str = "all",
        task_type: str = "all",
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(SgoSyncTask)
        if status == "active":
            stmt = stmt.where(SgoSyncTask.status.in_(ACTIVE_SGO_SYNC_TASK_STATUSES))
        elif status != "all":
            stmt = stmt.where(SgoSyncTask.status == status)
        if task_type != "all":
            stmt = stmt.where(SgoSyncTask.task_type == task_type)

        async with SessionLocal() as session:
            total = int(
                (await session.scalar(select(func.count()).select_from(stmt.subquery())))
                or 0
            )
            records = await session.scalars(
                stmt.order_by(SgoSyncTask.time_created.desc())
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            return [_record_to_dict(record) for record in records], total

    async def replace_failures(self, task_id: str, failures: list[dict]) -> None:
        async with SessionLocal() as session:
            await session.execute(
                delete(SgoSyncTaskFailure).where(
                    SgoSyncTaskFailure.task_id == task_id
                )
            )
            session.add_all(
                SgoSyncTaskFailure(task_id=task_id, **failure)
                for failure in failures
            )
            await session.commit()

    async def append_failures(self, task_id: str, failures: list[dict]) -> None:
        if not failures:
            return
        async with SessionLocal() as session:
            session.add_all(
                SgoSyncTaskFailure(task_id=task_id, **failure)
                for failure in failures
            )
            await session.commit()

    async def list_failures(
        self,
        task_id: str,
        *,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(SgoSyncTaskFailure).where(
            SgoSyncTaskFailure.task_id == task_id
        )
        async with SessionLocal() as session:
            total = int(
                (await session.scalar(select(func.count()).select_from(stmt.subquery())))
                or 0
            )
            records = await session.scalars(
                stmt.order_by(SgoSyncTaskFailure.time_created.asc())
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            return [_record_to_dict(record) for record in records], total

    async def mark_missing_active_task_interrupted(
        self,
        task_id: str,
    ) -> dict[str, Any] | None:
        now = datetime.now()
        return await self.transition(
            task_id,
            ACTIVE_SGO_SYNC_TASK_STATUSES,
            status="interrupted",
            current_item_id=None,
            completed_at=now,
            heartbeat_at=now,
            error_message="活动任务在当前服务进程中不存在",
            estimated_remaining_seconds=None,
        )
