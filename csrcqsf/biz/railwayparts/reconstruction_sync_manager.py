from __future__ import annotations

from sqlalchemy import or_, select

from globals_vars import logger
from csrcqsf.biz.railwayparts.reconstruction_client import (
    ReconstructionServiceClient,
    ReconstructionServiceClientError,
)
from csrcqsf.biz.railwayparts.reconstruction_manager import ReconstructionManager
from csrcqsf.data.pg import SessionLocal
from csrcqsf.models.reconstruction import ReconstructionRecord, ReconstructionStatus


class ReconstructionSyncManager:
    @classmethod
    async def sync_running_tasks(cls) -> dict:
        async with SessionLocal() as session:
            stmt = select(ReconstructionRecord).where(
                or_(
                    ReconstructionRecord.status == ReconstructionStatus.PENDING,
                    ReconstructionRecord.status == ReconstructionStatus.TRAINING,
                )
            )
            running_records = list((await session.scalars(stmt)).all())
            if not running_records:
                return {"total": 0, "synced_count": 0}

            client = ReconstructionServiceClient()
            try:
                remote_payload = await client.get_task_status_batch(
                    [record.task_id for record in running_records]
                )
            except ReconstructionServiceClientError as exc:
                raise RuntimeError(str(exc)) from exc

            by_task_id = {
                item["task_id"]: item
                for item in (remote_payload.get("items") or [])
                if item.get("task_id")
            }

            synced_count = 0
            for record in running_records:
                remote_status = by_task_id.get(record.task_id)
                if remote_status is None:
                    logger.warning(f"远端未返回重构任务状态: task_id={record.task_id}")
                    continue

                changed = await ReconstructionManager._apply_remote_status_to_record(
                    session=session,
                    record=record,
                    remote_status=remote_status,
                )
                if changed:
                    synced_count += 1

            if synced_count > 0:
                await session.commit()

            return {"total": len(running_records), "synced_count": synced_count}
