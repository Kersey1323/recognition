from __future__ import annotations

import sys

from loguru import logger

from csrcqsf.core.runtime_paths import RuntimePaths, get_runtime_paths


CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level}</level> | "
    "<cyan>{file.name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)
FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | {level} | "
    "{file.name}:{function}:{line} - {message}"
)

_configured = False


def configure_logging(
    paths: RuntimePaths | None = None,
    *,
    reset: bool = False,
):
    global _configured
    if _configured and not reset:
        return logger

    runtime_paths = paths or get_runtime_paths()
    logger.remove()
    logger.add(
        sys.stdout,
        format=CONSOLE_FORMAT,
        level="INFO",
        colorize=True,
    )

    try:
        runtime_paths.app_log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(runtime_paths.app_log_dir / "app_{time:YYYY-MM-DD}.log"),
            format=FILE_FORMAT,
            rotation="00:00",
            retention="30 days",
            compression="zip",
            level="DEBUG",
        )
    except OSError as exc:
        logger.warning(
            "文件日志初始化失败: path={}, error={}",
            runtime_paths.app_log_dir,
            exc,
        )

    _configured = True
    return logger


configure_logging()


__all__ = ["configure_logging", "logger"]
