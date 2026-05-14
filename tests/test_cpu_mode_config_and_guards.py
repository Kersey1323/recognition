import asyncio
import importlib
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import APIRouter
from pydantic import BaseModel


def _parse_env_file(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def _clear_module(prefix: str) -> None:
    for name in list(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            sys.modules.pop(name, None)


def _build_api_model_module() -> ModuleType:
    module = ModuleType("csrcqsf.biz.railwayparts.api_models")

    names = [
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
    ]
    for name in names:
        setattr(module, name, type(name, (BaseModel,), {}))

    module.__all__ = names
    return module


def _build_reconstruction_api_model_module() -> ModuleType:
    module = ModuleType("csrcqsf.biz.railwayparts.reconstruction_api_models")
    names = [
        "ReconstructionAllTasksReq",
        "ReconstructionAllTasksRes",
        "ReconstructionIndexRebuildRes",
        "ReconstructionListRes",
        "ReconstructionMultipartUploadUrlItem",
        "ReconstructionMultipartUploadedPartItem",
        "ReconstructionResultMessageRes",
        "ReconstructionResultUploadRes",
        "ReconstructionSourceVideoListReq",
        "ReconstructionSourceVideoListRes",
        "ReconstructionSourceVideoMessageRes",
        "ReconstructionSourceVideoRes",
        "ReconstructionStatisticsReq",
        "ReconstructionStatisticsRes",
        "ReconstructionStatusRes",
        "ReconstructionTaskRes",
        "ReconstructionTrainReq",
        "ReconstructionVideoReq",
        "ReconstructionVideoUploadAbortReq",
        "ReconstructionVideoUploadCompleteReq",
        "ReconstructionVideoUploadInitReq",
        "ReconstructionVideoUploadInitRes",
        "ReconstructionVideoUploadProgressReq",
        "ReconstructionVideoUploadProgressRes",
        "ReconstructionVideoUploadUrlsReq",
        "ReconstructionVideoUploadUrlsRes",
    ]
    for name in names:
        setattr(module, name, type(name, (BaseModel,), {}))

    module.__all__ = names
    return module


def _import_parts_service():
    _clear_module("csrcqsf.services.parts")
    _clear_module("csrcqsf.runtime")

    fake_api_models = _build_api_model_module()
    fake_reconstruction_api_models = _build_reconstruction_api_model_module()

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


def _import_image_service():
    _clear_module("csrcqsf.services.images")
    _clear_module("csrcqsf.runtime")

    fake_segment_module = ModuleType("csrcqsf.biz.segment")
    fake_segment_module.SegmentBiz = type("SegmentBiz", (), {})

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.biz.segment": fake_segment_module,
        },
    ):
        return importlib.import_module("csrcqsf.services.images")


def test_env_cpu_disables_gpu_and_model_capabilities():
    values = _parse_env_file(Path(".env.cpu"))

    assert values["ENABLE_CPU_SAFE_MODE"] == "1"
    assert values["ENABLE_GPU_RECONSTRUCTION"] == "0"
    assert values["ENABLE_SEGMENT_MODEL"] == "0"
    assert values["ENABLE_VECTOR_MODELS"] == "0"
    assert values["ENABLE_OCR_MODEL"] == "0"
    assert values["SIGLIP_DEVICE"] == "cpu"
    assert values["DINOV2_DEVICE"] == "cpu"
    assert values["SAM3_DEVICE"] == "cpu"


def test_dockerfile_cpu_uses_cpu_base_and_no_cuda_install():
    text = Path("Dockerfile.cpu").read_text(encoding="utf-8")

    assert "FROM python:3.10-slim" in text
    assert "nvidia/cuda" not in text
    assert "ARG PYTORCH_CPU_INDEX_URL" in text
    assert "ARG PYTORCH_CPU_FALLBACK_INDEX_URL" in text
    assert "mirrors.aliyun.com/pytorch-wheels/cpu" in text
    assert "download.pytorch.org/whl/cpu" in text
    assert "--no-install-package torch" in text
    assert "--no-install-package torchvision" in text


def test_run_docker_cpu_script_has_no_gpu_flag():
    text = Path("scripts/deployment/run_docker_cpu.sh").read_text(encoding="utf-8")

    assert "--gpus all" not in text
    assert "docker build" not in text
    assert "docker run -d" in text
    assert ".env.cpu" in text


def test_dockerfile_cpu_supports_configurable_mirrors():
    text = Path("Dockerfile.cpu").read_text(encoding="utf-8")

    assert "ARG APT_MIRROR" in text
    assert "ARG PIP_INDEX_URL" in text
    assert "ARG PYTORCH_CPU_INDEX_URL" in text
    assert "ARG PYTORCH_CPU_FALLBACK_INDEX_URL" in text
    assert "${PIP_INDEX_URL}" in text
    assert "${PYTORCH_CPU_INDEX_URL}" in text
    assert "${PYTORCH_CPU_FALLBACK_INDEX_URL}" in text
    assert text.rfind('torch==2.7.1+cpu') > text.rfind('COPY . /app')


