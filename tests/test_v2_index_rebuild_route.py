import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import BaseModel

from csrcqsf.biz.railwayparts import reconstruction_api_models as real_reconstruction_api_models


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
    fake_sgo_module = ModuleType("csrcqsf.biz.sgo")
    fake_sgo_module.SGOBiz = type("SGOBiz", (), {"list_parts_sgo_image": staticmethod(lambda item_id: [])})
    fake_reconstruction_model_module = ModuleType("csrcqsf.models.reconstruction")
    fake_reconstruction_model_module.ReconstructionRecord = type("ReconstructionRecord", (), {})
    with patch.dict(
        sys.modules,
        {
            "csrcqsf.biz.railwayparts.parts": fake_parts_manager_module,
            "csrcqsf.biz.railwayparts.milvus": fake_milvus_module,
            "csrcqsf.biz.railwayparts.auto_processor": fake_auto_processor_module,
            "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager": fake_state_manager_module,
            "csrcqsf.biz.railwayparts.reconstruction_manager": fake_reconstruction_manager_module,
            "csrcqsf.biz.railwayparts.reconstruction_api_models": real_reconstruction_api_models,
            "csrcqsf.biz.sgo": fake_sgo_module,
            "csrcqsf.models.reconstruction": fake_reconstruction_model_module,
        },
    ):
        module_name = "test_parts_service_index_rebuild_route"
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(
            module_name,
            Path("csrcqsf/services/parts.py"),
        )
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module


def test_v2_index_rebuild_route_accepts_rebuild_existing_flag():
    text = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    assert "async def rebuild_v2_index(" in text
    assert "rebuild_existing: bool = False" in text


def test_v2_index_rebuild_route_passes_rebuild_existing_to_background_and_sync_paths():
    text = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    assert "rebuild_existing=rebuild_existing" in text
    assert "ReconstructionIndexRebuildRes(" in text


def test_v2_index_rebuild_route_keeps_single_item_requests_sync():
    text = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    assert "should_background = int_item_id is None and (limit is None or limit > 100) and background_tasks is not None" in text
    assert "message=f'索引重建完成: 成功={result[\"success_count\"]}, 失败={result[\"fail_count\"]}'" in text


def test_v2_index_rebuild_route_returns_summary_for_single_item_requests():
    parts_service = _import_parts_service()
    background_tasks = MagicMock()

    with patch.object(
        parts_service.RailwayPartsManager,
        "rebuild_v2_index",
        AsyncMock(
            return_value={
                "success_count": 3,
                "fail_count": 0,
                "total": 3,
                "processed_item_count": 1,
                "skipped_existing_count": 0,
            }
        ),
        create=True,
    ) as rebuild_mock:
        result = asyncio.run(
            parts_service.rebuild_v2_index(
                item_id="1979020557620613120",
                limit=None,
                rebuild_existing=True,
                background_tasks=background_tasks,
            )
        )

    rebuild_mock.assert_awaited_once_with(
        item_id=1979020557620613120,
        limit=None,
        rebuild_existing=True,
    )
    background_tasks.add_task.assert_not_called()
    assert result.message == "索引重建完成: 成功=3, 失败=0"
    assert result.success_count == 3
    assert result.fail_count == 0
