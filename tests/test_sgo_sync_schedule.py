import asyncio
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from csrcqsf.modules.sgo import services
from csrcqsf.modules.sgo.services import SGOBiz


@pytest.fixture(autouse=True)
def enable_scheduled_sync(monkeypatch):
    monkeypatch.setenv("SGO_ENABLE_SCHEDULED_SYNC", "true")


@pytest.fixture
def scheduler():
    instance = BackgroundScheduler(timezone="UTC")
    instance.start(paused=True)
    try:
        yield instance
    finally:
        instance.shutdown(wait=False)


def test_image_sync_runs_at_midnight_beijing_even_when_server_uses_utc(monkeypatch, scheduler):
    monkeypatch.setenv("SGO_ENABLE_IMAGE_SYNC", "false")
    with patch.object(services, "scheduler", scheduler), patch.object(SGOBiz, "get_token") as token:
        SGOBiz.init()

    job = scheduler.get_job("sgo-images-sync")
    assert job is not None
    assert job.func == SGOBiz._submit_scheduled_sync
    assert job.args == ("images",)
    now = datetime(2026, 10, 14, 15, 30, tzinfo=timezone.utc)
    next_run = job.trigger.get_next_fire_time(None, now)
    assert next_run.astimezone(timezone.utc) == datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc)
    following = job.trigger.get_next_fire_time(next_run, next_run)
    assert following.astimezone(timezone.utc) == datetime(2026, 10, 15, 16, 0, tzinfo=timezone.utc)
    token.assert_not_called()


def test_inquiry_history_sync_defaults_to_every_100_minutes(monkeypatch, scheduler):
    from csrcqsf.core.settings import sgo_inquiry_history_sync_interval_minutes

    assert sgo_inquiry_history_sync_interval_minutes == 100
    monkeypatch.setenv("SGO_ENABLE_IMAGE_SYNC", "false")
    with patch.object(services, "scheduler", scheduler):
        SGOBiz.init()

    job = scheduler.get_job("sgo-inquiry-history-sync")
    assert job is not None
    assert job.func == SGOBiz._submit_scheduled_sync
    assert job.args == ("inquiry-history",)
    assert job.trigger.interval == timedelta(minutes=100)


def test_scheduled_sync_registration_is_idempotent(monkeypatch, scheduler):
    monkeypatch.setenv("SGO_ENABLE_IMAGE_SYNC", "true")
    with patch.object(services, "scheduler", scheduler), patch.object(SGOBiz, "get_token"):
        SGOBiz.init()
        SGOBiz.init()
    jobs = scheduler.get_jobs()
    assert len(jobs) == 4
    assert len({job.id for job in jobs}) == 4


@pytest.mark.parametrize(
    "task_type,runner,kwargs",
    [
        ("parts", SGOBiz.sync_parts_items, {}),
        ("images", SGOBiz.sync_images, {"item_id_list": [], "sync_scope": "all"}),
        ("inquiry-history", SGOBiz.sync_inquiry_history, {}),
    ],
)
def test_scheduled_job_submits_to_main_loop_and_uses_managed_sync(task_type, runner, kwargs, scheduler):
    manager = AsyncMock()
    manager.start.return_value = {"task_id": "scheduled-task"}

    def submit(coroutine):
        result = asyncio.run(coroutine)
        future = Future()
        future.set_result(result)
        return future

    with patch.object(services, "sgo_sync_task_manager", manager), \
         patch.object(services, "scheduler", scheduler), \
         patch.object(services, "submit_coroutine_to_main_loop", side_effect=submit) as main_loop:
        SGOBiz._submit_scheduled_sync(task_type)

    main_loop.assert_called_once()
    manager.start.assert_awaited_once_with(task_type, runner, **kwargs)


@pytest.mark.parametrize("task_type", ["parts", "images", "inquiry-history"])
def test_busy_scheduled_sync_defers_without_losing_job_or_creating_duplicate_retries(task_type, scheduler):
    manager = AsyncMock()
    manager.start.side_effect = RuntimeError("已有 SGO 同步任务正在执行")
    with patch.object(services, "sgo_sync_task_manager", manager), patch.object(services, "scheduler", scheduler):
        before = datetime.now(timezone.utc)
        asyncio.run(SGOBiz._start_scheduled_sync(task_type))
        asyncio.run(SGOBiz._start_scheduled_sync(task_type))
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        retry = jobs[0]
        assert retry.id == f"sgo-{task_type}-sync-retry"
        assert retry.args == (task_type,)
        assert before + timedelta(seconds=60) <= retry.trigger.run_date <= datetime.now(timezone.utc) + timedelta(seconds=60)

        manager.start.side_effect = None
        manager.start.return_value = {"task_id": "resumed-task"}
        asyncio.run(SGOBiz._start_scheduled_sync(task_type))
        assert scheduler.get_jobs() == []


def test_inquiry_sync_interval_can_be_configured(monkeypatch, scheduler):
    monkeypatch.setenv("SGO_ENABLE_IMAGE_SYNC", "false")
    with patch.object(services, "scheduler", scheduler), \
         patch.object(services, "sgo_inquiry_history_sync_interval_minutes", 45, create=True):
        SGOBiz.init()
    job = scheduler.get_job("sgo-inquiry-history-sync")
    assert job is not None
    assert job.trigger.interval == timedelta(minutes=45)


def test_disabled_scheduled_sync_registers_no_jobs_or_token_requests(monkeypatch, scheduler):
    monkeypatch.setenv("SGO_ENABLE_SCHEDULED_SYNC", "false")
    monkeypatch.setenv("SGO_ENABLE_IMAGE_SYNC", "true")
    with patch.object(services, "scheduler", scheduler), patch.object(SGOBiz, "get_token") as token:
        SGOBiz.init()
    assert scheduler.get_jobs() == []
    token.assert_not_called()


def test_disabling_sync_removes_existing_jobs_and_retries_only(monkeypatch, scheduler):
    with patch.object(services, "scheduler", scheduler), patch.object(SGOBiz, "get_token"):
        SGOBiz.init()
        scheduler.add_job(lambda: None, "interval", minutes=1, id="sgo-images-sync-retry")
        scheduler.add_job(lambda: None, "interval", minutes=1, id="unrelated-job")
        monkeypatch.setenv("SGO_ENABLE_SCHEDULED_SYNC", "false")
        SGOBiz.init()
    assert [job.id for job in scheduler.get_jobs()] == ["unrelated-job"]


@pytest.mark.parametrize("task_type", ["parts", "images", "inquiry-history"])
def test_disabled_scheduled_sync_cannot_submit_or_start_task(monkeypatch, task_type):
    monkeypatch.setenv("SGO_ENABLE_SCHEDULED_SYNC", "false")
    with patch.object(services, "submit_coroutine_to_main_loop") as submit, \
         patch.object(services, "sgo_sync_task_manager", AsyncMock()) as manager:
        SGOBiz._submit_scheduled_sync(task_type)
        asyncio.run(SGOBiz._start_scheduled_sync(task_type))
    submit.assert_not_called()
    manager.start.assert_not_awaited()
