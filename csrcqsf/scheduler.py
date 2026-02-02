from typing import Callable
from apscheduler.schedulers.background import BackgroundScheduler, BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from csrcqsf.logger import logger
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