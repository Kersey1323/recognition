from typing import Any, Callable, Coroutine
import asyncio
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from csrcqsf.core.logging_config import logger
from apscheduler.job import Job as apsjob
from datetime import datetime
from csrcqsf.core.settings import (
    main_db_env_configured,
    reconstruction_server_env_configured,
)


class BFRTrigger(CronTrigger):

    def __init__(self, year=None, month=None, day=None, week=None, day_of_week=None, hour=None,
                 minute=None, second=None, start_date=None, end_date=None, timezone=None,
                 jitter=None):
        super().__init__(year=year, month=month, day=day, week=week, day_of_week=day_of_week,
                         hour=hour, minute=minute, second=second, start_date=start_date, end_date=end_date, timezone=timezone)

    @classmethod
    def from_crontab(cls, expr):
        """
        override CronTrigger from_crontab
        原始的cron表达式不能到秒

        """
        values = expr.split()
        if len(values) != 6:
            raise ValueError(
                'Wrong number of fields; got {}, expected 6'.format(len(values)))

        return cls(second=values[0], minute=values[1], hour=values[2], day=values[3], month=values[4],
                   day_of_week=values[5])

    @classmethod
    def is_cron_effective(cls, expr: str) -> bool:
        try:
            cls.from_crontab(expr=expr)
        except Exception:
            return False
        return True


job_defaults = {
    'coalesce': False,
    'max_instances': 20
}

executors = {
    'default': {'type': 'threadpool', 'max_workers': 20},
    # 'processpool': ProcessPoolExecutor(5)
}

scheduler = BackgroundScheduler(executors=executors, job_defaults=job_defaults)
_main_async_loop: asyncio.AbstractEventLoop | None = None


def register_main_async_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_async_loop
    _main_async_loop = loop


def submit_coroutine_to_main_loop(coroutine: Coroutine[Any, Any, Any]):
    """从调度器线程把异步业务提交到 FastAPI 主事件循环。"""
    if _main_async_loop is None or _main_async_loop.is_closed():
        coroutine.close()
        raise RuntimeError("主事件循环尚未就绪")
    return asyncio.run_coroutine_threadsafe(coroutine, _main_async_loop)


def excute_job_once(func, *args, **kwargs):
    try:
        scheduler.add_job(func=func, trigger='date',
                          next_run_time=datetime.now(), *args, **kwargs)
    except Exception as e:
        print('excute_job_once error! ... ' + str(e))


def add_cron_job(func, cron: str, job_id: str, timeout=None, callback: Callable = None, *args, **kwargs):
    if job_id is None or job_id == '':
        raise Exception('job_id不能为空')

    job = scheduler.get_job(job_id=job_id)

    if job is not None:
        raise Exception(f'job_id:{job_id}已经存在')

    trigger: BFRTrigger = None
    try:
        trigger = BFRTrigger.from_crontab(cron)
    except Exception as e:
        raise Exception(f'根据cron表达式构建schedule触发器失败,错误信息{e}')

    scheduler.add_job(func=func, id=job_id,
                      trigger=trigger, *args, **kwargs)
    logger.info(f'作业id:{job_id}写入任务队列')


def get_cron_job(job_id: str) -> apsjob:
    return scheduler.get_job(job_id=job_id)


def remove_cron_queue_job(job_id: str):
    try:
        scheduler_job = scheduler.get_job(job_id=job_id)
        if scheduler_job is not None:
            # 删除调度器里的job
            scheduler.remove_job(job_id=job_id)
    except Exception:
        pass


scheduler.start()


# ============================================================================
# 定时任务：同步重建任务状态
# ============================================================================

def sync_reconstruction_tasks_sync():
    """
    定时同步所有进行中的重建任务状态（同步包装器）
    """
    if not main_db_env_configured():
        logger.warning("未显式配置主业务库环境变量，跳过重建任务状态同步")
        return
    if not reconstruction_server_env_configured():
        logger.warning("未显式配置重构服务环境变量，跳过重建任务状态同步")
        return
    if _main_async_loop is None or not _main_async_loop.is_running():
        logger.warning("主事件循环尚未就绪，跳过本轮重建任务状态同步")
        return

    try:
        from csrcqsf.modules.railway_parts.services.reconstruction_sync_service import (
            ReconstructionSyncManager,
        )

        future = asyncio.run_coroutine_threadsafe(
            ReconstructionSyncManager.sync_running_tasks(),
            _main_async_loop,
        )
        result = future.result()
        if result["synced_count"] > 0:
            logger.info(f"成功同步 {result['synced_count']}/{result['total']} 个重建任务状态")
    except Exception as e:
        logger.error(f"同步重建任务状态失败: {e}", exc_info=True)


# 添加定时任务：同步重建任务状态
# 从环境变量读取同步间隔（秒），默认 10 秒
RECONSTRUCTION_SYNC_INTERVAL = int(os.getenv('RECONSTRUCTION_SYNC_INTERVAL', '10'))

try:
    scheduler.add_job(
        func=sync_reconstruction_tasks_sync,
        trigger='interval',
        seconds=RECONSTRUCTION_SYNC_INTERVAL,
        id='sync_reconstruction_tasks',
        name='同步重建任务状态',
        replace_existing=True
    )
    logger.info(f"已启动重建任务状态同步定时任务（每{RECONSTRUCTION_SYNC_INTERVAL}秒执行一次）")
except Exception as e:
    logger.error(f"启动重建任务状态同步定时任务失败: {e}")
