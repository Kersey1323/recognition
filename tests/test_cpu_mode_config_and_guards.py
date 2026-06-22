import asyncio
import importlib
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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


def _seed_routes_package() -> None:
    package = ModuleType("csrcqsf.modules.railway_parts.routes")
    package.__path__ = [str(Path("csrcqsf/modules/railway_parts/routes").resolve())]
    sys.modules["csrcqsf.modules.railway_parts.routes"] = package


def _build_api_model_module() -> ModuleType:
    module = ModuleType("csrcqsf.modules.railway_parts.schemas")
    flexible_model = type(
        "_FlexibleModel",
        (BaseModel,),
        {"Config": type("Config", (), {"extra": "allow"})},
    )

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
        setattr(module, name, type(name, (flexible_model,), {}))

    module.__all__ = names
    return module


def _build_reconstruction_api_model_module() -> ModuleType:
    module = ModuleType("csrcqsf.modules.railway_parts.schemas.reconstruction")
    flexible_model = type(
        "_FlexibleModel",
        (BaseModel,),
        {"Config": type("Config", (), {"extra": "allow"})},
    )
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
        "ReconstructionVideoUploadMinioHealthRes",
        "ReconstructionVideoUploadPartRes",
        "ReconstructionVideoUploadPartReq",
        "ReconstructionVideoUploadProgressReq",
        "ReconstructionVideoUploadProgressRes",
        "ReconstructionVideoUploadUrlsReq",
        "ReconstructionVideoUploadUrlsRes",
    ]
    for name in names:
        setattr(module, name, type(name, (flexible_model,), {}))

    module.__all__ = names
    return module


def _seed_fake_railway_parts_schema_modules() -> dict[str, ModuleType]:
    flexible_model = type(
        "_FlexibleModel",
        (BaseModel,),
        {"Config": type("Config", (), {"extra": "allow"})},
    )

    schema_package = ModuleType("csrcqsf.modules.railway_parts.schemas")
    schema_package.__path__ = []

    fake_parts = ModuleType("csrcqsf.modules.railway_parts.schemas.parts")
    fake_parts.V2IndexDeleteRes = type("V2IndexDeleteRes", (flexible_model,), {})

    fake_search = ModuleType("csrcqsf.modules.railway_parts.schemas.search")
    for name in [
        "SearchHistoryDeleteReq",
        "SearchHistoryDeleteRes",
        "SearchHistoryDetailReq",
        "SearchHistoryFeedbackReq",
        "SearchHistoryFeedbackRes",
        "SearchHistoryListItem",
        "SearchHistoryListReq",
        "SearchHistoryListRes",
        "SearchHistorySummaryRes",
        "SearchHistoryVerifyReq",
        "SearchHistoryVerifyRes",
        "SearchTextReq",
        "V2IndexDeleteRes",
    ]:
        setattr(fake_search, name, type(name, (flexible_model,), {}))

    fake_review_ticket = ModuleType("csrcqsf.modules.railway_parts.schemas.review_ticket")

    fake_reconstruction = ModuleType("csrcqsf.modules.railway_parts.schemas.reconstruction")
    for name in [
        "ReconstructionAllTasksReq",
        "ReconstructionAllTasksRes",
        "ReconstructionIndexRebuildRes",
        "ReconstructionListRes",
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
        "ReconstructionVideoUploadMinioHealthRes",
        "ReconstructionVideoUploadPartRes",
        "ReconstructionVideoUploadProgressReq",
        "ReconstructionVideoUploadProgressRes",
        "ReconstructionVideoUploadUrlsReq",
        "ReconstructionVideoUploadUrlsRes",
    ]:
        setattr(fake_reconstruction, name, type(name, (flexible_model,), {}))

    return {
        "csrcqsf.modules.railway_parts.schemas": schema_package,
        "csrcqsf.modules.railway_parts.schemas.parts": fake_parts,
        "csrcqsf.modules.railway_parts.schemas.search": fake_search,
        "csrcqsf.modules.railway_parts.schemas.review_ticket": fake_review_ticket,
        "csrcqsf.modules.railway_parts.schemas.reconstruction": fake_reconstruction,
    }


