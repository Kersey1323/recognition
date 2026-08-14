from urllib.parse import quote_plus
import os

from bfrcommon.settings import Settings
from dotenv import load_dotenv

_EXPLICIT_ENV_KEYS = frozenset(os.environ.keys())

# 加载环境变量文件，但“是否显式配置”只认进程启动前已给出的环境变量
load_dotenv()


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
    if explicit_url.strip() != "":
        return explicit_url.strip()
    if host.strip() == "":
        return default_url
    if port.strip() == "":
        return f"{scheme}://{host.strip()}"
    return f"{scheme}://{host.strip()}:{port.strip()}"


def _first_explicit_then_non_empty_env(*names: str, default: str = "") -> str:
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
temp_dir = os.getenv(
    "TEMP_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "temp"),
)
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

basis_api_http_url = _first_non_empty_env("BASIS_API_HTTP_URL", default="")
model_service_url = os.getenv("MODEL_SERVICE_URL", "http://localhost:5555")
reconstruction_server_url = _first_non_empty_env(
    "RECONSTRUCTION_SERVER_URL",
    default="http://127.0.0.1:8000",
)
reconstruction_server_timeout_sec = float(
    _first_non_empty_env("RECONSTRUCTION_SERVER_TIMEOUT_SEC", default="10")
)
