"""配件向量检索的控制台与文件日志配置。"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from importlib import import_module


def setup_logger(name: str, log_dir: str | None = None) -> logging.Logger:
    """创建同时写入控制台和文件的模块日志器。"""
    if log_dir is None:
        runtime_paths = import_module("csrcqsf.core.runtime_paths")
        log_dir = str(runtime_paths.resolve_runtime_paths().indexing_log_dir)

    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_format)

    log_file = os.path.join(log_dir, f"indexing_{datetime.now().strftime('%Y%m%d')}.log")
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
