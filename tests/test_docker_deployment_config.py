import importlib
import sys
from pathlib import Path


def _reload_settings(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("csrcqsf.core.settings", None)
    return importlib.import_module("csrcqsf.core.settings")


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
        MAIN_DB_HOST="10.0.0.8",
        MAIN_DB_PORT="3307",
        MAIN_DB_USER="docker_user",
        MAIN_DB_PASSWORD="docker_password",
        MAIN_DB_DATABASE="coronavirusdb",
        MILVUS_HOST="10.0.0.10",
        MILVUS_PORT="29530",
        MINIO_ENDPOINT="10.0.0.11:9000",
        SGO_DATABASE_TYPE="mysql",
        SGO_MYSQL_HOST="10.0.0.12",
        SGO_MYSQL_PORT="3307",
        SGO_MYSQL_USER="sgo_user",
        SGO_MYSQL_PASSWORD="sgo_password",
        SGO_MYSQL_DATABASE="sgo_db",
    )

    assert settings.ai_settings.get_async_main_db_dsn() == (
        "mysql+asyncmy://docker_user:docker_password@10.0.0.8:3307/coronavirusdb"
    )
    assert settings.ai_settings.milvus_url == "http://10.0.0.10:29530"
    assert settings.minio_endpoint == "10.0.0.11:9000"
    assert settings.ai_settings.get_sgo_dsn() == (
        "mysql+asyncmy://sgo_user:sgo_password@10.0.0.12:3307/sgo_db"
    )


def test_settings_does_not_expose_removed_legacy_fields(monkeypatch):
    settings = _reload_settings(
        monkeypatch,
        MAIN_DB_HOST="10.0.0.8",
        MAIN_DB_PORT="3307",
        MAIN_DB_USER="docker_user",
        MAIN_DB_PASSWORD="docker_password",
        MAIN_DB_DATABASE="coronavirusdb",
    )

    assert not hasattr(settings.ai_settings, "deepseek_url")
    assert not hasattr(settings.ai_settings, "api_key")
    assert not hasattr(settings.ai_settings, "neo4j_url")
    assert not hasattr(settings.ai_settings, "neo4j_outer_url")
    assert not hasattr(settings.ai_settings, "llm_model_name")
    assert not hasattr(settings.ai_settings, "embeddings_model_name")
    assert not hasattr(settings.ai_settings, "search_use_vechile")


def test_env_deployment_uses_host_network_runtime_paths():
    values = _parse_env_file(Path(".env.deployment"))

    assert "MODEL_DIR" not in values
    assert "SAM3_MODEL_PATH" not in values
    assert "SAM_MODEL_PATH" not in values
    assert values["TEMP_DIR"] == "temp"
    assert values["MINIO_SEARCH_HISTORY_BUCKET"] == "bfr-search-history-files"
    assert values["DINOV2_PATCH_TOKENS_DIR"] == "state/vector_db/patch_tokens"
    assert values["INDEXING_CHECKPOINT_FILE"] == "state/vector_db/checkpoint.json"


def test_env_deployment_exposes_main_mysql_vars():
    values = _parse_env_file(Path(".env.deployment"))

    assert values["MAIN_DB_HOST"] == "192.168.100.2"
    assert values["MAIN_DB_PORT"] == "3307"
    assert values["MAIN_DB_DATABASE"] == "coronavirusdb"


def test_env_templates_expose_switchable_sgo_database_backends():
    for path in (Path(".env.example"), Path(".env.deployment")):
        values = _parse_env_file(path)
        assert values["SGO_DATABASE_TYPE"] == "mysql"
        assert values["SGO_MYSQL_DATABASE"] == "mdpdb"
        assert values["SGO_KINGBASE_PORT"] == "54321"
        assert values["SGO_KINGBASE_DATABASE"] == "mdpdb"


def test_root_dockerfile_declares_runtime_contract():
    text = Path("Dockerfile").read_text(encoding="utf-8")

    assert "EXPOSE 65432" in text
    assert 'VOLUME ["/app/logs", "/app/temp", "/app/state"]' in text
    assert "http://127.0.0.1:65432/health" in text


def test_vendor_dockerfile_matches_release_runtime_contract():
    text = Path("Dockerfile.vendor").read_text(encoding="utf-8")

    assert "EXPOSE 65432" in text
    assert 'VOLUME ["/app/logs", "/app/temp", "/app/state"]' in text
    assert "http://127.0.0.1:65432/health" in text


def test_run_docker_deployment_script_uses_cpu_business_defaults():
    text = Path("scripts/deployment/run_docker_deployment.sh").read_text(encoding="utf-8")

    assert 'IMAGE_NAME="${IMAGE_NAME:-recognition:latest}"' in text
    assert 'CONTAINER_NAME="${CONTAINER_NAME:-recognition-service}"' in text
    assert 'ENV_FILE="${ENV_FILE:-.env.deployment}"' in text
    assert "--gpus all" not in text
    assert "HOST_MODEL_DIR" not in text
    assert ':/models"' not in text


def test_env_templates_do_not_expose_removed_legacy_vars():
    for path in (Path(".env.example"), Path(".env.deployment")):
        values = _parse_env_file(path)
        assert "MODEL_DIR" not in values
        assert "SAM3_MODEL_PATH" not in values
        assert "SAM_MODEL_PATH" not in values
        assert "PG_HOST" not in values
        assert "PG_PORT" not in values
        assert "PG_DATABASE" not in values
        assert "PG_USER" not in values
        assert "PG_PASSWORD" not in values
        assert "MILVUS_URL" not in values
        assert "SGO_MYSQL_URL" not in values
        assert "SGO_MYSQL_USERNAME" not in values
        assert "RECONSTRUCTION_SERVER_HOST" not in values
        assert "RECONSTRUCTION_SERVER_PORT" not in values
        assert "REDIS_HOST" not in values
        assert "REDIS_PORT" not in values
        assert "CELERY_BROKER_URL" not in values
        assert "CELERY_RESULT_BACKEND" not in values
        assert "CELERY_TASK_TIME_LIMIT" not in values
        assert "CELERY_TASK_SOFT_TIME_LIMIT" not in values


def test_asset_proxy_auth_switch_has_safe_template_default():
    example_values = _parse_env_file(Path(".env.example"))
    deployment_values = _parse_env_file(Path(".env.deployment"))

    assert example_values["ASSET_PROXY_SKIP_AUTH"] == "false"
    assert deployment_values["ASSET_PROXY_SKIP_AUTH"] == "true"


def test_vector_env_config_no_longer_reads_pg_or_model_dir_contract():
    text = Path(
        "csrcqsf/modules/railway_parts/vector_search/config/env_config.py"
    ).read_text(encoding="utf-8")

    assert 'os.getenv("PG_HOST"' not in text
    assert 'os.getenv("PG_PORT"' not in text
    assert "get_pg_dsn" not in text
    assert "get_async_pg_dsn" not in text


def test_settings_and_app_no_longer_keep_redis_runtime_contract():
    settings_text = Path("csrcqsf/core/settings.py").read_text(encoding="utf-8")
    app_text = Path("csrcqsf/core/app.py").read_text(encoding="utf-8")

    assert "def redis_env_configured" not in settings_text
    assert '"CELERY_BROKER_URL"' not in settings_text
    assert '"CELERY_RESULT_BACKEND"' not in settings_text
    assert '"REDIS_HOST"' not in settings_text
    assert '"REDIS_PORT"' not in settings_text
    assert "redis_env_configured" not in app_text
