from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from typing import Any


async def run_startup_step(
    name: str,
    operation: Callable[[], Any],
    *,
    logger: Any,
    details: str = "",
) -> Any:
    """执行应用启动步骤，并记录阶段、耗时和失败堆栈。"""
    suffix = f" ({details})" if details else ""
    logger.info("应用启动初始化开始: {}{}", name, suffix)
    started_at = time.monotonic()

    try:
        result = operation()
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        elapsed = time.monotonic() - started_at
        logger.exception(
            "应用启动初始化失败: {}，耗时 {:.3f}s，错误: {}",
            name,
            elapsed,
            exc,
        )
        raise

    elapsed = time.monotonic() - started_at
    logger.info("应用启动初始化完成: {}，耗时 {:.3f}s", name, elapsed)
    return result
