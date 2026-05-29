import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from fastapi import FastAPI
from pydantic import BaseModel


_PARTS_SERVICE = None


def _clear_module(prefix: str) -> None:
    for name in list(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            sys.modules.pop(name, None)


def _seed_routes_package() -> None:
    package = ModuleType("csrcqsf.modules.railway_parts.routes")
    package.__path__ = [str(Path("csrcqsf/modules/railway_parts/routes").resolve())]
    sys.modules["csrcqsf.modules.railway_parts.routes"] = package


def _import_parts_service():
    global _PARTS_SERVICE
    if _PARTS_SERVICE is not None:
        return _PARTS_SERVICE

    _clear_module("csrcqsf.modules.railway_parts.routes")
    _clear_module("csrcqsf.runtime")
    _seed_routes_package()
    fake_reconstruction_service_module = ModuleType("csrcqsf.modules.railway_parts.services.reconstruction_service")
    fake_reconstruction_service_module.ReconstructionManager = type("ReconstructionManager", (), {})

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.railway_parts.services.reconstruction_service": fake_reconstruction_service_module,
        },
    ):
        router_module = importlib.import_module("csrcqsf.modules.railway_parts.routes.router")
        reconstruction_routes_module = importlib.import_module("csrcqsf.modules.railway_parts.routes.reconstruction_routes")
        _PARTS_SERVICE = ModuleType("test_reconstruction_routes_subset")
        _PARTS_SERVICE.parts_router = router_module.parts_router
        _PARTS_SERVICE.init_reconstruct_v2_video_upload = reconstruction_routes_module.init_reconstruct_v2_video_upload
        return _PARTS_SERVICE


def test_reconstruction_multipart_init_route_uses_json_metadata_only():
    parts_service = _import_parts_service()
    app = FastAPI()
    app.include_router(parts_service.parts_router)
    schema = app.openapi()

    content = schema["paths"]["/railway/parts/v2/reconstruct/video/upload/init"]["post"]["requestBody"]["content"]
    assert "application/json" in content

    body_schema_ref = content["application/json"]["schema"]["$ref"]
    body_schema_name = body_schema_ref.split("/")[-1]
    body_schema = schema["components"]["schemas"][body_schema_name]

    assert body_schema["properties"]["item_id"]["type"] == "string"
    assert body_schema["properties"]["file_name"]["type"] == "string"
    assert body_schema["properties"]["file_size"]["type"] == "integer"
    assert "file_name" in body_schema["required"]
    assert "file_size" in body_schema["required"]
    assert "storage_mode" in body_schema["properties"]
    assert "file" not in body_schema["properties"]
