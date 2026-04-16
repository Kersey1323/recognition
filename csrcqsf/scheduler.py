from typing import Callable
from apscheduler.schedulers.background import BackgroundScheduler, BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from globals_vars import logger
from apscheduler.job import Job as apsjob
from datetime import datetime,timedelta


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
        except:
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


def excute_job_once(func, *args, **kwargs):
    try:
        scheduler.add_job(func=func, trigger='date',
                          next_run_time=datetime.now(), *args, **kwargs)
    except Exception as e:
        print('excute_job_once error! ... ' + str(e))


def add_cron_job(func, cron: str, job_id: str, timeout=None, callback: Callable = None, *args, **kwargs):
    if job_id is None or job_id == '':
        raise Exception(f'job_id不能为空')

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
    except:
        pass


scheduler.start()


# ============================================================================
# 定时任务：同步重建任务状态
# ============================================================================

def sync_reconstruction_tasks_sync():
    """
    定时同步所有进行中的重建任务状态（同步版本）
    从 Celery 获取最新状态并更新到数据库
    
    注意：使用同步数据库操作避免事件循环冲突
    """
    try:
        from csrcqsf.biz.railwayparts.reconstruction_server.celery_app import celery_app
        from celery.result import AsyncResult
        from csrcqsf.models.reconstruction import ReconstructionStatus, ReconstructionRecord
        from sqlalchemy import create_engine, select, or_
        from sqlalchemy.orm import Session
        from csrcqsf.settings import ai_settings
        
        # 创建同步数据库引擎（使用 psycopg2 驱动）
        sync_db_url = ai_settings.get_pg_dsn()
        engine = create_engine(sync_db_url, pool_pre_ping=True)
        
        with Session(engine) as session:
            # 查询进行中的任务
            stmt = select(ReconstructionRecord).where(
                or_(
                    ReconstructionRecord.status == ReconstructionStatus.PENDING,
                    ReconstructionRecord.status == ReconstructionStatus.TRAINING
                )
            )
            result = session.execute(stmt)
            running_tasks = result.scalars().all()
            
            if not running_tasks:
                return
            
            logger.debug(f"同步 {len(running_tasks)} 个进行中的重建任务状态")
            
            # 逐个同步任务状态
            synced_count = 0
            for record in running_tasks:
                try:
                    # 从 Celery 获取任务状态
                    result = AsyncResult(record.task_id, app=celery_app)
                    
                    # 映射 Celery 状态到 ReconstructionStatus
                    status_map = {
                        "PENDING": ReconstructionStatus.PENDING,
                        "STARTED": ReconstructionStatus.TRAINING,
                        "PROGRESS": ReconstructionStatus.TRAINING,
                        "SUCCESS": ReconstructionStatus.SUCCESS,
                        "FAILURE": ReconstructionStatus.FAILED,
                    }
                    
                    new_status = status_map.get(result.state, record.status)
                    progress = record.progress
                    stage = record.current_stage
                    error = record.error_message
                    
                    # 获取进度和阶段信息
                    if result.state == "PROGRESS":
                        info = result.info or {}
                        stage = info.get("stage", stage)
                        progress = info.get("progress", progress)
                    elif result.state == "SUCCESS":
                        progress = 100
                        stage = "完成"
                    elif result.state == "FAILURE":
                        error = str(result.info)
                        stage = "失败"
                    
                    # 更新数据库状态
                    if new_status != record.status or progress != record.progress:
                        record.status = new_status
                        record.progress = progress
                        record.current_stage = stage
                        if error:
                            record.error_message = error
                        session.commit()
                        synced_count += 1
                        
                except Exception as e:
                    logger.error(f"同步任务 {record.task_id} 状态失败: {e}")
                    session.rollback()
            
            if synced_count > 0:
                logger.info(f"成功同步 {synced_count}/{len(running_tasks)} 个重建任务状态")
                
    except Exception as e:
        logger.error(f"同步重建任务状态失败: {e}", exc_info=True)


# 添加定时任务：同步重建任务状态
# 从环境变量读取同步间隔（秒），默认 10 秒
import os
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