def _import_parts_service():
    _clear_module("csrcqsf.modules.railway_parts.routes")
    _clear_module("csrcqsf.core.runtime")
    _seed_routes_package()

    fake_api_models = _build_api_model_module()
    fake_reconstruction_api_models = _build_reconstruction_api_model_module()

    fake_parts_service_module = ModuleType("csrcqsf.modules.railway_parts.services.parts_service")
    fake_parts_service_module.RailwayPartsManager = type(
        "RailwayPartsManager",
        (),
        {
            "search_v2_by_text": staticmethod(AsyncMock(return_value={"message": "ok"})),
            "create_v2_collections": staticmethod(AsyncMock(return_value=None)),
            "rebuild_v2_index": staticmethod(AsyncMock(return_value={"success_count": 0, "fail_count": 0, "total": 0, "processed_item_count": 0, "skipped_existing_count": 0})),
            "delete_v2_index": staticmethod(AsyncMock(return_value={"message": "ok"})),
        },
    )

    fake_reconstruction_service_module = ModuleType("csrcqsf.modules.railway_parts.services.reconstruction_service")
    fake_reconstruction_service_module.ReconstructionManager = type(
        "ReconstructionManager",
        (),
        {
            "submit_train_task": staticmethod(
                AsyncMock(
                    return_value={
                        "task_id": "task-1",
                        "item_id": "1001",
                        "mode": "train",
                        "message": "训练任务已提交",
                    }
                )
            ),
        },
    )

    fake_state_manager_module = ModuleType("csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager")
    fake_state_manager_module.MilvusStateManagerV2 = type("MilvusStateManagerV2", (), {})

    fake_sgo_services_module = ModuleType("csrcqsf.modules.sgo.services")
    fake_sgo_services_module.SGOBiz = type(
        "SGOBiz",
        (),
        {"list_parts_sgo_image": staticmethod(lambda item_id: [])},
    )

    fake_schema_modules = _seed_fake_railway_parts_schema_modules()

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.railway_parts.schemas": fake_api_models,
            "csrcqsf.modules.railway_parts.schemas.reconstruction": fake_reconstruction_api_models,
            "csrcqsf.modules.railway_parts.services.parts_service": fake_parts_service_module,
            "csrcqsf.modules.railway_parts.services.reconstruction_service": fake_reconstruction_service_module,
            "csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager": fake_state_manager_module,
            "csrcqsf.modules.sgo.services": fake_sgo_services_module,
            **fake_schema_modules,
        },
    ):
        router_module = importlib.import_module("csrcqsf.modules.railway_parts.routes.router")
        search_routes_module = importlib.import_module("csrcqsf.modules.railway_parts.routes.search_routes")
        reconstruction_routes_module = importlib.import_module("csrcqsf.modules.railway_parts.routes.reconstruction_routes")
        module = ModuleType("test_parts_routes_subset")
        module.parts_router = router_module.parts_router
        module.ReconstructionManager = reconstruction_routes_module.ReconstructionManager
        module.search_v2_by_text = search_routes_module.search_v2_by_text
        module.reconstruct_v2_train = reconstruction_routes_module.reconstruct_v2_train
        return module


def _import_image_service():
    _clear_module("csrcqsf.modules.image")
    _clear_module("csrcqsf.core.runtime")

    fake_image_services_module = ModuleType("csrcqsf.modules.image.services")
    fake_image_services_module.SegmentBiz = type("SegmentBiz", (), {})

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.image.services": fake_image_services_module,
        },
    ):
        return importlib.import_module("csrcqsf.modules.image.routes")


def test_env_cpu_disables_gpu_and_model_capabilities():
    values = _parse_env_file(Path("docker/.env.cpu"))

    assert values["ENABLE_CPU_SAFE_MODE"] == "1"
    assert values["ENABLE_GPU_RECONSTRUCTION"] == "0"
    assert values["ENABLE_SEGMENT_MODEL"] == "0"
    assert values["ENABLE_VECTOR_MODELS"] == "0"
    assert values["ENABLE_OCR_MODEL"] == "0"
    assert values["SIGLIP_DEVICE"] == "cpu"
    assert values["DINOV2_DEVICE"] == "cpu"
    assert values["SAM3_DEVICE"] == "cpu"


def test_dockerfile_cpu_uses_cpu_base_and_no_cuda_install():
    text = Path("docker/Dockerfile.cpu").read_text(encoding="utf-8")

    assert "FROM python:3.10-slim" in text
    assert "nvidia/cuda" not in text
    assert "ARG PIP_INDEX_URL" in text
    assert "--no-install-package torch" not in text
    assert "--no-install-package torchvision" not in text
    assert "torch==2.7.1+cpu" not in text
    assert "torchvision==0.22.1+cpu" not in text


