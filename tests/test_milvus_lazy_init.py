import importlib.util
import sys
import types
from enum import Enum
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(module_name: str, relative_path: str):
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_data_milvus_client_is_lazy(monkeypatch):
    calls = []

    fake_pymilvus = types.ModuleType("pymilvus")

    class FakeMilvusClient:
        def __init__(self, *, uri):
            calls.append(uri)
            self.uri = uri

    fake_pymilvus.MilvusClient = FakeMilvusClient
    monkeypatch.setitem(sys.modules, "pymilvus", fake_pymilvus)

    fake_settings = types.ModuleType("csrcqsf.settings")
    fake_settings.ai_settings = types.SimpleNamespace(milvus_url="http://milvus:19530")
    monkeypatch.setitem(sys.modules, "csrcqsf.settings", fake_settings)

    module = _load_module("tests_lazy_data_milvus", "csrcqsf/data/milvus.py")

    assert calls == []

    first = module.get_milvus_client()
    second = module.get_milvus_client()

    assert calls == ["http://milvus:19530"]
    assert first is second
    assert module.milvus_client.uri == "http://milvus:19530"


def test_railwayparts_milvus_defers_optional_model_loading(monkeypatch):
    model_loads = {"resnet": 0, "embedding": 0}

    for package_name in (
        "csrcqsf",
        "csrcqsf.biz",
        "csrcqsf.biz.railwayparts",
        "csrcqsf.data",
        "csrcqsf.models",
        "bfrcommon",
        "anyio",
        "sklearn",
    ):
        package = types.ModuleType(package_name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, package_name, package)

    fake_timm = types.ModuleType("timm")

    class FakeModel:
        default_cfg = {"input_size": (3, 224, 224)}

        def eval(self):
            return None

    def fake_create_model(*args, **kwargs):
        model_loads["resnet"] += 1
        return FakeModel()

    fake_timm.create_model = fake_create_model
    monkeypatch.setitem(sys.modules, "timm", fake_timm)

    fake_timm_data = types.ModuleType("timm.data")
    fake_timm_data.resolve_data_config = lambda *args, **kwargs: {}
    monkeypatch.setitem(sys.modules, "timm.data", fake_timm_data)

    fake_timm_transforms = types.ModuleType("timm.data.transforms_factory")
    fake_timm_transforms.create_transform = lambda **kwargs: (lambda image: image)
    monkeypatch.setitem(sys.modules, "timm.data.transforms_factory", fake_timm_transforms)

    monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))

    fake_anyio_to_thread = types.ModuleType("anyio.to_thread")
    fake_anyio_to_thread.run_sync = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    monkeypatch.setitem(sys.modules, "anyio.to_thread", fake_anyio_to_thread)

    fake_bfrcommon_common = types.ModuleType("bfrcommon.common")
    fake_bfrcommon_common.splite_list_by_n = lambda values, size: [values[i : i + size] for i in range(0, len(values), size)]
    monkeypatch.setitem(sys.modules, "bfrcommon.common", fake_bfrcommon_common)

    fake_bfrcommon_snowflake = types.ModuleType("bfrcommon.snowflake")
    fake_bfrcommon_snowflake.get_id = lambda: 1
    monkeypatch.setitem(sys.modules, "bfrcommon.snowflake", fake_bfrcommon_snowflake)

    fake_pil = types.ModuleType("PIL")
    fake_pil.Image = types.SimpleNamespace(fromarray=lambda image: image)
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)

    fake_pydantic = types.ModuleType("pydantic")

    class FakeBaseModel:
        pass

    fake_pydantic.BaseModel = FakeBaseModel
    monkeypatch.setitem(sys.modules, "pydantic", fake_pydantic)

    fake_pymilvus = types.ModuleType("pymilvus")
    fake_pymilvus.DataType = types.SimpleNamespace(INT64="INT64", FLOAT_VECTOR="FLOAT_VECTOR")
    fake_pymilvus.MilvusClient = object
    monkeypatch.setitem(sys.modules, "pymilvus", fake_pymilvus)

    fake_sklearn_preprocessing = types.ModuleType("sklearn.preprocessing")
    fake_sklearn_preprocessing.normalize = lambda value, norm=None: value
    monkeypatch.setitem(sys.modules, "sklearn.preprocessing", fake_sklearn_preprocessing)

    fake_data_milvus = types.ModuleType("csrcqsf.data.milvus")
    fake_data_milvus.milvus_client = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "csrcqsf.data.milvus", fake_data_milvus)

    fake_data_minio = types.ModuleType("csrcqsf.data.minio")
    fake_data_minio.minio_instance = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "csrcqsf.data.minio", fake_data_minio)

    fake_globals = types.ModuleType("globals_vars")
    fake_globals.logger = types.SimpleNamespace(info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "globals_vars", fake_globals)

    fake_models_item = types.ModuleType("csrcqsf.models.item")
    fake_models_item.Enum = Enum
    monkeypatch.setitem(sys.modules, "csrcqsf.models.item", fake_models_item)

    fake_models_sgo = types.ModuleType("csrcqsf.models.sgo")
    fake_models_sgo.SgoItemImages = object
    monkeypatch.setitem(sys.modules, "csrcqsf.models.sgo", fake_models_sgo)

    fake_settings = types.ModuleType("csrcqsf.settings")
    fake_settings.resolve_model_path = lambda path: path if path.startswith("/") else f"/models/{path}"
    monkeypatch.setitem(sys.modules, "csrcqsf.settings", fake_settings)

    fake_api_models = types.ModuleType("csrcqsf.biz.railwayparts.api_models")
    monkeypatch.setitem(sys.modules, "csrcqsf.biz.railwayparts.api_models", fake_api_models)

    module = _load_module(
        "csrcqsf.biz.railwayparts.milvus_lazy_test",
        "csrcqsf/biz/railwayparts/milvus.py",
    )

    assert model_loads == {"resnet": 0, "embedding": 0}
    assert getattr(module.MilvusManager, "_hp_extractor") is None
