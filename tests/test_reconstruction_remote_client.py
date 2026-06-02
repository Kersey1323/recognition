import asyncio

from csrcqsf.modules.railway_parts.integrations.reconstruction_client import ReconstructionServiceClient


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return str(self._payload)


class _FakeSession:
    def __init__(self, recorder: dict, payload: dict):
        self.recorder = recorder
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def request(self, method: str, url: str, json=None):
        self.recorder["method"] = method
        self.recorder["url"] = url
        self.recorder["json"] = json
        return _FakeResponse(self.payload)


def test_reconstruction_client_posts_video_task_to_internal_route():
    recorder = {}
    client = ReconstructionServiceClient(base_url="http://reconstruction:8000", timeout_sec=9)

    from unittest.mock import patch

    with patch(
        "aiohttp.ClientSession",
        return_value=_FakeSession(
            recorder,
            {"task_id": "task-1", "status": "SUBMITTED", "message": "ok"},
        ),
    ):
        result = asyncio.run(
            client.submit_video_task(
                {
                    "task_id": "task-1",
                    "item_id": "1001",
                    "video_path": "bfr-3d-videos/raw/demo.mp4",
                    "name": "run-001",
                }
            )
        )

    assert result["task_id"] == "task-1"
    assert recorder["method"] == "POST"
    assert recorder["url"] == "http://reconstruction:8000/reconstruction/tasks/video"


def test_reconstruction_client_posts_batch_status_route():
    recorder = {}
    client = ReconstructionServiceClient(base_url="http://reconstruction:8000", timeout_sec=9)

    from unittest.mock import patch

    with patch(
        "aiohttp.ClientSession",
        return_value=_FakeSession(
            recorder,
            {
                "items": [
                    {
                        "task_id": "task-1",
                        "status": "SUCCESS",
                        "progress": 100,
                        "current_stage": "完成",
                        "error_message": None,
                        "ply_path": "bfr-reconstruction-files/results/task-1/point_cloud.ply",
                    }
                ]
            },
        ),
    ):
        result = asyncio.run(client.get_task_status_batch(["task-1"]))

    assert result["items"][0]["ply_path"].endswith("point_cloud.ply")
    assert recorder["method"] == "POST"
    assert recorder["url"] == "http://reconstruction:8000/reconstruction/tasks/status/batch"
    assert recorder["json"] == {"task_ids": ["task-1"]}
