import asyncio
import importlib
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

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

    fake_reconstruction_service_module = ModuleType("csrcqsf.modules.railway_parts.services.reconstruction_service")
    fake_reconstruction_service_module.ReconstructionManager = type("ReconstructionManager", (), {})

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.railway_parts.services.reconstruction_service": fake_reconstruction_service_module,
        },
    ):
        module = importlib.import_module("csrcqsf.modules.railway_parts.routes.reconstruction_routes")
        subset = ModuleType("test_reconstruction_routes_subset")
        subset.ReconstructionManager = module.ReconstructionManager
        subset.reconstruct_v2_train = module.reconstruct_v2_train
        return subset


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
