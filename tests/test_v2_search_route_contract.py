import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel

from csrcqsf.biz.railwayparts.api_models import SearchRes, SearchTextReq


def _import_parts_service():
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
    ]:
        setattr(fake_reconstruction_api_models_module, name, type(name, (BaseModel,), {}))

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.biz.railwayparts.parts": fake_parts_manager_module,
            "csrcqsf.biz.railwayparts.milvus": fake_milvus_module,
            "csrcqsf.biz.railwayparts.auto_processor": fake_auto_processor_module,
            "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager": fake_state_manager_module,
            "csrcqsf.biz.railwayparts.reconstruction_manager": fake_reconstruction_manager_module,
            "csrcqsf.biz.railwayparts.reconstruction_api_models": fake_reconstruction_api_models_module,
        },
    ):
        module_name = "test_parts_service_search_route"
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(
            module_name,
            Path("csrcqsf/services/parts.py"),
        )
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
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