def test_run_docker_cpu_script_runs_prebuilt_image_with_host_mount():
    text = Path("scripts/deployment/run_docker_cpu.sh").read_text(encoding="utf-8")

    assert "HOST_DIR" in text
    assert 'docker rm -f "${CONTAINER_NAME}"' in text
    assert '--env-file "${ENV_FILE}"' in text
    assert '-v "${HOST_DIR}":/app' in text


def test_parts_service_rejects_gpu_reconstruction_when_disabled(monkeypatch):
    monkeypatch.setenv("ENABLE_GPU_RECONSTRUCTION", "0")
    parts_service = _import_parts_service()

    req = SimpleNamespace(item_id="1001", scene="demo", iterations=1000, output_name=None)

    try:
        asyncio.run(parts_service.reconstruct_v2_train(req))
    except Exception as exc:
        assert "当前无GPU，无法使用" in str(exc)
    else:
        raise AssertionError("expected GPU reconstruction route to be blocked")


def test_parts_service_rejects_vector_routes_when_cpu_safe_mode_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_CPU_SAFE_MODE", "1")
    monkeypatch.setenv("ENABLE_VECTOR_MODELS", "1")
    parts_service = _import_parts_service()

    req = SimpleNamespace(query_text="制动盘", top_k=5, search_equipment="web")

    try:
        asyncio.run(parts_service.search_v2_by_text(req))
    except Exception as exc:
        assert "CPU模式下已禁用" in str(exc)
    else:
        raise AssertionError("expected vector route to be blocked in cpu safe mode")


def test_image_service_rejects_ocr_when_disabled(monkeypatch):
    monkeypatch.setenv("ENABLE_OCR_MODEL", "0")
    image_service = _import_image_service()

    req = SimpleNamespace(file_url="http://example.com/demo.jpg")

    try:
        asyncio.run(image_service.front_image(req))
    except Exception as exc:
        assert "当前未配置模型，无法使用" in str(exc)
    else:
        raise AssertionError("expected OCR route to be blocked")


def test_app_lifespan_skips_segmentbiz_init_when_segment_disabled(monkeypatch):
    monkeypatch.setenv("ENABLE_SEGMENT_MODEL", "0")
    monkeypatch.setenv("ENABLE_OCR_MODEL", "0")

    _clear_module("csrcqsf.app")
    _clear_module("csrcqsf.runtime")

    fake_services_module = ModuleType("csrcqsf.services")
    fake_services_module.parts_router = APIRouter()
    fake_services_module.sgo_router = APIRouter()
    fake_services_module.parts_docs_router = APIRouter()
    fake_services_module.image_router = APIRouter()

    fake_doc_router_module = ModuleType("bfrcommon.doc_router")
    fake_doc_router_module.make_doc_router = lambda *args, **kwargs: None
    fake_doc_router_module.doc_router = SimpleNamespace(routes=[])

    fake_response_module = ModuleType("bfrcommon.middlewares.response")
    fake_response_module.DefaultResponse = dict
    fake_response_module.catch_exceptions_middleware = lambda logger=None, limit=4: (
        lambda request, call_next: call_next(request)
    )

    fake_auth_module = ModuleType("bfrcommon.middlewares.auth")
    fake_auth_module.add_process_time_header = lambda logger=None: (
        lambda request, call_next: call_next(request)
    )
    fake_auth_module.auth_middleware = lambda request, call_next: call_next(request)

    fake_logger_module = ModuleType("globals_vars")
    fake_logger_module.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )

    fake_segment_module = ModuleType("csrcqsf.biz.segment")
    fake_segment_module.SegmentBiz = type("SegmentBiz", (), {"init": AsyncMock()})

    fake_pg_module = ModuleType("csrcqsf.data.pg")
    fake_pg_module.db_migrate = AsyncMock()

    fake_minio_module = ModuleType("csrcqsf.data.minio")
    fake_minio_module.create_minio_buckets = AsyncMock()

    fake_sgo_module = ModuleType("csrcqsf.biz.sgo")
    fake_sgo_module.SGOBiz = type("SGOBiz", (), {"init": staticmethod(lambda: None)})

    fake_api_models_module = ModuleType("csrcqsf.api_models")
    fake_api_models_module.SimpleSegmentReq = type(
        "SimpleSegmentReq",
        (BaseModel,),
        {"__annotations__": {"file_url": str}},
    )
    fake_api_models_module.SimpleSegmentRes = type(
        "SimpleSegmentRes",
        (BaseModel,),
        {"mask": ""},
    )

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.services": fake_services_module,
            "bfrcommon.doc_router": fake_doc_router_module,
            "bfrcommon.middlewares.response": fake_response_module,
            "bfrcommon.middlewares.auth": fake_auth_module,
            "globals_vars": fake_logger_module,
            "csrcqsf.biz.segment": fake_segment_module,
            "csrcqsf.data.pg": fake_pg_module,
            "csrcqsf.data.minio": fake_minio_module,
            "csrcqsf.biz.sgo": fake_sgo_module,
            "csrcqsf.api_models": fake_api_models_module,
        },
    ):
        module = importlib.import_module("csrcqsf.app")

        async def _run():
            async with module.lifespan(module.app):
                return None

        asyncio.run(_run())

    fake_segment_module.SegmentBiz.init.assert_not_awaited()


