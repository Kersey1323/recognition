"""源视频持久化完成后的 Viewer360 可选自动创建入口。"""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


async def maybe_auto_create_viewer360(
    *,
    item_id: int,
    rebuild_existing: bool,
    enabled: bool | None = None,
    manager: Any = None,
) -> dict | None:
    if enabled is None:
        from csrcqsf.core.settings import (
            viewer360_auto_create_after_video_upload,
            viewer360_enabled,
        )

        enabled = viewer360_enabled and viewer360_auto_create_after_video_upload
    if not enabled:
        return None
    if manager is None:
        from csrcqsf.modules.railway_parts.services.viewer360_task_manager import (
            viewer360_task_manager,
        )

        manager = viewer360_task_manager
    try:
        # 自动和手工入口共用同一提交方法，因此已有结果复用和活动任务限制不会分叉。
        return await manager.submit(
            item_id=item_id,
            rebuild_existing=rebuild_existing,
        )
    except Exception as exc:
        # 视频已经成功持久化，任务排队失败只告警，不能反向回滚视频业务。
        logger.warning(
            "Viewer360 自动创建失败: item_id=%s, rebuild_existing=%s, error=%s",
            item_id,
            rebuild_existing,
            exc,
        )
        return None
