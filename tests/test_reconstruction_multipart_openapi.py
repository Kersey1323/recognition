import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from fastapi import FastAPI
from pydantic import BaseModel


_PARTS_SERVICE = None


def _import_parts_service():
    global _PARTS_SERVICE
    if _PARTS_SERVICE is not None:
        return _PARTS_SERVICE

    fake_parts_manager_module = ModuleType("csrcqsf.biz.railwayparts.parts")
    fake_parts_manager_module.RailwayPartsManager = type("RailwayPartsManager", (), {})
    fake_milvus_module = ModuleType("csrcqsf.biz.railwayparts.milvus")
    fake_milvus_module.MilvusManager = type("MilvusManager", (), {})
    fake_auto_processor_module = ModuleType("csrcqsf.biz.railwayparts.auto_processor")
    fake_auto_processor_module.AutoPartProcessor = type("AutoPartProcessor", (), {})
    fake_state_manager_module = ModuleType("csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager")
    fake_state_manager_module.MilvusStateManagerV2 = type("MilvusStateManagerV2", (), {})
    fake_reconstruction_manager_module = ModuleType("csrcqsf.biz.railwayparts.reconstruction_manager")
    fake_reconstruction_manager_module.ReconstructionManager = type("ReconstructionManager", (), {})
    fake_sgo_module = ModuleType("csrcqsf.biz.sgo")
    fake_sgo_module.SGOBiz = type("SGOBiz", (), {"list_parts_sgo_image": staticmethod(lambda item_id: [])})
    fake_reconstruction_model_module = ModuleType("csrcqsf.models.reconstruction")
    fake_reconstruction_model_module.ReconstructionRecord = type("ReconstructionRecord", (), {})
    fake_reconstruction_api_models_module = ModuleType("csrcqsf.biz.railwayparts.reconstruction_api_models")

    for name in [
        "ReconstructionTrainReq",
        "ReconstructionVideoReq",
        "ReconstructionTaskRes",
        "ReconstructionStatusRes",
        "ReconstructionListRes",
        "ReconstructionStatisticsReq",
        "ReconstructionStatisticsRes",
        "ReconstructionSourceVideoRes",
        "ReconstructionSourceVideoListReq",
        "ReconstructionSourceVideoListRes",
        "ReconstructionSourceVideoMessageRes",
        "ReconstructionResultMessageRes",
        "ReconstructionResultUploadRes",
        "ReconstructionAllTasksReq",
        "ReconstructionAllTasksRes",
        "ReconstructionIndexRebuildRes",
        "ReconstructionMultipartUploadUrlItem",
        "ReconstructionMultipartUploadedPartItem",
        "ReconstructionVideoUploadAbortReq",
        "ReconstructionVideoUploadCompleteReq",
        "ReconstructionVideoUploadInitReq",
        "ReconstructionVideoUploadInitRes",
        "ReconstructionVideoUploadProgressReq",
        "ReconstructionVideoUploadProgressRes",
        "ReconstructionVideoUploadUrlsReq",
        "ReconstructionVideoUploadUrlsRes",
        "ReconstructionVideoUploadRes",
    ]:
        setattr(fake_reconstruction_api_models_module, name, type(name, (BaseModel,), {}))

    fake_reconstruction_api_models_module.ReconstructionVideoUploadInitReq = type(
        "ReconstructionVideoUploadInitReq",
        (BaseModel,),
        {
            "__annotations__": {
                "item_id": str,
                "file_name": str,
                "file_size": int,
                "content_type": str,
                "height": float | None,
                "length": float | None,
                "width": float | None,
                "weight": float | None,
            }
        },
    )

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.biz.railwayparts.parts": fake_parts_manager_module,
            "csrcqsf.biz.railwayparts.milvus": fake_milvus_module,
            "csrcqsf.biz.railwayparts.auto_processor": fake_auto_processor_module,
            "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager": fake_state_manager_module,
            "csrcqsf.biz.railwayparts.reconstruction_manager": fake_reconstruction_manager_module,
            "csrcqsf.biz.railwayparts.reconstruction_api_models": fake_reconstruction_api_models_module,
            "csrcqsf.biz.sgo": fake_sgo_module,
            "csrcqsf.models.reconstruction": fake_reconstruction_model_module,
        },
    ):
        module_name = "test_parts_service_reconstruction_multipart_openapi"
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, Path("csrcqsf/services/parts.py"))
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        _PARTS_SERVICE = module
        return module


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
    assert "file" not in body_schema["properties"]
