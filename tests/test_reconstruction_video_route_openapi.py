import asyncio

from fastapi import FastAPI
from unittest.mock import AsyncMock, patch

from csrcqsf.modules.railway_parts.schemas.reconstruction import ReconstructionVideoReq
from csrcqsf.modules.railway_parts.routes.router import parts_router
from csrcqsf.modules.railway_parts.routes import reconstruction_routes


def _build_app():
    app = FastAPI()
    app.include_router(parts_router)
    return app


def test_reconstruction_video_openapi_exposes_only_item_and_iterations():
    app = _build_app()
    schema = app.openapi()

    request_body = schema["paths"]["/railway/parts/v2/reconstruct/tasks/video"]["post"]["requestBody"]
    body_schema_ref = request_body["content"]["application/json"]["schema"]["$ref"]
    body_schema_name = body_schema_ref.split("/")[-1]
    body_schema = schema["components"]["schemas"][body_schema_name]

    assert set(body_schema["properties"]) == {"item_id", "iterations"}
    assert set(body_schema["required"]) == {"item_id", "iterations"}


def test_reconstruction_video_route_forwards_only_business_fields():
    mocked_submit = AsyncMock(
        return_value={
            "task_id": "task-123",
            "item_id": 1001,
            "mode": "video",
            "message": "视频重建任务已提交",
        }
    )

    with patch.object(reconstruction_routes, "ensure_gpu_reconstruction_enabled", return_value=None), \
         patch.object(reconstruction_routes.ReconstructionManager, "submit_video_task", mocked_submit):
        response = asyncio.run(
            reconstruction_routes.reconstruct_v2_video(
                ReconstructionVideoReq(
                    item_id="1001",
                    iterations=10000,
                )
            )
        )

    assert response.task_id == "task-123"
    assert mocked_submit.await_args.kwargs == {
        "item_id": 1001,
        "iterations": 10000,
    }
