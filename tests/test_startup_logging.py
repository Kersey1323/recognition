import asyncio

import pytest

from csrcqsf.core.startup_logging import run_startup_step


class RecordingLogger:
    def __init__(self):
        self.info_messages = []
        self.exception_messages = []

    def info(self, message, *args):
        self.info_messages.append(message.format(*args))

    def exception(self, message, *args):
        self.exception_messages.append(message.format(*args))


def test_run_startup_step_logs_start_completion_and_elapsed_time():
    logger = RecordingLogger()

    async def initialize():
        return None

    asyncio.run(
        run_startup_step(
            "主业务数据库迁移",
            initialize,
            logger=logger,
            details="host=192.168.100.2, port=3307, database=test",
        )
    )

    assert logger.info_messages[0] == (
        "应用启动初始化开始: 主业务数据库迁移 "
        "(host=192.168.100.2, port=3307, database=test)"
    )
    assert logger.info_messages[1].startswith("应用启动初始化完成: 主业务数据库迁移，耗时 ")
    assert logger.info_messages[1].endswith("s")


def test_run_startup_step_logs_failed_stage_and_reraises():
    logger = RecordingLogger()

    async def initialize():
        raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(run_startup_step("主业务数据库迁移", initialize, logger=logger))

    assert len(logger.exception_messages) == 1
    assert logger.exception_messages[0].startswith("应用启动初始化失败: 主业务数据库迁移，耗时 ")
    assert "database unavailable" in logger.exception_messages[0]
