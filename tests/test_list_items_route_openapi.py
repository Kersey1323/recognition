import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from fastapi import FastAPI


def _clear_module(prefix: str) -> None:
    for name in list(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            sys.modules.pop(name, None)


def _seed_routes_package() -> None:
    package = ModuleType("csrcqsf.modules.railway_parts.routes")
    package.__path__ = [str(Path("csrcqsf/modules/railway_parts/routes").resolve())]
    sys.modules["csrcqsf.modules.railway_parts.routes"] = package


def _import_parts_route_subset():
    _clear_module("csrcqsf.modules.railway_parts.routes")
    _clear_module("csrcqsf.runtime")
    _seed_routes_package()

    fake_parts_service_module = ModuleType("csrcqsf.modules.railway_parts.services.parts_service")
    fake_parts_service_module.RailwayPartsManager = type("RailwayPartsManager", (), {})

    fake_sgo_services_module = ModuleType("csrcqsf.modules.sgo.services")
    fake_sgo_services_module.SGOBiz = type("SGOBiz", (), {})

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.railway_parts.services.parts_service": fake_parts_service_module,
            "csrcqsf.modules.sgo.services": fake_sgo_services_module,
        },
    ):
        router_module = importlib.import_module("csrcqsf.modules.railway_parts.routes.router")
        importlib.import_module("csrcqsf.modules.railway_parts.routes.parts_routes")
        module = ModuleType("test_parts_routes_subset")
        module.parts_router = router_module.parts_router
        return module


def test_list_items_openapi_exposes_item_code_filter():
    route_subset = _import_parts_route_subset()
    app = FastAPI()
    app.include_router(route_subset.parts_router)
    schema = app.openapi()

    request_body = schema["paths"]["/railway/parts/list_items"]["post"]["requestBody"]
    body_schema_ref = request_body["content"]["application/json"]["schema"]["$ref"]
    body_schema_name = body_schema_ref.split("/")[-1]
    body_schema = schema["components"]["schemas"][body_schema_name]

    assert "item_code" in body_schema["properties"]
    assert body_schema["properties"]["item_code"]["type"] == "string"


def test_list_items_openapi_exposes_exact_item_name_filter():
    route_subset = _import_parts_route_subset()
    app = FastAPI()
    app.include_router(route_subset.parts_router)
    schema = app.openapi()

    request_body = schema["paths"]["/railway/parts/list_items"]["post"]["requestBody"]
    body_schema_ref = request_body["content"]["application/json"]["schema"]["$ref"]
    body_schema_name = body_schema_ref.split("/")[-1]
    body_schema = schema["components"]["schemas"][body_schema_name]

    assert "item_name" in body_schema["properties"]
    assert body_schema["properties"]["item_name"]["type"] == "string"


def test_list_items_openapi_exposes_vehicle_batch_filter():
    route_subset = _import_parts_route_subset()
    app = FastAPI()
    app.include_router(route_subset.parts_router)
    schema = app.openapi()

    request_body = schema["paths"]["/railway/parts/list_items"]["post"]["requestBody"]
    body_schema_ref = request_body["content"]["application/json"]["schema"]["$ref"]
    body_schema_name = body_schema_ref.split("/")[-1]
    body_schema = schema["components"]["schemas"][body_schema_name]

    assert "vehicle_batch" in body_schema["properties"]
    assert body_schema["properties"]["vehicle_batch"]["type"] == "string"
