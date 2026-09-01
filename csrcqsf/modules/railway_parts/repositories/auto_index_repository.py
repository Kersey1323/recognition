"""自动索引扫描的待处理配件查询。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import exists, func, select

from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.models.orm.index_rebuild_task import IndexRebuildTask
from csrcqsf.models.orm.sgo import SgoItemImages


TERMINAL_ATTEMPT_STATUSES = ("success", "failed", "cancelled")


def build_auto_index_candidate_stmt(
    *,
    limit: int,
    excluded_item_ids: Sequence[int] = (),
):
    attempted = exists(
        select(IndexRebuildTask.id).where(
            IndexRebuildTask.task_scope == "single",
            IndexRebuildTask.item_id == SgoItemImages.item_id,
            IndexRebuildTask.status.in_(TERMINAL_ATTEMPT_STATUSES),
            IndexRebuildTask.time_created >= SgoItemImages.time_created,
        )
    )
    stmt = select(SgoItemImages.item_id).where(
        # 所有来源的未索引图片都进入自动任务；是否分割由索引流程按图片来源判断。
        SgoItemImages.is_indexed != 1,
        SgoItemImages.is_deleted == 0,
        ~attempted,
    )
    if excluded_item_ids:
        stmt = stmt.where(SgoItemImages.item_id.not_in(excluded_item_ids))

    # 最早采集的待索引图片优先；选中配件后，一个任务处理该配件全部未索引图片。
    return (
        stmt.group_by(SgoItemImages.item_id)
        .order_by(
            func.min(SgoItemImages.time_created),
            func.min(SgoItemImages.id),
        )
        .limit(limit)
    )


class AutoIndexRepository:
    async def list_candidate_item_ids(
        self,
        *,
        limit: int,
        excluded_item_ids: Sequence[int] = (),
    ) -> list[int]:
        if limit <= 0:
            return []
        stmt = build_auto_index_candidate_stmt(
            limit=limit,
            excluded_item_ids=excluded_item_ids,
        )
        async with SessionLocal() as session:
            result = await session.scalars(stmt)
            return [int(item_id) for item_id in result]
