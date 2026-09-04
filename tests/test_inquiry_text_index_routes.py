import importlib
import sys
from pathlib import Path
from types import ModuleType

from fastapi import FastAPI


def test_inquiry_text_index_routes_are_registered_with_documented_contract():
    prefix = "csrcqsf.modules.railway_parts.routes"
    for name in list(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            sys.modules.pop(name, None)
    package = ModuleType(prefix)
    package.__path__ = [str(Path("csrcqsf/modules/railway_parts/routes").resolve())]
    sys.modules[prefix] = package
    router_module = importlib.import_module(f"{prefix}.router")
    importlib.import_module(f"{prefix}.inquiry_text_index_routes")
    app = FastAPI()
    app.include_router(router_module.parts_router)

    schema = app.openapi()
    paths = schema["paths"]
    expected = {
        "/railway/parts/v2/inquiry-text-index/rebuild",
        "/railway/parts/v2/inquiry-text-index/tasks/list",
        "/railway/parts/v2/inquiry-text-index/tasks/{task_id}",
        "/railway/parts/v2/inquiry-text-index/tasks/{task_id}/cancel",
        "/railway/parts/v2/inquiry-text-index/tasks/{task_id}/retry",
        "/railway/parts/v2/inquiry-text-index/tasks/{task_id}/failures/list",
    }
    assert expected.issubset(paths)

    definitions = schema.get("definitions", schema.get("components", {}).get("schemas", {}))
    list_req = definitions["InquiryTextIndexTaskListReq"]
    assert set(list_req["properties"]["status"]["enum"]) == {
        "all",
        "active",
        "pending",
        "running",
        "cancelling",
        "success",
        "failed",
        "cancelled",
        "interrupted",
    }
    assert set(list_req["properties"]["task_scope"]["enum"]) == {
        "all",
        "incremental",
        "full",
    }
    task_status = definitions["InquiryTextIndexTaskStatusRes"]
    assert set(task_status["properties"]["trigger_source"]["enum"]) == {
        "sgo_inquiry_sync",
        "manual",
    }
    assert task_status["properties"]["source_sync_task_ids"]["type"] == "array"
