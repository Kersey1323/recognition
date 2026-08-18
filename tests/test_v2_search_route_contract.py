import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from pydantic import BaseModel

from csrcqsf.modules.railway_parts.schemas.search import SearchRes, SearchTextReq


def _clear_module(prefix: str) -> None:
    for name in list(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            sys.modules.pop(name, None)


def _seed_routes_package() -> None:
    package = ModuleType("csrcqsf.modules.railway_parts.routes")
    package.__path__ = [str(Path("csrcqsf/modules/railway_parts/routes").resolve())]
    sys.modules["csrcqsf.modules.railway_parts.routes"] = package


def _import_parts_service():
    _clear_module("csrcqsf.modules.railway_parts.routes")
    _clear_module("csrcqsf.runtime")
    _seed_routes_package()
    fake_parts_service_module = ModuleType("csrcqsf.modules.railway_parts.services.parts_service")
    fake_parts_service_module.RailwayPartsManager = type("RailwayPartsManager", (), {})
    fake_state_manager_module = ModuleType("csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager")
    fake_state_manager_module.MilvusStateManagerV2 = type("MilvusStateManagerV2", (), {})
    fake_index_rebuild_module = ModuleType(
        "csrcqsf.modules.railway_parts.services.index_rebuild_task_manager"
    )
    fake_index_rebuild_module.index_rebuild_task_manager = object()
    fake_reconstruction_api_models_module = ModuleType("csrcqsf.modules.railway_parts.schemas.reconstruction")
    for name in [
        "ReconstructionIndexRebuildRes",
        "ReconstructionIndexRebuildStatusRes",
        "ReconstructionIndexTaskCancelReq",
        "ReconstructionIndexTaskListReq",
        "ReconstructionIndexTaskListRes",
    ]:
        setattr(fake_reconstruction_api_models_module, name, type(name, (BaseModel,), {}))

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.railway_parts.services.parts_service": fake_parts_service_module,
            "csrcqsf.modules.railway_parts.services.index_rebuild_task_manager": fake_index_rebuild_module,
            "csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager": fake_state_manager_module,
            "csrcqsf.modules.railway_parts.schemas.reconstruction": fake_reconstruction_api_models_module,
        },
    ):
        router_module = importlib.import_module("csrcqsf.modules.railway_parts.routes.router")
        search_routes_module = importlib.import_module("csrcqsf.modules.railway_parts.routes.search_routes")
        module = ModuleType("test_search_routes_subset")
        module.parts_router = router_module.parts_router
        module.RailwayPartsManager = search_routes_module.RailwayPartsManager
        module.search_v2_by_text = search_routes_module.search_v2_by_text
        return module


def test_text_search_route_accepts_request_body_model():
    parts_service = _import_parts_service()
    payload = SearchRes(history_id="2048696242753638400", data=[], message=None)

    with patch.object(parts_service.RailwayPartsManager, "search_v2_by_text", AsyncMock(return_value=payload), create=True) as search_mock:
        result = asyncio.run(
            parts_service.search_v2_by_text(
                SearchTextReq(query_text="制动盘", top_k=5)
            )
        )

    assert result.history_id == "2048696242753638400"
    assert search_mock.await_args.kwargs == {
        "query_text": "制动盘",
        "top_k": 5,
        "search_equipment": "web",
    }


def test_parts_service_unifies_single_and_multi_image_search_on_one_route():
    parts_service = _import_parts_service()
    app = FastAPI()
    app.include_router(parts_service.parts_router)
    schema = app.openapi()

    assert "/railway/parts/v2/search/image" in schema["paths"]
    assert "/railway/parts/v2/search/images" not in schema["paths"]

    body_schema_ref = schema["paths"]["/railway/parts/v2/search/image"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
    body_schema_name = body_schema_ref.split("/")[-1]
    body_schema = schema["components"]["schemas"][body_schema_name]

    assert "file" in body_schema["properties"]
    assert body_schema["properties"]["file"]["type"] == "array"
    assert body_schema["properties"]["file"]["items"]["format"] == "binary"
