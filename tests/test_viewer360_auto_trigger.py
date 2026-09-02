import asyncio
import inspect

from csrcqsf.modules.railway_parts.services.viewer360_auto_trigger import (
    maybe_auto_create_viewer360,
)


class FakeManager:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def submit(self, **values):
        self.calls.append(values)
        if self.error:
            raise self.error
        return {"task_id": "task-1"}


def test_auto_trigger_is_noop_while_disabled():
    manager = FakeManager()

    result = asyncio.run(
        maybe_auto_create_viewer360(
            item_id=12,
            rebuild_existing=False,
            enabled=False,
            manager=manager,
        )
    )

    assert result is None
    assert manager.calls == []


def test_auto_trigger_uses_shared_manager_submission():
    manager = FakeManager()

    result = asyncio.run(
        maybe_auto_create_viewer360(
            item_id=12,
            rebuild_existing=True,
            enabled=True,
            manager=manager,
        )
    )

    assert result == {"task_id": "task-1"}
    assert manager.calls == [{"item_id": 12, "rebuild_existing": True}]


def test_auto_trigger_failure_does_not_escape(caplog):
    result = asyncio.run(
        maybe_auto_create_viewer360(
            item_id=12,
            rebuild_existing=False,
            enabled=True,
            manager=FakeManager(RuntimeError("queue unavailable")),
        )
    )

    assert result is None
    assert "queue unavailable" in caplog.text


def test_video_services_call_auto_trigger_after_persistence():
    from csrcqsf.modules.railway_parts.services import source_video_service, upload_service

    source = inspect.getsource(source_video_service)
    multipart = inspect.getsource(upload_service)
    assert source.count("maybe_auto_create_viewer360") >= 3
    assert multipart.count("maybe_auto_create_viewer360") >= 3
