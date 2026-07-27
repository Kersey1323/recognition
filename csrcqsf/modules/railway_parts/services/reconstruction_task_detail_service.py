"""Task-scoped reconstruction detail queries."""
from __future__ import annotations

from bfrcommon.common import date_to_str


def is_task_result_deleted(record, status: str | None, success_status: str) -> bool:
    effective_status = status if status is not None else record.status
    # 只有曾经成功产出模型、随后任务结果地址被清空的记录，才属于模型已删除。
    return (
        effective_status == success_status
        and not getattr(record, "ply_url", None)
        and not getattr(record, "obj_url", None)
        and not getattr(record, "glb_url", None)
    )


def serialize_task_item_detail(cls, record, item, parent_item=None) -> dict:
    result = cls._serialize_task_record(record, item_name_map={item.id: item.item_name})
    result.update(
        {
            "item_code": item.item_code,
            "height": item.height,
            "length": item.long,
            "width": item.width,
            "weight": item.weight,
            "video_path": cls._public_asset_url(item.source_video_path),
            "size_str": item.size_str,
            "parent_item_id": parent_item.id if parent_item else None,
            "parent_item_name": parent_item.item_name if parent_item else None,
            "parent_item_code": parent_item.item_code if parent_item else None,
            "created_at": date_to_str(item.time_created),
            "updated_at": date_to_str(item.time_updated),
        }
    )
    return result


async def get_task_item_detail(cls, task_id: str, runtime) -> dict:
    async with runtime.SessionLocal() as session:
        record = await runtime.ReconstructionRecord.get_by_task_id(session, task_id)
        if not record:
            raise runtime.ReconstructionBusinessError(f"重构任务不存在: task_id={task_id}")

        item = await runtime.Items.get_item_by_id(session, record.item_id)
        if not item:
            raise runtime.ReconstructionBusinessError(f"配件不存在: item_id={record.item_id}")

        result_deleted = is_task_result_deleted(
            record, record.status, runtime.ReconstructionStatus.SUCCESS)
        if runtime.reconstruction_server_env_configured() and not result_deleted:
            try:
                remote_status = await cls._get_reconstruction_client().get_task_status(task_id)
            except runtime.ReconstructionServiceClientError as exc:
                runtime.logger.warning(f"查询远端重构任务详情失败，回退本地快照: task_id={task_id}, err={exc}")
            else:
                changed = await cls._apply_remote_status_to_record(
                    session=session,
                    record=record,
                    remote_status=remote_status,
                )
                if changed:
                    await session.commit()

        parent_item = None
        if getattr(item, "parent_item_id", 0) > 0:
            parent_item = await runtime.Items.get_item_by_id(session, item.parent_item_id)
        return serialize_task_item_detail(cls, record, item, parent_item=parent_item)