def test_app_lifespan_skips_db_and_minio_init_when_env_not_explicitly_configured(monkeypatch):
    for key in (
        "MAIN_DB_HOST",
        "MAIN_DB_PORT",
        "MAIN_DB_USER",
        "MAIN_DB_PASSWORD",
        "MAIN_DB_DATABASE",
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "MILVUS_HOST",
        "MILVUS_PORT",
        "REDIS_HOST",
        "REDIS_PORT",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("ENABLE_SEGMENT_MODEL", "0")
    monkeypatch.setenv("ENABLE_OCR_MODEL", "0")

    _clear_module("csrcqsf.app")
    _clear_module("csrcqsf.runtime")

    fake_services_module = ModuleType("csrcqsf.services")
    fake_services_module.parts_router = APIRouter()
    fake_services_module.sgo_router = APIRouter()
    fake_services_module.parts_docs_router = APIRouter()
    fake_services_module.image_router = APIRouter()

    fake_response_module = ModuleType("bfrcommon.middlewares.response")
    fake_response_module.DefaultResponse = dict
    fake_response_module.catch_exceptions_middleware = lambda logger=None, limit=4: (
        lambda request, call_next: call_next(request)
    )

    fake_auth_module = ModuleType("bfrcommon.middlewares.auth")
    fake_auth_module.add_process_time_header = lambda logger=None: (
        lambda request, call_next: call_next(request)
    )

    fake_logger_module = ModuleType("globals_vars")
    fake_logger_module.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )

    fake_segment_module = ModuleType("csrcqsf.biz.segment")
    fake_segment_module.SegmentBiz = type("SegmentBiz", (), {"init": AsyncMock()})

    fake_pg_module = ModuleType("csrcqsf.data.pg")
    fake_pg_module.db_migrate = AsyncMock()

    fake_minio_module = ModuleType("csrcqsf.data.minio")
    fake_minio_module.create_minio_buckets = AsyncMock()

    fake_sgo_module = ModuleType("csrcqsf.biz.sgo")
    fake_sgo_module.SGOBiz = type("SGOBiz", (), {"init": staticmethod(lambda: None)})

    fake_api_models_module = ModuleType("csrcqsf.api_models")
    fake_api_models_module.SimpleSegmentReq = type(
        "SimpleSegmentReq",
        (BaseModel,),
        {"__annotations__": {"file_url": str}},
    )
    fake_api_models_module.SimpleSegmentRes = type(
        "SimpleSegmentRes",
        (BaseModel,),
        {"mask": ""},
    )

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.services": fake_services_module,
            "bfrcommon.middlewares.response": fake_response_module,
            "bfrcommon.middlewares.auth": fake_auth_module,
            "globals_vars": fake_logger_module,
            "csrcqsf.biz.segment": fake_segment_module,
            "csrcqsf.data.pg": fake_pg_module,
            "csrcqsf.data.minio": fake_minio_module,
            "csrcqsf.biz.sgo": fake_sgo_module,
            "csrcqsf.api_models": fake_api_models_module,
        },
    ):
        module = importlib.import_module("csrcqsf.app")

        async def _run():
            async with module.lifespan(module.app):
                return None

        asyncio.run(_run())

    fake_pg_module.db_migrate.assert_not_awaited()
    fake_minio_module.create_minio_buckets.assert_not_awaited()


def test_scheduler_skips_sync_when_main_db_or_redis_not_explicitly_configured(monkeypatch):
    for key in (
        "MAIN_DB_HOST",
        "MAIN_DB_PORT",
        "MAIN_DB_USER",
        "MAIN_DB_PASSWORD",
        "PG_HOST",
        "PG_PORT",
        "PG_USER",
        "PG_PASSWORD",
        "REDIS_HOST",
        "REDIS_PORT",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
    ):
        monkeypatch.delenv(key, raising=False)

    _clear_module("csrcqsf.scheduler")

    fake_settings_module = ModuleType("csrcqsf.settings")
    fake_settings_module.main_db_env_configured = lambda: False
    fake_settings_module.redis_env_configured = lambda: False

    with patch.dict(sys.modules, {"csrcqsf.settings": fake_settings_module}):
        scheduler_module = importlib.import_module("csrcqsf.scheduler")

    with patch("csrcqsf.scheduler.create_engine") as create_engine_mock, patch(
        "csrcqsf.scheduler.AsyncResult"
    ) as async_result_mock:
        scheduler_module.sync_reconstruction_tasks_sync()

    create_engine_mock.assert_not_called()
    async_result_mock.assert_not_called()
