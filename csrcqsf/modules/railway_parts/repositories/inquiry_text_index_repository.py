"""询码语义索引任务持久化访问。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update

from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.models.orm.inquiry_text_index_task import (
    ACTIVE_INQUIRY_TEXT_INDEX_TASK_STATUSES,
    InquiryTextIndexFailure,
    InquiryTextIndexTask,
)


def _record_to_dict(record) -> dict[str, Any]:
    return {
        column.name: getattr(record, column.name)
        for column in record.__table__.columns
    }


class InquiryTextIndexTaskRepository:
    async def create(self, **values) -> dict[str, Any]:
        async with SessionLocal() as session:
            record = InquiryTextIndexTask(**values)
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return _record_to_dict(record)

    async def get(self, task_id: str) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            record = await session.scalar(
                select(InquiryTextIndexTask).where(
                    InquiryTextIndexTask.task_id == task_id
                )
            )
            return _record_to_dict(record) if record is not None else None

    async def update(self, task_id: str, **values) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            record = await session.scalar(
                select(InquiryTextIndexTask).where(
                    InquiryTextIndexTask.task_id == task_id
                )
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
        # 条件更新保证 worker 完成、取消请求和服务停止只能写入一个合法终态。
        async with SessionLocal() as session:
            result = await session.execute(
                update(InquiryTextIndexTask)
                .where(
                    InquiryTextIndexTask.task_id == task_id,
                    InquiryTextIndexTask.status.in_(from_statuses),
                )
                .values(**values)
            )
            if result.rowcount != 1:
                await session.rollback()
                return None
            await session.commit()
            record = await session.scalar(
                select(InquiryTextIndexTask).where(
                    InquiryTextIndexTask.task_id == task_id
                )
            )
            return _record_to_dict(record) if record is not None else None

    async def claim_next_pending(self) -> dict[str, Any] | None:
        # 行锁跳过已被领取任务，为未来多 worker 部署保留安全的 FIFO 领取语义。
        async with SessionLocal() as session:
            record = await session.scalar(
                select(InquiryTextIndexTask)
                .where(InquiryTextIndexTask.status == "pending")
                .order_by(InquiryTextIndexTask.time_created.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if record is None:
                await session.rollback()
                return None
            now = datetime.now()
            record.status = "running"
            record.started_at = now
            record.heartbeat_at = now
            await session.commit()
            await session.refresh(record)
            return _record_to_dict(record)

    async def list(
        self,
        *,
        page: int = 1,
        per_page: int = 20,
        status: str = "all",
        task_scope: str = "all",
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(InquiryTextIndexTask)
        if status == "active":
            stmt = stmt.where(
                InquiryTextIndexTask.status.in_(ACTIVE_INQUIRY_TEXT_INDEX_TASK_STATUSES)
            )
        elif status != "all":
            stmt = stmt.where(InquiryTextIndexTask.status == status)
        if task_scope != "all":
            stmt = stmt.where(InquiryTextIndexTask.task_scope == task_scope)
        async with SessionLocal() as session:
            total = int(
                await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            )
            records = await session.scalars(
                stmt.order_by(InquiryTextIndexTask.time_created.desc())
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            return [_record_to_dict(record) for record in records], total

    async def replace_failures(self, task_id: str, failures: list[dict]) -> None:
        async with SessionLocal() as session:
            await session.execute(
                delete(InquiryTextIndexFailure).where(
                    InquiryTextIndexFailure.task_id == task_id
                )
            )
            session.add_all(
                InquiryTextIndexFailure(task_id=task_id, **failure)
                for failure in failures
            )
            await session.commit()

    async def append_failures(self, task_id: str, failures: list[dict]) -> None:
        if not failures:
            return
        async with SessionLocal() as session:
            session.add_all(
                InquiryTextIndexFailure(task_id=task_id, **failure)
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
        stmt = select(InquiryTextIndexFailure).where(
            InquiryTextIndexFailure.task_id == task_id
        )
        async with SessionLocal() as session:
            total = int(
                await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            )
            records = await session.scalars(
                stmt.order_by(InquiryTextIndexFailure.time_created.asc())
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            return [_record_to_dict(record) for record in records], total

    async def summarize_failure_types(
        self,
        task_id: str,
        *,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """按异常类型聚合失败明细，返回 TOP-N 类型及其条数与一条示例消息。

        用于把“为什么失败”直接呈现到任务 error_message，避免翻看海量明细。
        """
        async with SessionLocal() as session:
            rows = await session.execute(
                select(
                    InquiryTextIndexFailure.error_type,
                    InquiryTextIndexFailure.stage,
                    func.count().label("count"),
                    func.min(InquiryTextIndexFailure.error_message).label("sample_message"),
                )
                .where(InquiryTextIndexFailure.task_id == task_id)
                .group_by(
                    InquiryTextIndexFailure.error_type,
                    InquiryTextIndexFailure.stage,
                )
                .order_by(func.count().desc(), InquiryTextIndexFailure.error_type.asc())
                .limit(max(1, int(limit)))
            )
            return [
                {
                    "error_type": str(row.error_type),
                    "stage": str(row.stage),
                    "count": int(row.count),
                    "sample_message": row.sample_message,
                }
                for row in rows
            ]

    async def mark_missing_active_task_interrupted(
        self,
        task_id: str,
    ) -> dict[str, Any] | None:
        now = datetime.now()
        return await self.transition(
            task_id,
            ACTIVE_INQUIRY_TEXT_INDEX_TASK_STATUSES,
            status="interrupted",
            current_inquiry_id=None,
            completed_at=now,
            heartbeat_at=now,
            error_message="活动任务在当前服务进程中不存在",
        )
