"""Viewer360 任务与当前发布版本的事务访问层。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import case, delete, func, literal_column, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert

from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.models.orm.item import Items
from csrcqsf.models.orm.viewer360_task import (
    ACTIVE_VIEWER360_TASK_STATUSES,
    ItemViewer360Current,
    Viewer360Task,
    Viewer360TaskFailure,
)


def viewer360_task_to_dict(record: Viewer360Task) -> dict[str, Any]:
    return {column.name: getattr(record, column.name) for column in record.__table__.columns}


def _current_to_dict(record: ItemViewer360Current) -> dict[str, Any]:
    return {column.name: getattr(record, column.name) for column in record.__table__.columns}


def _failure_to_dict(record: Viewer360TaskFailure) -> dict[str, Any]:
    return {column.name: getattr(record, column.name) for column in record.__table__.columns}


class Viewer360Repository:
    async def get_item_source(self, item_id: int) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            item = await session.scalar(select(Items).where(Items.id == item_id))
            if item is None:
                return None
            return {
                "item_id": item.id,
                "item_name": item.item_name,
                "source_video_object": item.source_video_path,
                "source_video_updated_at": item.source_video_updated_at,
            }

    async def get_item_brief(self, item_id: int) -> dict[str, Any] | None:
        """返回配件的展示信息（名称/编码），供任务类接口随响应返回。"""
        async with SessionLocal() as session:
            item = await session.scalar(select(Items).where(Items.id == item_id))
            if item is None:
                return None
            return {
                "item_name": item.item_name,
                "item_code": item.item_code,
            }

    async def create_task(self, **values) -> dict[str, Any]:
        async with SessionLocal() as session:
            record = Viewer360Task(**values)
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return viewer360_task_to_dict(record)

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            record = await session.scalar(select(Viewer360Task).where(Viewer360Task.task_id == task_id))
            return viewer360_task_to_dict(record) if record is not None else None

    async def find_active_by_item(self, item_id: int) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            record = await session.scalar(
                select(Viewer360Task)
                .where(
                    Viewer360Task.item_id == item_id,
                    Viewer360Task.status.in_(ACTIVE_VIEWER360_TASK_STATUSES),
                )
                .order_by(Viewer360Task.time_created.desc())
                .limit(1)
            )
            return viewer360_task_to_dict(record) if record is not None else None

    async def update_task(self, task_id: str, **values) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            record = await session.scalar(select(Viewer360Task).where(Viewer360Task.task_id == task_id))
            if record is None:
                return None
            for key, value in values.items():
                setattr(record, key, value)
            await session.commit()
            await session.refresh(record)
            return viewer360_task_to_dict(record)

    async def transition_task(
        self,
        task_id: str,
        from_statuses: tuple[str, ...],
        **values,
    ) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            result = await session.execute(
                update(Viewer360Task)
                .where(
                    Viewer360Task.task_id == task_id,
                    Viewer360Task.status.in_(from_statuses),
                )
                .values(**values)
            )
            if result.rowcount != 1:
                await session.rollback()
                return None
            await session.commit()
            record = await session.scalar(select(Viewer360Task).where(Viewer360Task.task_id == task_id))
            return viewer360_task_to_dict(record) if record is not None else None

    async def reset_task_for_retry(
        self,
        task_id: str,
        from_statuses: tuple[str, ...],
        **values,
    ) -> dict[str, Any] | None:
        """原地恢复终态任务，并清除上一轮失败明细。"""
        async with SessionLocal() as session:
            record = await session.scalar(
                select(Viewer360Task)
                .where(Viewer360Task.task_id == task_id)
                .with_for_update()
            )
            if record is None or record.status not in from_statuses:
                await session.rollback()
                return None
            for key, value in values.items():
                setattr(record, key, value)
            # 同一个 task_id 代表当前一次执行，重试后失败列表只展示本轮问题。
            await session.execute(
                delete(Viewer360TaskFailure).where(
                    Viewer360TaskFailure.task_id == task_id
                )
            )
            await session.commit()
            await session.refresh(record)
            return viewer360_task_to_dict(record)

    async def list_tasks(
        self,
        *,
        page: int,
        per_page: int,
        status: str,
        item_id: int | None,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(Viewer360Task)
        if status == "active":
            stmt = stmt.where(Viewer360Task.status.in_(ACTIVE_VIEWER360_TASK_STATUSES))
        elif status != "all":
            stmt = stmt.where(Viewer360Task.status == status)
        if item_id is not None:
            stmt = stmt.where(Viewer360Task.item_id == item_id)
        async with SessionLocal() as session:
            total = int((await session.scalar(select(func.count()).select_from(stmt.subquery()))) or 0)
            records = await session.scalars(
                stmt.order_by(Viewer360Task.time_created.desc())
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            tasks = [viewer360_task_to_dict(record) for record in records]
            # 列表页需要直接展示配件名称与编码：按本页任务涉及的配件 ID 批量补齐。
            item_ids = {task["item_id"] for task in tasks if task.get("item_id") is not None}
            if item_ids:
                items = (
                    await session.scalars(select(Items).where(Items.id.in_(item_ids)))
                ).all()
                item_map = {item.id: item for item in items}
                for task in tasks:
                    item = item_map.get(task["item_id"])
                    task["item_name"] = item.item_name if item is not None else None
                    task["item_code"] = item.item_code if item is not None else None
            return tasks, total

    async def summarize_tasks(self) -> dict[str, float | int | None]:
        """按 Viewer360 状态汇总任务，并统计成功任务最近一次执行耗时。"""
        running_statuses = ("pending", "running", "cancelling")
        failed_statuses = ("failed", "interrupted")
        elapsed_seconds = func.timestampdiff(
            literal_column("SECOND"),
            Viewer360Task.started_at,
            Viewer360Task.completed_at,
        )
        stmt = select(
            func.count(Viewer360Task.id),
            func.sum(case((Viewer360Task.status.in_(running_statuses), 1), else_=0)),
            func.sum(case((Viewer360Task.status == "success", 1), else_=0)),
            func.sum(case((Viewer360Task.status.in_(failed_statuses), 1), else_=0)),
            func.sum(case((Viewer360Task.status == "cancelled", 1), else_=0)),
            func.avg(case((Viewer360Task.status == "success", elapsed_seconds), else_=None)),
            func.min(case((Viewer360Task.status == "success", elapsed_seconds), else_=None)),
            func.max(case((Viewer360Task.status == "success", elapsed_seconds), else_=None)),
        )
        async with SessionLocal() as session:
            total, running, success, failed, cancelled, avg_elapsed, min_elapsed, max_elapsed = (
                await session.execute(stmt)
            ).one()
        return {
            "total_tasks": int(total or 0),
            "running_tasks": int(running or 0),
            "success_tasks": int(success or 0),
            "failed_tasks": int(failed or 0),
            "cancelled_tasks": int(cancelled or 0),
            "avg_success_elapsed_sec": (
                float(avg_elapsed) if avg_elapsed is not None else None
            ),
            "min_success_elapsed_sec": (
                float(min_elapsed) if min_elapsed is not None else None
            ),
            "max_success_elapsed_sec": (
                float(max_elapsed) if max_elapsed is not None else None
            ),
        }

    async def add_failure(self, **values) -> dict[str, Any]:
        async with SessionLocal() as session:
            record = Viewer360TaskFailure(**values)
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return _failure_to_dict(record)

    async def list_failures(
        self,
        task_id: str,
        *,
        page: int,
        per_page: int,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(Viewer360TaskFailure).where(Viewer360TaskFailure.task_id == task_id)
        async with SessionLocal() as session:
            total = int((await session.scalar(select(func.count()).select_from(stmt.subquery()))) or 0)
            records = await session.scalars(
                stmt.order_by(Viewer360TaskFailure.time_created.asc())
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            return [_failure_to_dict(record) for record in records], total

    async def get_current(self, item_id: int) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            record = await session.get(ItemViewer360Current, item_id)
            return _current_to_dict(record) if record is not None else None

    async def publish_success(
        self,
        task_id: str,
        *,
        item_id: int,
        manifest_object: str,
        amount_x: int,
        amount_y: int,
        fingerprint: str,
        pipeline_metadata_json: dict[str, Any],
        total_frames: int,
        processed_frames: int,
        row_states_json: list[dict[str, Any]],
    ) -> dict[str, Any]:
        now = datetime.now()
        async with SessionLocal() as session:
            task = await session.scalar(
                select(Viewer360Task)
                .where(Viewer360Task.task_id == task_id)
                .with_for_update()
            )
            if task is None:
                raise KeyError(task_id)
            if task.status not in {"running", "cancelling"}:
                raise RuntimeError(f"Viewer360 task cannot publish from status={task.status}")
            if task.status == "cancelling":
                raise RuntimeError("Viewer360 task was cancelled before publication")

            # Manifest 和全部图片已在 OSS 校验完成，此事务是新版本对外生效的唯一切换点。
            task.status = "success"
            task.current_stage = "completed"
            task.progress = 100
            task.manifest_object = manifest_object
            task.amount_x = amount_x
            task.amount_y = amount_y
            task.fingerprint = fingerprint
            task.pipeline_metadata_json = pipeline_metadata_json
            task.total_frames = total_frames
            task.processed_frames = processed_frames
            task.row_states_json = row_states_json
            task.completed_at = now
            task.heartbeat_at = now
            stmt = mysql_insert(ItemViewer360Current).values(
                item_id=item_id,
                task_id=task_id,
                manifest_object=manifest_object,
                amount_x=amount_x,
                amount_y=amount_y,
                fingerprint=fingerprint,
                time_created=now,
                time_updated=now,
            )
            await session.execute(
                stmt.on_duplicate_key_update(
                    task_id=stmt.inserted.task_id,
                    manifest_object=stmt.inserted.manifest_object,
                    amount_x=stmt.inserted.amount_x,
                    amount_y=stmt.inserted.amount_y,
                    fingerprint=stmt.inserted.fingerprint,
                    time_updated=now,
                )
            )
            await session.commit()
            await session.refresh(task)
            return viewer360_task_to_dict(task)

    async def mark_result_deleted(self, task_id: str) -> dict[str, Any] | None:
        now = datetime.now()
        async with SessionLocal() as session:
            task = await session.scalar(
                select(Viewer360Task)
                .where(Viewer360Task.task_id == task_id)
                .with_for_update()
            )
            if task is None:
                return None
            if task.result_deleted_at is None:
                task.result_deleted_at = now
            await session.execute(
                delete(ItemViewer360Current).where(
                    ItemViewer360Current.item_id == task.item_id,
                    ItemViewer360Current.task_id == task.task_id,
                )
            )
            await session.commit()
            await session.refresh(task)
            return viewer360_task_to_dict(task)
