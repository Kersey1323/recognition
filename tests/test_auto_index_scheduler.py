import asyncio

from csrcqsf.modules.railway_parts.services.auto_index_scheduler import (
    AutoIndexScheduler,
)


class FakeAutoIndexRepository:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    async def list_candidate_item_ids(self, **kwargs):
        self.calls.append(kwargs)
        if not self.results:
            return []
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeIndexTaskManager:
    def __init__(self, slots=16, active_item_ids=(), start_results=None):
        self.available_single_slots = slots
        self.active_single_item_ids = tuple(active_item_ids)
        self.start_results = list(start_results or [])
        self.calls = []
        self.listener = None
        self.started = asyncio.Event()

    def set_capacity_listener(self, listener):
        self.listener = listener

    async def try_start_single(self, runner, *, item_id):
        self.calls.append((runner, item_id))
        self.started.set()
        if self.start_results:
            return self.start_results.pop(0)
        return {"task_id": f"task-{item_id}"}


async def _runner(**_kwargs):
    return {}


def test_scheduler_starts_candidates_immediately_and_passes_active_exclusions():
    async def scenario():
        repository = FakeAutoIndexRepository(results=[[101, 102]])
        manager = FakeIndexTaskManager(slots=2, active_item_ids=(99,))
        scheduler = AutoIndexScheduler(
            repository=repository,
            manager=manager,
            scan_interval_seconds=60,
        )

        await scheduler.start(_runner)
        await asyncio.wait_for(manager.started.wait(), timeout=1)
        for _ in range(20):
            if len(manager.calls) == 2:
                break
            await asyncio.sleep(0)
        await scheduler.stop()

        assert repository.calls == [
            {"limit": 2, "excluded_item_ids": (99,)}
        ]
        assert manager.calls == [(_runner, 101), (_runner, 102)]
        assert manager.listener is None

    asyncio.run(scenario())


def test_scheduler_does_not_query_candidates_without_capacity():
    async def scenario():
        repository = FakeAutoIndexRepository(results=[[101]])
        manager = FakeIndexTaskManager(slots=0)
        scheduler = AutoIndexScheduler(
            repository=repository,
            manager=manager,
            scan_interval_seconds=60,
        )

        await scheduler.start(_runner)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await scheduler.stop()

        assert repository.calls == []
        assert manager.calls == []

    asyncio.run(scenario())


def test_scheduler_stops_current_scan_when_capacity_race_rejects_candidate():
    async def scenario():
        repository = FakeAutoIndexRepository(results=[[101, 102, 103]])
        manager = FakeIndexTaskManager(
            slots=3,
            start_results=[{"task_id": "task-101"}, None],
        )
        scheduler = AutoIndexScheduler(
            repository=repository,
            manager=manager,
            scan_interval_seconds=60,
        )
        scheduler._runner = _runner

        started_count = await scheduler.scan_once()

        assert started_count == 1
        assert manager.calls == [(_runner, 101), (_runner, 102)]

    asyncio.run(scenario())


def test_scheduler_recovers_after_one_scan_failure():
    async def scenario():
        repository = FakeAutoIndexRepository(
            results=[RuntimeError("database unavailable"), [101]]
        )
        manager = FakeIndexTaskManager(slots=1)
        scheduler = AutoIndexScheduler(
            repository=repository,
            manager=manager,
            scan_interval_seconds=0.01,
        )

        await scheduler.start(_runner)
        await asyncio.wait_for(manager.started.wait(), timeout=1)
        await scheduler.stop()

        assert len(repository.calls) >= 2
        assert manager.calls == [(_runner, 101)]

    asyncio.run(scenario())


def test_scheduler_can_restart_on_a_new_event_loop():
    repository = FakeAutoIndexRepository(results=[[], []])
    manager = FakeIndexTaskManager(slots=1)
    scheduler = AutoIndexScheduler(
        repository=repository,
        manager=manager,
        scan_interval_seconds=60,
    )

    async def start_and_stop():
        expected_call_count = len(repository.calls) + 1
        await scheduler.start(_runner)
        for _ in range(50):
            if len(repository.calls) >= expected_call_count:
                break
            await asyncio.sleep(0)
        await scheduler.stop()

    asyncio.run(start_and_stop())
    asyncio.run(start_and_stop())

    assert len(repository.calls) == 2