def test_run_docker_cpu_script_has_no_gpu_flag():
    text = Path("scripts/deployment/run_docker_cpu.sh").read_text(encoding="utf-8")

    assert "--gpus all" not in text
    assert "docker build" not in text
    assert "docker run -d" in text
    assert ".env.cpu" in text


def test_dockerfile_cpu_supports_configurable_mirrors():
    text = Path("docker/Dockerfile.cpu").read_text(encoding="utf-8")

    assert "ARG APT_MIRROR" in text
    assert "ARG PIP_INDEX_URL" in text
    assert "${PIP_INDEX_URL}" in text
    assert "uv sync --frozen --active --no-dev" in text


def test_run_docker_cpu_script_runs_prebuilt_image_with_host_mount():
    text = Path("scripts/deployment/run_docker_cpu.sh").read_text(encoding="utf-8")

    assert "HOST_MODEL_DIR" in text
    assert 'docker rm -f "${CONTAINER_NAME}"' in text
    assert '--env-file "${ENV_FILE}"' in text
    assert '-v "${HOST_MODEL_DIR}:/models"' in text


def test_parts_service_rejects_gpu_reconstruction_when_disabled(monkeypatch):
    parts_service = _import_parts_service()

    req = SimpleNamespace(item_id="1001", scene="demo", iterations=1000, output_name=None)

    with patch.dict(
        parts_service.reconstruct_v2_train.__globals__,
        {
            "ensure_gpu_reconstruction_enabled": MagicMock(
                side_effect=Exception("未配置重构服务，当前无法使用三维重构能力")
            )
        },
    ):
        try:
            asyncio.run(parts_service.reconstruct_v2_train(req))
        except Exception as exc:
            assert "未配置重构服务" in str(exc)
        else:
            raise AssertionError("expected GPU reconstruction route to be blocked")


def test_parts_service_allows_reconstruction_when_remote_service_configured(monkeypatch):
    parts_service = _import_parts_service()

    req = SimpleNamespace(item_id="1001", scene="demo", iterations=1000, output_name=None)

    with patch.dict(
        parts_service.reconstruct_v2_train.__globals__,
        {"ensure_gpu_reconstruction_enabled": MagicMock(return_value=None)},
    ):
        with patch.object(
            parts_service.ReconstructionManager,
            "submit_train_task",
            AsyncMock(
                return_value={
                    "task_id": "task-1",
                    "item_id": "1001",
                    "mode": "train",
                    "message": "训练任务已提交",
                }
            ),
            create=True,
        ):
            result = asyncio.run(parts_service.reconstruct_v2_train(req))

    assert result.task_id == "task-1"


def test_app_no_longer_warns_about_local_reconstruction_redis_dependency():
    text = Path("csrcqsf/core/app.py").read_text(encoding="utf-8")

    assert "重建状态同步任务将按需跳过" not in text
    assert "重构服务未配置时将禁用三维重构能力" in text


def test_cpu_env_template_mentions_reconstruction_server_url():
    text = Path("docker/.env.cpu").read_text(encoding="utf-8")

    assert "RECONSTRUCTION_SERVER_URL=" in text


def test_readme_mentions_dual_service_boundary():
    text = Path("README.md").read_text(encoding="utf-8")

    assert "RECONSTRUCTION_SERVER_URL" in text
    assert "reconstruction_server" in text


def test_reconstruction_server_env_configured_accepts_dotenv_loaded_url():
    from csrcqsf.core.settings import reconstruction_server_env_configured

    with patch("csrcqsf.core.settings._first_non_empty_env", return_value="http://gpu-service:8000"):
        assert reconstruction_server_env_configured() is True


