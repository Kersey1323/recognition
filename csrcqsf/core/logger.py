"""
日志工具函数模块

注意：日志配置已统一到 csrcqsf.core.logging_config 中
本模块仅提供日志相关的工具函数
"""
from contextlib import contextmanager
import time
from datetime import datetime
from typing import Dict, Optional
import uuid
import os
import json
import re

from csrcqsf.core.logging_config import logger
from csrcqsf.core.runtime_paths import get_runtime_paths

# 日志文件路径
log_path = str(get_runtime_paths().app_log_dir)


def get_logger_file_path(filename: str) -> str:
    """获取日志文件完整路径"""
    return os.path.join(log_path, filename)


def file_filter(record, tag):
    """日志过滤器"""
    return record["extra"].get(tag) is not None


# 日志正则表达式（用于解析日志文件）
reg = r"(?P<time>.*) -- (?P<level>.*) -- (?P<file>.*) -- (?P<line>.*) -- (?P<message>.*) -- (?P<extra>.*)"
logger_reg = re.compile(reg)


def logger_reg_parse(log_record: str) -> Dict[str, any]:
    """解析日志记录字符串"""
    record = logger_reg.match(log_record)
    result = {}
    if record is None:
        print(log_record)
        return result

    result['time'] = record[1]
    result['level'] = record[2]
    result['file'] = record[3]
    result['line'] = record[4]
    result['message'] = record[5]
    result['extra'] = record[6]
    return result


def cast(groups):
    """类型转换函数"""
    if "time" in groups:
        groups["time"] = datetime.strptime(groups["time"], "%Y-%m-%d %H:%M:%S")
    if 'extra' in groups:
        groups['extra'] = json.loads(groups['extra'])


def seek_logger(logger_file_path: str, python_file: str, line: Optional[int] = 20000, 
                query: Optional[str] = None, start_date: Optional[datetime] = None, 
                end_date: Optional[datetime] = None, extra: Optional[Dict[str, str]] = None) -> str:
    """
    搜索日志文件中的特定记录
    
    Args:
        logger_file_path: 日志文件路径
        python_file: Python 文件名
        line: 读取的行数
        query: 搜索关键词
        start_date: 开始日期
        end_date: 结束日期
        extra: 额外字段过滤
    
    Returns:
        匹配的日志记录字符串
    """
    from bfrcommon.file import tail
    
    result = []
    with open(logger_file_path) as file:
        if line == 0:
            line = 20000
        tmpfile_path = os.path.join(os.path.dirname(
            logger_file_path), str(uuid.uuid4())+'.log')
        tail(file, line, tmp_file_path=tmpfile_path)
        for log in logger.parse(tmpfile_path, reg, cast=cast):
            if log['file'] != python_file:
                continue
            if start_date is not None and start_date > log["time"]:
                continue
            if end_date is not None and end_date < log["time"]:
                continue
            if query is not None and (query not in log['message'] and query not in log['extra']):
                continue
            if extra is not None:
                extraFlag = True
                for key, value in extra.items():
                    if key not in log['extra']:
                        extraFlag = False
                    else:
                        if log['extra'][key] != value:
                            extraFlag = False
                if extraFlag == False:
                    continue
            linecontent = f"""{log['time'].strftime("%Y-%m-%d %H:%M:%S")} - {log['file']}{log['line']}行 - {log['message']} - {log['extra']}"""
            result.append(linecontent)
        os.remove(tmpfile_path)

    return '\n'.join(result)


def used_time(func):
    """装饰器：记录函数执行时间"""
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        duration = time.perf_counter() - start
        logger.info(f"{func.__name__} 执行时间: {duration:.5f} 秒")
        return result
    return wrapper


class AsyncTimer:
    """异步计时器上下文管理器"""

    def __init__(self, desc: str | None):
        self.desc = desc if desc is not None else "代码块"

    async def __aenter__(self):
        self.start = time.perf_counter()
        return self

    async def __aexit__(self, *exc):
        self.duration = time.perf_counter() - self.start
        logger.info(f"{self.desc}耗时: {self.duration:.5f}s")


@contextmanager
def CodeTimer(name: str):
    """同步计时器上下文管理器"""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        logger.info(f"{name}的执行时间: {duration:.5f} 秒")
