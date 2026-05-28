import asyncio
import importlib
import os
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel


def _clear_module(prefix: str) -> None:
    for name in list(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            sys.modules.pop(name, None)


def _import_parts_service():
    _clear_module("csrcqsf.services.parts")
    _clear_module("csrcqsf.runtime")

    flexible_model = type(
        "_FlexibleModel",
        (BaseModel,),
        {"Config": type("Config", (), {"extra": "allow"})},
    )

    fake_reconstruction_api_models = ModuleType("csrcqsf.biz.railwayparts.reconstruction_api_models")
    for name in [
        "ReconstructionTrainReq",
        "ReconstructionVideoReq",
        "ReconstructionTaskRes",
        "ReconstructionStatusRes",
        "ReconstructionStatisticsReq",
        "ReconstructionStatisticsRes",
        "ReconstructionListRes",
        "ReconstructionAllTasksReq",
        "ReconstructionAllTasksRes",
        "ReconstructionSourceVideoListReq",
        "ReconstructionSourceVideoListRes",
        "ReconstructionSourceVideoMessageRes",
        "ReconstructionSourceVideoRes",
        "ReconstructionResultMessageRes",
        "ReconstructionResultUploadRes",
        "ReconstructionVideoUploadInitReq",
        "ReconstructionVideoUploadInitRes",
        "ReconstructionVideoUploadPartReq",
        "ReconstructionVideoUploadProgressReq",
        "ReconstructionVideoUploadProgressRes",
        "ReconstructionVideoUploadUrlsReq",
        "ReconstructionVideoUploadUrlsRes",
        "ReconstructionVideoUploadCompleteReq",
        "ReconstructionVideoUploadAbortReq",
        "ReconstructionVideoUploadMinioHealthRes",
        "ReconstructionMultipartUploadUrlItem",
        "ReconstructionMultipartUploadedPartItem",
        "ReconstructionIndexRebuildRes",
    ]:
        setattr(fake_reconstruction_api_models, name, type(name, (flexible_model,), {}))

    fake_api_models = ModuleType("csrcqsf.biz.railwayparts.api_models")
    for name in [
        "CreateItemReq",
        "DeleteItemReq",
        "UpdateItemReq",
        "UpdateItemSizeStr",
        "ListItemReq",
        "LisItemRes",
        "ListItemImagesReq",
        "ListItemImagesRes",
        "ListItemImageItem",
        "CreateItemImagesReq",
        "CreateItemImagesRes",
        "GetItemDetailReq",
        "GetItemDetailRes",
        "IndexStatisticsReq",
        "IndexStatisticsRes",
        "AutoSegmentReq",
        "AutoSegmentRes",
        "ListSegmentedImagesRes",
        "SegmentedImageItem",
        "V2IndexDeleteRes",
        "SearchTextReq",
        "SearchHistoryListReq",
        "SearchHistoryListRes",
        "SearchHistoryListItem",
        "SearchHistoryDetailReq",
        "SearchHistorySummaryRes",
        "SearchHistoryVerifyReq",
        "SearchHistoryVerifyRes",
        "SearchHistoryFeedbackReq",
        "SearchHistoryFeedbackRes",
        "SearchReviewTicketListReq",
        "SearchReviewTicketListRes",
        "SearchReviewTicketDetailReq",
        "SearchReviewTicketDetailRes",
        "SearchReviewTicketUpdateReq",
        "SearchReviewTicketUpdateRes",
        "SearchReviewTicketSummaryRes",
        "ItemSuggestReq",
        "ItemSuggestRes",
        "SearchHistoryDeleteReq",
        "SearchHistoryDeleteRes",
    ]:
        setattr(fake_api_models, name, type(name, (flexible_model,), {}))
    fake_api_models.__all__ = [name for name in fake_api_models.__dict__ if not name.startswith("_")]

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

    fake_settings_module = ModuleType("csrcqsf.settings")
    fake_settings_module.ai_settings = SimpleNamespace()
    fake_settings_module.reconstruction_server_env_configured = lambda: bool(os.getenv("RECONSTRUCTION_SERVER_URL"))

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.biz.railwayparts.api_models": fake_api_models,
            "csrcqsf.biz.railwayparts.reconstruction_api_models": fake_reconstruction_api_models,
            "csrcqsf.biz.railwayparts.parts": fake_parts_manager_module,
            "csrcqsf.biz.railwayparts.milvus": fake_milvus_module,
            "csrcqsf.biz.railwayparts.auto_processor": fake_auto_processor_module,
            "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager": fake_state_manager_module,
            "csrcqsf.biz.railwayparts.reconstruction_manager": fake_reconstruction_manager_module,
            "csrcqsf.biz.sgo": fake_sgo_module,
            "csrcqsf.settings": fake_settings_module,
        },
    ):
        return importlib.import_module("csrcqsf.services.parts")


def test_reconstruction_routes_reject_when_remote_service_url_missing(monkeypatch):
    monkeypatch.delenv("RECONSTRUCTION_SERVER_URL", raising=False)
    monkeypatch.setenv("ENABLE_GPU_RECONSTRUCTION", "1")
    parts_service = _import_parts_service()

    req = SimpleNamespace(item_id="1001", scene="demo", iterations=1000, output_name=None)

    try:
        asyncio.run(parts_service.reconstruct_v2_train(req))
    except Exception as exc:
        assert "未配置重构服务" in str(exc)
    else:
        raise AssertionError("expected reconstruction route to be blocked without RECONSTRUCTION_SERVER_URL")


def test_reconstruction_routes_allow_when_remote_service_url_present(monkeypatch):
    monkeypatch.setenv("RECONSTRUCTION_SERVER_URL", "http://gpu-service:8000")
    monkeypatch.setenv("ENABLE_GPU_RECONSTRUCTION", "0")
    parts_service = _import_parts_service()

    req = SimpleNamespace(item_id="1001", scene="demo", iterations=1000, output_name=None)

    with patch.object(
        parts_service.ReconstructionManager,
        "submit_train_task",
        AsyncMock(return_value={"task_id": "task-1", "item_id": "1001", "mode": "train", "message": "训练任务已提交"}),
        create=True,
    ):
        result = asyncio.run(parts_service.reconstruct_v2_train(req))

    assert getattr(result, "task_id", None) == "task-1" or result.dict()["task_id"] == "task-1"
