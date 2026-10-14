from dataclasses import dataclass
from urllib.parse import quote_plus
import os

from bfrcommon.settings import Settings

from csrcqsf.core.environment import load_explicit_env_file
from csrcqsf.core.runtime_paths import get_runtime_paths

# 记录进程启动时真实注入的变量，避免镜像默认值被误判为甲方已完成部署配置。
_EXPLICIT_ENV_KEYS = frozenset(os.environ.keys())

# 本地环境文件必须显式指定；生产环境始终以进程环境变量为准。
load_explicit_env_file()
runtime_paths = get_runtime_paths(refresh=True)


def _first_non_empty_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip() != "":
            return value.strip()
    return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bounded_env_int(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    raw_value = os.getenv(name)
    value = default if raw_value is None else int(raw_value.strip())
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


@dataclass(frozen=True)
class AuthSettings:
    """Recognition 全局访问鉴权配置。"""

    app_env: str
    enabled: bool
    provider: str
    mock_token: str
    docs_public: bool
    allowed_origins: tuple[str, ...]
    sgo_auth_url: str
    sgo_service: str
    sgo_mode: str
    sgo_timeout_seconds: float
    redis_url: str
    token_cache_ttl_seconds: int
    invalid_token_cache_ttl_seconds: int


def _comma_separated_env(name: str, *, default: str = "") -> tuple[str, ...]:
    raw_value = os.getenv(name, default)
    return tuple(value.strip() for value in raw_value.split(",") if value.strip())


def load_auth_settings() -> AuthSettings:
    """读取鉴权配置，并阻止生产环境以免鉴权或 Mock 模式启动。"""
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    provider = os.getenv("AUTH_PROVIDER", "sgo").strip().lower()
    enabled = _env_bool("AUTH_ENABLED", False)
    docs_public = _env_bool("AUTH_DOCS_PUBLIC", app_env == "development")
    allowed_origins = _comma_separated_env(
        "AUTH_ALLOWED_ORIGINS",
        default="*" if app_env == "development" else "",
    )

    if app_env not in {"development", "production"}:
        raise ValueError("APP_ENV 仅支持 development 或 production")
    if provider not in {"sgo", "mock"}:
        raise ValueError("AUTH_PROVIDER 仅支持 sgo 或 mock")

    settings = AuthSettings(
        app_env=app_env,
        enabled=enabled,
        provider=provider,
        mock_token=os.getenv("AUTH_MOCK_TOKEN", "").strip(),
        docs_public=docs_public,
        allowed_origins=allowed_origins,
        sgo_auth_url=os.getenv("SGO_SSO_AUTH_URL", "").strip(),
        sgo_service=os.getenv("SGO_SSO_SERVICE", "sgo").strip() or "sgo",
        sgo_mode=os.getenv("SGO_SSO_MODE", "").strip(),
        sgo_timeout_seconds=float(os.getenv("SGO_SSO_TIMEOUT_SECONDS", "5")),
        redis_url=os.getenv("AUTH_REDIS_URL", "").strip(),
        token_cache_ttl_seconds=_bounded_env_int(
            "AUTH_TOKEN_CACHE_TTL_SECONDS",
            default=300,
            minimum=1,
        ),
        invalid_token_cache_ttl_seconds=_bounded_env_int(
            "AUTH_INVALID_TOKEN_CACHE_TTL_SECONDS",
            default=10,
            minimum=1,
        ),
    )

    if app_env == "production":
        if not enabled:
            raise ValueError("AUTH_ENABLED must be true in production")
        if provider != "sgo":
            raise ValueError("AUTH_PROVIDER must be sgo in production")
        if docs_public:
            raise ValueError("AUTH_DOCS_PUBLIC must be false in production")
        if not allowed_origins or "*" in allowed_origins:
            raise ValueError("AUTH_ALLOWED_ORIGINS must list explicit production origins")
        if not settings.redis_url:
            raise ValueError("AUTH_REDIS_URL must be configured in production")
        if not settings.sgo_auth_url:
            raise ValueError("SGO_SSO_AUTH_URL must be configured in production")
    if enabled and provider == "mock" and not settings.mock_token:
        raise ValueError("AUTH_MOCK_TOKEN must be configured for mock authentication")
    if enabled and provider == "sgo" and not settings.sgo_auth_url:
        raise ValueError("SGO_SSO_AUTH_URL must be configured for SGO authentication")
    return settings


def env_is_explicit(name: str) -> bool:
    value = os.getenv(name)
    return name in _EXPLICIT_ENV_KEYS and value is not None and value.strip() != ""


def _all_explicit_env(*names: str) -> bool:
    return all(env_is_explicit(name) for name in names)


def _build_service_url(
    explicit_url: str,
    host: str,
    port: str,
    default_url: str,
    scheme: str = "http",
) -> str:
    """优先使用完整地址，否则由主机和端口拼出外部服务地址。"""
    if explicit_url.strip() != "":
        return explicit_url.strip()
    if host.strip() == "":
        return default_url
    if port.strip() == "":
        return f"{scheme}://{host.strip()}"
    return f"{scheme}://{host.strip()}:{port.strip()}"


def _first_explicit_then_non_empty_env(*names: str, default: str = "") -> str:
    # 部署环境显式值优先于 Settings 内置值，兼容旧变量名时仍保持唯一取值顺序。
    for name in names:
        if env_is_explicit(name):
            return os.getenv(name, "").strip()
    return _first_non_empty_env(*names, default=default)


def main_db_env_configured() -> bool:
    return _all_explicit_env(
        "MAIN_DB_HOST",
        "MAIN_DB_PORT",
        "MAIN_DB_USER",
        "MAIN_DB_PASSWORD",
        "MAIN_DB_DATABASE",
    )


def minio_env_configured() -> bool:
    return _all_explicit_env(
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
    )


def milvus_env_configured() -> bool:
    return _all_explicit_env(
        "MILVUS_HOST",
        "MILVUS_PORT",
    )


def reconstruction_server_env_configured() -> bool:
    return env_is_explicit("RECONSTRUCTION_SERVER_URL")


def sgo_env_configured() -> bool:
    # 只校验当前启用的 SGO 数据源，未启用数据库的配置不应阻塞服务启动。
    prefix = "SGO_KINGBASE" if sgo_database_type == "kingbase" else "SGO_MYSQL"
    return _all_explicit_env(
        f"{prefix}_HOST",
        f"{prefix}_PORT",
        f"{prefix}_USER",
        f"{prefix}_PASSWORD",
        f"{prefix}_DATABASE",
    )


minio_bucket = os.getenv("MINIO_BUCKET", "bfr-ai-files")
minio_reconstruction_video_bucket = os.getenv(
    "MINIO_RECONSTRUCTION_VIDEO_BUCKET",
    "bfr-3d-videos",
)
minio_reconstruction_file_bucket = os.getenv(
    "MINIO_RECONSTRUCTION_FILE_BUCKET",
    "bfr-reconstruction-files",
)
minio_search_history_bucket = os.getenv(
    "MINIO_SEARCH_HISTORY_BUCKET",
    "bfr-search-history-files",
)
minio_endpoint = os.getenv("MINIO_ENDPOINT", "192.168.100.2:9000")
minio_access_key = os.getenv("MINIO_ACCESS_KEY", "root")
minio_secret_key = os.getenv("MINIO_SECRET_KEY", "REMOVED_CREDENTIAL")
minio_secure = _env_bool("MINIO_SECURE", False)
agent_running = _env_bool("AGENT_RUNING", False)
temp_dir = str(runtime_paths.temp_dir)
main_db_database = _first_non_empty_env(
    "MAIN_DB_DATABASE",
    default="coronavirusdb",
)
sgo_mysql_database = _first_explicit_then_non_empty_env(
    "SGO_MYSQL_DATABASE",
    default="mdpdb",
)
sgo_kingbase_database = _first_explicit_then_non_empty_env(
    "SGO_KINGBASE_DATABASE",
    default="mdpdb",
)
sgo_database_type = _first_explicit_then_non_empty_env(
    "SGO_DATABASE_TYPE",
    default="mysql",
).lower()
if sgo_database_type not in {"mysql", "kingbase"}:
    raise ValueError(
        "SGO_DATABASE_TYPE 仅支持 mysql 或 kingbase，"
        f"当前值: {sgo_database_type}"
    )
sgo_database_name = (
    sgo_kingbase_database if sgo_database_type == "kingbase" else sgo_mysql_database
)


class AISettings(Settings):
    milvus_url: str = "http://192.168.100.12:19530"
    sgo_mysql_url: str = ""
    sgo_mysql_port: str = ""
    sgo_mysql_password: str = ""
    sgo_mysql_username: str = ""
    sgo_kingbase_url: str = ""
    sgo_kingbase_port: str = ""
    sgo_kingbase_password: str = ""
    sgo_kingbase_username: str = ""
    basis_api_grpc_url: str = "10.144.145.6:8701"

    @property
    def mysql(self):
        return self.pg

    def get_mysql_dsn(self):
        return (
            f"mysql+pymysql://{self.mysql.user_name}:{quote_plus(self.mysql.password)}"
            f"@{self.mysql.url}:{self.mysql.port}/{main_db_database}"
        )

    def get_async_mysql_dsn(self):
        return (
            f"mysql+asyncmy://{self.mysql.user_name}:{quote_plus(self.mysql.password)}"
            f"@{self.mysql.url}:{self.mysql.port}/{main_db_database}"
        )

    def get_main_db_dsn(self):
        return self.get_mysql_dsn()

    def get_async_main_db_dsn(self):
        return self.get_async_mysql_dsn()

    def get_pg_dsn(self):
        return self.get_mysql_dsn()

    def get_async_pg_dsn(self):
        return self.get_async_mysql_dsn()

    def get_sgo_dsn(self):
        # Kingbase 使用项目注册的 SQLAlchemy 方言，MySQL 沿用 asyncmy 异步驱动。
        if sgo_database_type == "kingbase":
            return (
                "kingbase+asyncpg://"
                f"{self.sgo_kingbase_username}:{quote_plus(self.sgo_kingbase_password)}"
                f"@{self.sgo_kingbase_url}:{self.sgo_kingbase_port}/"
                f"{sgo_kingbase_database}"
            )
        return (
            f"mysql+asyncmy://{self.sgo_mysql_username}:{quote_plus(self.sgo_mysql_password)}"
            f"@{self.sgo_mysql_url}:{self.sgo_mysql_port}/{sgo_mysql_database}"
        )

    @property
    def sgo_host(self) -> str:
        if sgo_database_type == "kingbase":
            return self.sgo_kingbase_url
        return self.sgo_mysql_url

    @property
    def sgo_port(self) -> str:
        if sgo_database_type == "kingbase":
            return self.sgo_kingbase_port
        return self.sgo_mysql_port


def _apply_runtime_connection_overrides(settings: AISettings) -> None:
    """将部署环境连接信息覆盖到公共 Settings 对象，供旧代码继续统一取值。"""
    settings.mysql.url = _first_non_empty_env(
        "MAIN_DB_HOST",
        default=settings.mysql.url,
    )
    settings.mysql.port = _first_non_empty_env(
        "MAIN_DB_PORT",
        default=settings.mysql.port,
    )
    settings.mysql.user_name = _first_non_empty_env(
        "MAIN_DB_USER",
        default=settings.mysql.user_name,
    )
    settings.mysql.password = _first_non_empty_env(
        "MAIN_DB_PASSWORD",
        default=settings.mysql.password,
    )
    settings.milvus_url = _build_service_url(
        explicit_url="",
        host=_first_non_empty_env("MILVUS_HOST"),
        port=_first_non_empty_env("MILVUS_PORT"),
        default_url=settings.milvus_url,
    )
    settings.sgo_mysql_url = _first_non_empty_env(
        "SGO_MYSQL_HOST",
        default=settings.sgo_mysql_url,
    )
    settings.sgo_mysql_port = _first_non_empty_env(
        "SGO_MYSQL_PORT",
        default=settings.sgo_mysql_port,
    )
    settings.sgo_mysql_username = _first_non_empty_env(
        "SGO_MYSQL_USER",
        default=settings.sgo_mysql_username,
    )
    settings.sgo_mysql_password = _first_non_empty_env(
        "SGO_MYSQL_PASSWORD",
        default=settings.sgo_mysql_password,
    )
    settings.sgo_kingbase_url = _first_non_empty_env(
        "SGO_KINGBASE_HOST",
        default=settings.sgo_kingbase_url,
    )
    settings.sgo_kingbase_port = _first_non_empty_env(
        "SGO_KINGBASE_PORT",
        default=settings.sgo_kingbase_port,
    )
    settings.sgo_kingbase_username = _first_non_empty_env(
        "SGO_KINGBASE_USER",
        default=settings.sgo_kingbase_username,
    )
    settings.sgo_kingbase_password = _first_non_empty_env(
        "SGO_KINGBASE_PASSWORD",
        default=settings.sgo_kingbase_password,
    )
    settings.basis_api_grpc_url = _first_non_empty_env(
        "BASIS_API_GRPC_URL",
        default=settings.basis_api_grpc_url,
    )


ai_settings = AISettings()
_apply_runtime_connection_overrides(ai_settings)

model_service_url = os.getenv("MODEL_SERVICE_URL", "http://localhost:5555")
model_service_index_timeout_sec = int(
    os.getenv("MODEL_SERVICE_INDEX_TIMEOUT_SEC", "120")
)
index_single_task_max_concurrency = max(
    1,
    int(os.getenv("INDEX_SINGLE_TASK_MAX_CONCURRENCY", "16")),
)
index_auto_scan_interval_seconds = max(
    1,
    int(os.getenv("INDEX_AUTO_SCAN_INTERVAL_SECONDS", "30")),
)
reconstruction_server_url = _first_non_empty_env(
    "RECONSTRUCTION_SERVER_URL",
    default="http://127.0.0.1:8000",
)
reconstruction_server_timeout_sec = float(
    _first_non_empty_env("RECONSTRUCTION_SERVER_TIMEOUT_SEC", default="10")
)
reconstruction_server_download_timeout_sec = float(
    _first_non_empty_env(
        "RECONSTRUCTION_SERVER_DOWNLOAD_TIMEOUT_SEC",
        default="300",
    )
)
sgo_parts_sync_interval_minutes = _bounded_env_int(
    "SGO_PARTS_SYNC_INTERVAL_MINUTES", default=100, minimum=1, maximum=10080
)
sgo_inquiry_history_sync_interval_minutes = _bounded_env_int(
    "SGO_INQUIRY_HISTORY_SYNC_INTERVAL_MINUTES", default=100, minimum=1, maximum=10080
)
sgo_image_item_batch_size = _bounded_env_int(
    "SGO_IMAGE_ITEM_BATCH_SIZE", default=300, minimum=1, maximum=5000
)
sgo_image_zip_batch_size = _bounded_env_int(
    "SGO_IMAGE_ZIP_BATCH_SIZE", default=1, minimum=1, maximum=200
)
sgo_image_upload_concurrency = _bounded_env_int(
    "SGO_IMAGE_UPLOAD_CONCURRENCY", default=4, minimum=1, maximum=32
)
sgo_image_download_concurrency = _bounded_env_int(
    "SGO_IMAGE_DOWNLOAD_CONCURRENCY", default=4, minimum=1, maximum=16
)
sgo_image_download_timeout_seconds = _bounded_env_int(
    "SGO_IMAGE_DOWNLOAD_TIMEOUT_SECONDS", default=120, minimum=1, maximum=1800
)
sgo_image_download_retries = _bounded_env_int(
    "SGO_IMAGE_DOWNLOAD_RETRIES", default=3, minimum=1, maximum=10
)
sgo_image_zip_max_bytes = _bounded_env_int(
    "SGO_IMAGE_ZIP_MAX_BYTES",
    default=256 * 1024 * 1024,
    minimum=1024 * 1024,
)

# 询码记录提交后仅将本次新增样本送入 BGE 增量任务；关闭时保留人工全量重建能力。
inquiry_text_auto_index_enabled = _env_bool(
    "INQUIRY_TEXT_AUTO_INDEX_ENABLED",
    True,
)

# Viewer360 使用固定采集节拍；部署环境可显式覆盖，但行数与方向必须一一对应。
viewer360_enabled = _env_bool("VIEWER360_ENABLED", True)
viewer360_auto_create_after_video_upload = _env_bool(
    "VIEWER360_AUTO_CREATE_AFTER_VIDEO_UPLOAD", False
)
viewer360_max_concurrent_tasks = max(
    1, int(os.getenv("VIEWER360_MAX_CONCURRENT_TASKS", "1"))
)
viewer360_work_dir = os.getenv("VIEWER360_WORK_DIR", "/data/viewer360-tasks")
viewer360_work_retention_days = max(
    1, int(os.getenv("VIEWER360_WORK_RETENTION_DAYS", "7"))
)
viewer360_task_timeout_seconds = max(
    1, int(os.getenv("VIEWER360_TASK_TIMEOUT_SECONDS", "1800"))
)
viewer360_ffmpeg_threads = max(1, int(os.getenv("VIEWER360_FFMPEG_THREADS", "4")))
viewer360_row_count = max(2, int(os.getenv("VIEWER360_ROW_COUNT", "4")))
viewer360_row_directions = tuple(
    int(value.strip())
    for value in os.getenv("VIEWER360_ROW_DIRECTIONS", "1,-1,1,-1").split(",")
)
if (
    len(viewer360_row_directions) != viewer360_row_count
    or any(value not in {-1, 1} for value in viewer360_row_directions)
):
    raise ValueError("VIEWER360_ROW_DIRECTIONS must contain one -1/1 value per row")
viewer360_transition_seconds = float(os.getenv("VIEWER360_TRANSITION_SECONDS", "2"))
viewer360_frames_per_row = max(1, int(os.getenv("VIEWER360_FRAMES_PER_ROW", "72")))
viewer360_image_size = max(1, int(os.getenv("VIEWER360_IMAGE_SIZE", "1600")))
viewer360_webp_quality = int(os.getenv("VIEWER360_WEBP_QUALITY", "90"))
viewer360_center_p95_ratio = float(os.getenv("VIEWER360_CENTER_P95_RATIO", "0.015"))
viewer360_model_timeout_seconds = max(
    1, int(os.getenv("VIEWER360_MODEL_TIMEOUT_SECONDS", "600"))
)
