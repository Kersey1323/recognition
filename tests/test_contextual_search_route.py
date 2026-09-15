import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from csrcqsf.modules.railway_parts.schemas.search import (
    ContextualSearchRes,
    SearchItem,
    SearchHistoryListItem,
)
from csrcqsf.modules.railway_parts.services.contextual_search_service import (
    ContextualSearchBusinessError,
)


def _clear_module(prefix: str) -> None:
    for name in list(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            sys.modules.pop(name, None)


def _import_search_routes():
    cached = getattr(_import_search_routes, "_cached", None)
    if cached is not None:
        return cached
    _clear_module("csrcqsf.modules.railway_parts.routes")
    package = ModuleType("csrcqsf.modules.railway_parts.routes")
    package.__path__ = [str(Path("csrcqsf/modules/railway_parts/routes").resolve())]
    sys.modules["csrcqsf.modules.railway_parts.routes"] = package

    fake_parts_service = ModuleType("csrcqsf.modules.railway_parts.services.parts_service")
    fake_parts_service.RailwayPartsManager = type("RailwayPartsManager", (), {})
    fake_state_manager = ModuleType(
        "csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager"
    )
    fake_state_manager.MilvusStateManagerV2 = type("MilvusStateManagerV2", (), {})
    fake_reconstruction_models = ModuleType(
        "csrcqsf.modules.railway_parts.schemas.reconstruction"
    )
    for name in [
        "ReconstructionIndexRebuildRes",
        "ReconstructionIndexRebuildStatusRes",
        "ReconstructionIndexTaskCancelReq",
        "ReconstructionIndexTaskListReq",
        "ReconstructionIndexTaskListRes",
    ]:
        setattr(fake_reconstruction_models, name, type(name, (BaseModel,), {}))

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.railway_parts.services.parts_service": fake_parts_service,
            "csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager": fake_state_manager,
            "csrcqsf.modules.railway_parts.schemas.reconstruction": fake_reconstruction_models,
        },
    ):
        router_module = importlib.import_module(
            "csrcqsf.modules.railway_parts.routes.router"
        )
        routes = importlib.import_module(
            "csrcqsf.modules.railway_parts.routes.search_routes"
        )
        _import_search_routes._cached = (routes, router_module.parts_router)
        return _import_search_routes._cached


def test_contextual_search_openapi_uses_optional_files_and_siglip_default():
    _, router = _import_search_routes()
    app = FastAPI()
    app.include_router(router)

    operation = app.openapi()["paths"]["/railway/parts/v2/search/contextual"]["post"]
    assert operation["summary"] == "带业务条件的V2图片/描述检索"
    body_ref = operation["requestBody"]["content"]["multipart/form-data"]["schema"][
        "$ref"
    ]
    body = app.openapi()["components"]["schemas"][body_ref.split("/")[-1]]

    assert "history_id" in body["properties"]
    assert "file" in body["properties"]
    assert "item_description" in body["properties"]
    assert "top_k" not in body["properties"]
    assert body["properties"]["search_mode"]["default"] == "siglip"
    assert "file" not in body.get("required", [])
    assert "history_id" not in body.get("required", [])


def test_contextual_search_route_delegates_all_business_inputs():
    routes, _ = _import_search_routes()
    payload = ContextualSearchRes(
        history_id="101",
        previous=None,
        current={
            "query_images": ["new.jpg"],
            "parameters": {"search_mode": "siglip"},
            "searched_at": "2026-08-18 10:00:00",
            "data": [],
        },
    )
    search_mock = AsyncMock(return_value=payload)

    with patch.object(
        routes.RailwayPartsManager,
        "search_v2_contextual",
        search_mock,
        create=True,
    ):
        result = asyncio.run(
            routes.search_v2_contextual(
                history_id="101",
                file=[],
                vehicle_batch="SFE27",
                item_name="按钮",
                item_description="卫生间墙面上的冲洗按钮",
                train_no="2777",
                car_num="01",
                subordinate_component="卫生间",
                search_mode="siglip",
                search_equipment="web",
            )
        )

    assert result.history_id == "101"
    assert search_mock.await_args.kwargs == {
        "history_id": 101,
        "files": [],
        "vehicle_batch": "SFE27",
        "item_name": "按钮",
        "item_description": "卫生间墙面上的冲洗按钮",
        "train_no": "2777",
        "car_num": "01",
        "subordinate_component": "卫生间",
        "search_mode": "siglip",
        "search_equipment": "web",
    }


