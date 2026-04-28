from datetime import datetime
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

    with patch("csrcqsf.scheduler.create_engine"), \
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
