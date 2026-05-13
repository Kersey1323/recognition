import importlib
import sys
from pathlib import Path


def _reload_settings(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("csrcqsf.settings", None)
    return importlib.import_module("csrcqsf.settings")


def _parse_env_file(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def test_main_get_app_port_reads_env(monkeypatch):
    monkeypatch.setenv("APP_PORT", "7001")
    sys.modules.pop("main", None)
    main = importlib.import_module("main")

    assert main.get_app_port() == 7001


def test_settings_apply_runtime_env_overrides(monkeypatch):
    settings = _reload_settings(
        monkeypatch,
        PG_HOST="10.0.0.8",
        PG_PORT="5433",
        PG_USER="docker_user",
        PG_PASSWORD="docker_password",
        PG_DATABASE="partsdb",
        MILVUS_HOST="10.0.0.10",
        MILVUS_PORT="29530",
        MINIO_ENDPOINT="10.0.0.11:9000",
        SGO_MYSQL_HOST="10.0.0.12",
        SGO_MYSQL_PORT="3307",
        SGO_MYSQL_USER="sgo_user",
        SGO_MYSQL_PASSWORD="sgo_password",
        SGO_MYSQL_DATABASE="sgo_db",
    )

    assert settings.ai_settings.get_async_pg_dsn() == (
        "postgresql+asyncpg://docker_user:docker_password@10.0.0.8:5433/partsdb"
    )
    assert settings.ai_settings.milvus_url == "http://10.0.0.10:29530"
    assert settings.ai_settings.minio_url == "10.0.0.11:9000"
    assert settings.ai_settings.get_sgo_dsn() == (
        "mysql+asyncmy://sgo_user:sgo_password@10.0.0.12:3307/sgo_db"
    )


def test_env_deployment_uses_container_runtime_paths():
    values = _parse_env_file(Path(".env.deployment"))

    assert values["MODEL_DIR"] == "/models"
    assert values["TEMP_DIR"] == "/app/temp"
    assert values["DINOV2_PATCH_TOKENS_DIR"] == "/app/state/vector_db/patch_tokens"
    assert values["INDEXING_CHECKPOINT_FILE"] == "/app/state/vector_db/checkpoint.json"
