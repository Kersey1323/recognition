#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局变量配置文件 - Bad Agent Backend v2

包含：
- 项目工作目录配置
- 日志系统配置（支持堆栈跟踪和标准化格式）
- 自动日志清理（删除半年前的日志）
- 其他全局配置变量
"""

import os
import sys
import logging
import logging.handlers
import json
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass
import threading


# =============================================================================
# 项目基础配置
# =============================================================================

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.absolute()


from loguru import logger
import sys

from dotenv import load_dotenv, find_dotenv
from uuid import uuid4
from typing import Optional

# load_dotenv(".env", override=True)
load_dotenv(find_dotenv())



# 工作目录配置
@dataclass
class WorkDirectories:
    """工作目录配置类"""

    # 基础目录
    root: Path = PROJECT_ROOT
    
    # 数据目录
    data: Path = PROJECT_ROOT / "data"
    
    # 日志目录
    logs: Path = PROJECT_ROOT / "logs"
    
    # 模型目录
    models: Path = PROJECT_ROOT / "models"
    
    # 向量数据库目录
    vector_db: Path = PROJECT_ROOT / "vector_db"
    patch_tokens: Path = vector_db / "patch_tokens"
    vector_logs: Path = vector_db / "logs"
    
    # 文档目录
    docs: Path = PROJECT_ROOT / "docs"
    
    # 测试目录
    tests: Path = PROJECT_ROOT / "tests"

    def __post_init__(self):
        """确保所有目录存在"""
        for directory in [
            self.data,
            self.logs,
            self.models,
            self.vector_db, self.patch_tokens, self.vector_logs,
            self.docs,
            self.tests
        ]:
            directory.mkdir(parents=True, exist_ok=True)


# 全局工作目录实例
WORK_DIRS = WorkDirectories()


# =============================================================================
# 日志配置
# =============================================================================
logger.remove()

    # 添加控制台输出
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <cyan>{file.name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)

# 添加文件输出
logger.add(
    "logs/app/app_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {file.name}:{function}:{line} - {message}",
    rotation="00:00",  # 每天轮转
    retention="30 days",  # 保留30天
    compression="zip",  # 压缩旧日志
    level="DEBUG"
)

# 自动初始化
if __name__ == "__main__" :
    # 移除默认配置
    workdirs = WorkDirectories() 
    logger.info("日志系统初始化完成")
    logger.info(f"日志目录配置: {workdirs.logs}")
    logger.info(f"项目根目录: {workdirs.root}，")