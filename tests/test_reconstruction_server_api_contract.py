import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

import httpx

RECONSTRUCTION_SERVER_DIR = Path("csrcqsf/biz/railwayparts/reconstruction_server").resolve()
if str(RECONSTRUCTION_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(RECONSTRUCTION_SERVER_DIR))

from csrcqsf.biz.railwayparts.reconstruction_server.api import app


async def _request(method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def test_submit_video_route_passes_caller_supplied_task_id_to_celery():
    fake_task = SimpleNamespace(id="ignored-by-test")

    with patch(
        "csrcqsf.biz.railwayparts.reconstruction_server.api.video_reconstruction.apply_async",
        return_value=fake_task,
    ) as apply_mock, patch(
        "csrcqsf.biz.railwayparts.reconstruction_server.api.looks_like_minio_path",
        return_value=True,
    ), patch(
        "os.path.exists",
        return_value=False,
    ):
        response = asyncio.run(
            _request(
                "POST",
                "/reconstruction/tasks/video",
                json={
                    "task_id": "task-from-main-service",
                    "item_id": "1980083913525903360",
                    "video_path": "bfr-3d-videos/raw/demo.mp4",
                    "name": "run-001",
                    "iterations": 30000,
                },
            )
        )

    assert response.status_code == 200
    assert response.json()["task_id"] == "task-from-main-service"
    assert apply_mock.call_args.kwargs["task_id"] == "task-from-main-service"


def test_batch_status_route_returns_standardized_items():
    with patch(
        "csrcqsf.biz.railwayparts.reconstruction_server.api.get_standardized_task_info",
        side_effect=[
            {
                "task_id": "task-1",
                "status": "PROGRESS",
                "progress": 65,
                "current_stage": "SAM3",
                "error_message": None,
                "ply_path": None,
            },
            {
                "task_id": "task-2",
                "status": "SUCCESS",
                "progress": 100,
                "current_stage": "完成",
                "error_message": None,
                "ply_path": "bfr-reconstruction-files/results/task-2/point_cloud.ply",
            },
        ],
    ):
        response = asyncio.run(
            _request(
                "POST",
                "/reconstruction/tasks/status/batch",
                json={"task_ids": ["task-1", "task-2"]},
            )
        )

    assert response.status_code == 200
    assert response.json()["items"][1]["ply_path"].endswith("point_cloud.ply")


def test_internal_scenes_route_keeps_remote_scene_listing():
    with patch(
        "csrcqsf.biz.railwayparts.reconstruction_server.api.list_scenes",
        return_value=["scene-a", "scene-b"],
    ):
        response = asyncio.run(_request("GET", "/reconstruction/scenes"))

    assert response.status_code == 200
    assert response.json() == {"scenes": ["scene-a", "scene-b"]}
