import asyncio

from csrcqsf.modules.railway_parts.services.viewer360_task_manager import (
    Viewer360TaskManager,
)


class _StatisticsRepository:
    async def summarize_tasks(self):
        return {
            "total_tasks": 20,
            "running_tasks": 3,
            "success_tasks": 10,
            "failed_tasks": 5,
            "cancelled_tasks": 2,
            "avg_success_elapsed_sec": 126.5,
            "min_success_elapsed_sec": 90.0,
            "max_success_elapsed_sec": 180.0,
        }


def test_viewer360_statistics_uses_success_and_failure_as_rate_base():
    manager = Viewer360TaskManager(
        repository=_StatisticsRepository(),
        storage=object(),
    )

    result = asyncio.run(manager.statistics())

    assert result == {
        "total_tasks": 20,
        "running_tasks": 3,
        "success_tasks": 10,
        "failed_tasks": 5,
        "cancelled_tasks": 2,
        "success_rate": 10 / 15,
        "avg_success_elapsed_sec": 126.5,
        "min_success_elapsed_sec": 90.0,
        "max_success_elapsed_sec": 180.0,
    }


def test_viewer360_statistics_returns_zero_rate_without_finished_attempts():
    class _EmptyRepository:
        async def summarize_tasks(self):
            return {
                "total_tasks": 3,
                "running_tasks": 3,
                "success_tasks": 0,
                "failed_tasks": 0,
                "cancelled_tasks": 0,
                "avg_success_elapsed_sec": None,
                "min_success_elapsed_sec": None,
                "max_success_elapsed_sec": None,
            }

    manager = Viewer360TaskManager(repository=_EmptyRepository(), storage=object())
    assert asyncio.run(manager.statistics())["success_rate"] == 0
