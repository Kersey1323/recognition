"""SGO 同步任务及失败明细的数据访问层。"""

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
from csrcqsf.modules.sgo.error_codes import failure_error_code


def _record_to_dict(record) -> dict[str, Any]:
    return {
        column.name: getattr(record, column.name)
        for column in record.__table__.columns
    }


def _with_error_code(failure: dict) -> dict:
    return {
        **failure,
        "error_code": failure_error_code(
            failure["stage"], failure["error_type"], failure["error_message"]
        ),
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
        # 状态条件写入提供轻量 CAS，取消和完成并发发生时只有合法一方生效。
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

    async def count_by_status(self, task_type: str) -> dict[str, int]:
        async with SessionLocal() as session:
            rows = await session.execute(
                select(SgoSyncTask.status, func.count())
                .where(SgoSyncTask.task_type == task_type)
                .group_by(SgoSyncTask.status)
            )
            return {status: int(count) for status, count in rows}

    async def replace_failures(self, task_id: str, failures: list[dict]) -> None:
        # 非增量执行器在任务结束时用完整失败集合覆盖旧明细。
        async with SessionLocal() as session:
            await session.execute(
                delete(SgoSyncTaskFailure).where(
                    SgoSyncTaskFailure.task_id == task_id
                )
            )
            session.add_all(
                SgoSyncTaskFailure(task_id=task_id, **_with_error_code(failure))
                for failure in failures
            )
            await session.commit()

    async def append_failures(self, task_id: str, failures: list[dict]) -> None:
        # 图片全量同步按批追加，避免长任务把数万条失败明细积压在内存。
        if not failures:
            return
        async with SessionLocal() as session:
            session.add_all(
                SgoSyncTaskFailure(task_id=task_id, **_with_error_code(failure))
                for failure in failures
            )
            await session.commit()

    async def list_failures(
        self,
        task_id: str,
        *,
        page: int = 1,
        per_page: int = 20,
        stage: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        error_code: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(SgoSyncTaskFailure).where(
            SgoSyncTaskFailure.task_id == task_id
        )
        if stage is not None:
            stmt = stmt.where(SgoSyncTaskFailure.stage == stage)
        if error_type is not None:
            stmt = stmt.where(SgoSyncTaskFailure.error_type == error_type)
        if error_message is not None:
            stmt = stmt.where(SgoSyncTaskFailure.error_message == error_message)
        if error_code is not None:
            stmt = stmt.where(SgoSyncTaskFailure.error_code == error_code)
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

    async def summarize_failures(self, task_id: str) -> list[dict[str, Any]]:
        """按稳定业务错误码聚合；消息和异常类型仅供诊断展示。"""
        async with SessionLocal() as session:
            rows = await session.execute(
                select(
                    SgoSyncTaskFailure.error_code,
                    func.min(SgoSyncTaskFailure.stage).label("stage"),
                    func.min(SgoSyncTaskFailure.error_type).label("error_type"),
                    func.min(SgoSyncTaskFailure.error_message).label("error_message"),
                    func.count().label("count"),
                )
                .where(SgoSyncTaskFailure.task_id == task_id)
                .group_by(
                    SgoSyncTaskFailure.error_code,
                )
                .order_by(
                    func.count().desc(),
                    SgoSyncTaskFailure.error_code.asc(),
                )
            )
            return [
                {
                    "error_code": str(row.error_code),
                    "stage": str(row.stage),
                    "error_type": str(row.error_type),
                    "error_message": str(row.error_message),
                    "count": int(row.count),
                }
                for row in rows
            ]

    async def mark_missing_active_task_interrupted(
        self,
        task_id: str,
    ) -> dict[str, Any] | None:
        # 数据库显示活动但当前进程没有协程时，任务已无法取消或继续，只能转中断。
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
