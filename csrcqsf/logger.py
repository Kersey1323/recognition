from contextlib import contextmanager
import time
from datetime import datetime
from typing import Dict, Optional
import uuid
from bfrcommon.file import tail
import os
from loguru import logger
import sys
import json
import re

log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
if os.path.exists(log_path) == False:
    os.mkdir(log_path)


def get_logger_file_path(filename: str) -> str:
    return os.path.join(log_path, filename)


def file_filter(record, tag):
    return record["extra"].get(tag) is not None


log_format = "{time:YYYY-MM-DD HH:mm:ss} -- {level} -- {file} -- {line} -- {message} -- {extra}"


def patching(record):
    if record["extra"] is not None:
        record["extra"] = json.dumps(record["extra"])
    return record


# 把默认的Sink删除掉
logger.remove()

logger_file = os.path.join(log_path, 'ai.log')
logger.add(logger_file, level="DEBUG", format=log_format,
           rotation="500 MB", enqueue=True)
logger.add(sys.stdout, format=log_format,
           level="INFO", enqueue=True, colorize=True)
# logger = logger.patch(patcher=patching)

reg = r"(?P<time>.*) -- (?P<level>.*) -- (?P<file>.*) -- (?P<line>.*) -- (?P<message>.*) -- (?P<extra>.*)"

logger_reg = re.compile(reg)


def logger_reg_parse(log_record: str) -> Dict[str, any]:
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
    if "time" in groups:
        groups["time"] = datetime.strptime(groups["time"], "%Y-%m-%d %H:%M:%S")
    if 'extra' in groups:
        groups['extra'] = json.loads(groups['extra'])


def seek_logger(logger_file_path: str, python_file: str, line: Optional[int] = 20000, query: Optional[str] = None, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None, extra: Optional[Dict[str, str]] = None) -> str:
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
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        duration = time.perf_counter() - start
        logger.info(f"{func.__name__} 执行时间: {duration:.5f} 秒")
        return result
    return wrapper


class AsyncTimer:

    def __init__(self, desc: str | None):

        self.desc = desc if desc is not None else "代码块"

    async def __aenter__(self):
        self.start = time.perf_counter()
        return self

    async def __aexit__(self, *exc):
        self.duration = time.perf_counter() - self.start
        logger.info(f"{self.desc}耗时: {self.duration:.5f}s")



@contextmanager
def CodeTimer(name:str):
    """简单的计时上下文管理器"""
    start = time.perf_counter()
    try:
        yield
    finally:
        end = time.time()
        duration = time.perf_counter() - start
        logger.info(f"{name}的执行时间: {duration:.5f} 秒")