def test_contextual_search_route_enriches_each_snapshot_with_its_vehicle():
    routes, _ = _import_search_routes()
    payload = ContextualSearchRes(
        history_id="101",
        previous={
            "query_images": [],
            "parameters": {"vehicle_batch": "SFE28", "search_mode": "siglip"},
            "searched_at": "2026-08-18 09:00:00",
            "data": [SearchItem(item_id="1", item_code="A")],
        },
        current={
            "query_images": [],
            "parameters": {"vehicle_batch": "SFE27", "search_mode": "siglip"},
            "searched_at": "2026-08-18 10:00:00",
            "data": [SearchItem(item_id="2", item_code="B")],
        },
    )
    with patch.object(
        routes.RailwayPartsManager, "search_v2_contextual",
        AsyncMock(return_value=payload), create=True,
    ), patch.object(routes, "enrich_search_items", AsyncMock()) as enrich:
        asyncio.run(routes.search_v2_contextual(history_id="101", file=[]))

    assert enrich.await_count == 2
    assert enrich.await_args_list[0].args == (payload.current.data,)
    assert enrich.await_args_list[0].kwargs == {"vehicle_batch": "SFE27"}
    assert enrich.await_args_list[1].args == (payload.previous.data,)
    assert enrich.await_args_list[1].kwargs == {"vehicle_batch": "SFE28"}


def test_contextual_search_route_accepts_swagger_empty_file_field():
    routes, router = _import_search_routes()
    app = FastAPI()
    app.include_router(router)
    payload = ContextualSearchRes(
        history_id="101",
        previous=None,
        current={
            "query_images": [],
            "parameters": {"item_description": "厕所里的马桶盖"},
            "searched_at": "2026-08-31 10:00:00",
            "data": [],
        },
    )
    search_mock = AsyncMock(return_value=payload)

    api_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/railway/parts/v2/search/contextual"
    )
    request_body = api_route.body_field.type_(
        file=[""],
        item_description="厕所里的马桶盖",
    )

    with patch.object(
        routes.RailwayPartsManager,
        "search_v2_contextual",
        search_mock,
        create=True,
    ):
        response = asyncio.run(
            routes.search_v2_contextual(
                history_id=None,
                file=request_body.file,
                vehicle_batch=None,
                item_name=None,
                item_description=request_body.item_description,
                train_no=None,
                car_num=None,
                subordinate_component=None,
                search_mode="siglip",
                search_equipment="web",
            )
        )

    assert response.history_id == "101"
    assert search_mock.await_args.kwargs["files"] == []


def test_contextual_search_route_preserves_business_error_status():
    routes, _ = _import_search_routes()

    with patch.object(
        routes.RailwayPartsManager,
        "search_v2_contextual",
        AsyncMock(side_effect=ContextualSearchBusinessError(409, "只有 pending 状态允许再次检索")),
        create=True,
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(routes.search_v2_contextual(history_id="101", file=[]))

    assert exc.value.status_code == 409


def test_contextual_search_route_rejects_non_numeric_history_id():
    routes, _ = _import_search_routes()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.search_v2_contextual(history_id="not-a-number", file=[]))

    assert exc.value.status_code == 422


def test_search_history_detail_schema_exposes_previous_window_fields():
    field_names = set(SearchHistoryListItem.__fields__)

    assert "search_parameter" in field_names
    assert "previous_query_images" in field_names
    assert "previous_search_parameter" in field_names
    assert "previous_result" in field_names
    assert "previous_searched_at" in field_names
    assert "search_revision" in field_names