def test_parts_service_rejects_vector_routes_when_cpu_safe_mode_enabled(monkeypatch):
    parts_service = _import_parts_service()

    req = SimpleNamespace(query_text="制动盘", top_k=5, search_equipment="web")

    with patch.dict(
        parts_service.search_v2_by_text.__globals__,
        {
            "ensure_vector_models_enabled": MagicMock(
                side_effect=Exception("当前为CPU联调模式，CPU模式下已禁用该接口")
            )
        },
    ):
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

    _clear_module("csrcqsf.core.app")
    _clear_module("csrcqsf.core.runtime")
    _clear_module("csrcqsf.core.scheduler")
    _clear_module("csrcqsf.infra.db.main_db")
    _clear_module("csrcqsf.infra.storage.minio")
    _clear_module("csrcqsf.modules.doc_parse")
    _clear_module("csrcqsf.modules.image")
    _clear_module("csrcqsf.modules.image.services")
    _clear_module("csrcqsf.modules.railway_parts.routes")
    _clear_module("csrcqsf.modules.sgo")
    _clear_module("csrcqsf.modules.sgo.services")

    fake_parts_routes_module = ModuleType("csrcqsf.modules.railway_parts.routes")
    fake_parts_routes_module.parts_router = APIRouter()
    fake_parts_routes_module.asset_proxy_router = APIRouter()
    fake_doc_parse_routes_module = ModuleType("csrcqsf.modules.doc_parse.routes")
    fake_doc_parse_routes_module.parts_docs_router = APIRouter()
    fake_image_routes_module = ModuleType("csrcqsf.modules.image.routes")
    fake_image_routes_module.image_router = APIRouter()
    fake_sgo_routes_module = ModuleType("csrcqsf.modules.sgo.routes")
    fake_sgo_routes_module.sgo_router = APIRouter()

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

    fake_image_services_module = ModuleType("csrcqsf.modules.image.services")
    fake_image_services_module.SegmentBiz = type("SegmentBiz", (), {"init": AsyncMock()})

    fake_pg_module = ModuleType("csrcqsf.infra.db.main_db")
    fake_pg_module.db_migrate = AsyncMock()

    fake_minio_module = ModuleType("csrcqsf.infra.storage.minio")
    fake_minio_module.create_minio_buckets = AsyncMock()

    fake_sgo_services_module = ModuleType("csrcqsf.modules.sgo.services")
    fake_sgo_services_module.SGOBiz = type("SGOBiz", (), {"init": staticmethod(lambda: None)})

    fake_scheduler_module = ModuleType("csrcqsf.core.scheduler")
    fake_scheduler_module.register_main_async_loop = MagicMock()

    fake_image_schemas_module = ModuleType("csrcqsf.modules.image.schemas")
    fake_image_schemas_module.SimpleSegmentReq = type(
        "SimpleSegmentReq",
        (BaseModel,),
        {"__annotations__": {"file_url": str}},
    )
    fake_image_schemas_module.SimpleSegmentRes = type(
        "SimpleSegmentRes",
        (BaseModel,),
        {"mask": ""},
    )

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.railway_parts.routes": fake_parts_routes_module,
            "csrcqsf.modules.doc_parse.routes": fake_doc_parse_routes_module,
            "csrcqsf.modules.image.routes": fake_image_routes_module,
            "csrcqsf.modules.sgo.routes": fake_sgo_routes_module,
            "bfrcommon.doc_router": fake_doc_router_module,
            "bfrcommon.middlewares.response": fake_response_module,
            "bfrcommon.middlewares.auth": fake_auth_module,
            "globals_vars": fake_logger_module,
            "csrcqsf.modules.image.services": fake_image_services_module,
            "csrcqsf.infra.db.main_db": fake_pg_module,
            "csrcqsf.infra.storage.minio": fake_minio_module,
            "csrcqsf.modules.sgo.services": fake_sgo_services_module,
            "csrcqsf.core.scheduler": fake_scheduler_module,
            "csrcqsf.modules.image.schemas": fake_image_schemas_module,
        },
    ):
        module = importlib.import_module("csrcqsf.core.app")

        async def _run():
            async with module.lifespan(module.app):
                return None

        asyncio.run(_run())

    fake_image_services_module.SegmentBiz.init.assert_not_awaited()
    fake_scheduler_module.register_main_async_loop.assert_called_once()


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

    _clear_module("csrcqsf.core.app")
    _clear_module("csrcqsf.core.runtime")
    _clear_module("csrcqsf.core.scheduler")
    _clear_module("csrcqsf.infra.db.main_db")
    _clear_module("csrcqsf.infra.storage.minio")
    _clear_module("csrcqsf.modules.doc_parse")
    _clear_module("csrcqsf.modules.image")
    _clear_module("csrcqsf.modules.image.services")
    _clear_module("csrcqsf.modules.railway_parts.routes")
    _clear_module("csrcqsf.modules.sgo")
    _clear_module("csrcqsf.modules.sgo.services")

    fake_parts_routes_module = ModuleType("csrcqsf.modules.railway_parts.routes")
    fake_parts_routes_module.parts_router = APIRouter()
    fake_parts_routes_module.asset_proxy_router = APIRouter()
    fake_doc_parse_routes_module = ModuleType("csrcqsf.modules.doc_parse.routes")
    fake_doc_parse_routes_module.parts_docs_router = APIRouter()
    fake_image_routes_module = ModuleType("csrcqsf.modules.image.routes")
    fake_image_routes_module.image_router = APIRouter()
    fake_sgo_routes_module = ModuleType("csrcqsf.modules.sgo.routes")
    fake_sgo_routes_module.sgo_router = APIRouter()

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

    fake_image_services_module = ModuleType("csrcqsf.modules.image.services")
    fake_image_services_module.SegmentBiz = type("SegmentBiz", (), {"init": AsyncMock()})

    fake_pg_module = ModuleType("csrcqsf.infra.db.main_db")
    fake_pg_module.db_migrate = AsyncMock()

    fake_minio_module = ModuleType("csrcqsf.infra.storage.minio")
    fake_minio_module.create_minio_buckets = AsyncMock()

    fake_sgo_services_module = ModuleType("csrcqsf.modules.sgo.services")
    fake_sgo_services_module.SGOBiz = type("SGOBiz", (), {"init": staticmethod(lambda: None)})

    fake_scheduler_module = ModuleType("csrcqsf.core.scheduler")
    fake_scheduler_module.register_main_async_loop = MagicMock()

    fake_image_schemas_module = ModuleType("csrcqsf.modules.image.schemas")
    fake_image_schemas_module.SimpleSegmentReq = type(
        "SimpleSegmentReq",
        (BaseModel,),
        {"__annotations__": {"file_url": str}},
    )
    fake_image_schemas_module.SimpleSegmentRes = type(
        "SimpleSegmentRes",
        (BaseModel,),
        {"mask": ""},
    )

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.railway_parts.routes": fake_parts_routes_module,
            "csrcqsf.modules.doc_parse.routes": fake_doc_parse_routes_module,
            "csrcqsf.modules.image.routes": fake_image_routes_module,
            "csrcqsf.modules.sgo.routes": fake_sgo_routes_module,
            "bfrcommon.middlewares.response": fake_response_module,
            "bfrcommon.middlewares.auth": fake_auth_module,
            "globals_vars": fake_logger_module,
            "csrcqsf.modules.image.services": fake_image_services_module,
            "csrcqsf.infra.db.main_db": fake_pg_module,
            "csrcqsf.infra.storage.minio": fake_minio_module,
            "csrcqsf.modules.sgo.services": fake_sgo_services_module,
            "csrcqsf.core.scheduler": fake_scheduler_module,
            "csrcqsf.modules.image.schemas": fake_image_schemas_module,
        },
    ):
        module = importlib.import_module("csrcqsf.core.app")

        async def _run():
            async with module.lifespan(module.app):
                return None

        asyncio.run(_run())

    fake_pg_module.db_migrate.assert_not_awaited()
    fake_minio_module.create_minio_buckets.assert_not_awaited()
    fake_scheduler_module.register_main_async_loop.assert_called_once()


def test_scheduler_skips_sync_when_main_db_or_remote_service_not_explicitly_configured(monkeypatch):
    for key in (
        "MAIN_DB_HOST",
        "MAIN_DB_PORT",
        "MAIN_DB_USER",
        "MAIN_DB_PASSWORD",
        "PG_HOST",
        "PG_PORT",
        "PG_USER",
        "PG_PASSWORD",
        "RECONSTRUCTION_SERVER_URL",
        "RECONSTRUCTION_SERVER_HOST",
        "RECONSTRUCTION_SERVER_PORT",
    ):
        monkeypatch.delenv(key, raising=False)

    _clear_module("csrcqsf.core.scheduler")

    fake_settings_module = ModuleType("csrcqsf.core.settings")
    fake_settings_module.main_db_env_configured = lambda: False
    fake_settings_module.reconstruction_server_env_configured = lambda: False

    with patch.dict(sys.modules, {"csrcqsf.core.settings": fake_settings_module}):
        scheduler_module = importlib.import_module("csrcqsf.core.scheduler")

    with patch("csrcqsf.core.scheduler.asyncio.run") as run_mock:
        scheduler_module.sync_reconstruction_tasks_sync()

    run_mock.assert_not_called()
