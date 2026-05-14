from datetime import datetime
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from csrcqsf.models.reconstruction import ReconstructionStatus
from csrcqsf.scheduler import sync_reconstruction_tasks_sync


def test_scheduler_marks_success_terminal_records_complete_with_date_done():
    record = SimpleNamespace(
        task_id="task-id",
        status=ReconstructionStatus.TRAINING,
        progress=98,
        current_stage="提取结果",
        error_message=None,
        completed_at=None,
        elapsed_sec=None,
    )
    async_result = SimpleNamespace(
        state="SUCCESS",
        result={"status": "success", "elapsed_sec": 493.4},
        info=None,
        date_done=datetime(2026, 4, 28, 16, 27, 53),
    )
    fake_scalars = MagicMock()
    fake_scalars.all.return_value = [record]
    fake_execute = MagicMock(return_value=SimpleNamespace(scalars=lambda: fake_scalars))
    fake_session = MagicMock()
    fake_session.execute = fake_execute

    with patch("csrcqsf.scheduler.main_db_env_configured", return_value=True), \
         patch("csrcqsf.scheduler.redis_env_configured", return_value=True), \
         patch("csrcqsf.scheduler.create_engine"), \
         patch("csrcqsf.scheduler.Session") as session_cls, \
         patch("csrcqsf.scheduler.AsyncResult", return_value=async_result):
        session_cls.return_value.__enter__.return_value = fake_session
        sync_reconstruction_tasks_sync()

    assert record.status == ReconstructionStatus.SUCCESS
    assert record.progress == 100
    assert record.current_stage == "完成"
    assert record.completed_at == datetime(2026, 4, 28, 16, 27, 53)
    assert record.elapsed_sec == 493.4
    fake_session.commit.assert_called_once()


def test_scheduler_returns_early_without_explicit_env(monkeypatch):
    for key in (
        "MAIN_DB_HOST",
        "MAIN_DB_PORT",
        "MAIN_DB_USER",
        "MAIN_DB_PASSWORD",
        "PG_HOST",
        "PG_PORT",
        "PG_USER",
        "PG_PASSWORD",
        "REDIS_HOST",
        "REDIS_PORT",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
    ):
        monkeypatch.delenv(key, raising=False)

    sys.modules.pop("csrcqsf.scheduler", None)
    scheduler_module = importlib.import_module("csrcqsf.scheduler")

    with patch("csrcqsf.scheduler.main_db_env_configured", return_value=False), patch(
        "csrcqsf.scheduler.redis_env_configured", return_value=False
    ), patch("csrcqsf.scheduler.create_engine") as create_engine_mock, patch(
        "csrcqsf.scheduler.AsyncResult"
    ) as async_result_mock:
        scheduler_module.sync_reconstruction_tasks_sync()

    create_engine_mock.assert_not_called()
    async_result_mock.assert_not_called()
