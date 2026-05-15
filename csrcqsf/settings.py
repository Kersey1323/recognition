from urllib.parse import quote_plus
import urllib.parse
import aiohttp
import anyio
import os
import sys

from bfrcommon.settings import Settings
from dotenv import load_dotenv
import urllib

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


def _any_explicit_env(*names: str) -> bool:
    return any(env_is_explicit(name) for name in names)


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
    ) or _all_explicit_env(
        "PG_HOST",
        "PG_PORT",
        "PG_USER",
        "PG_PASSWORD",
    )


def minio_env_configured() -> bool:
    return _all_explicit_env(
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
    )


def milvus_env_configured() -> bool:
    return env_is_explicit("MILVUS_URL") or _all_explicit_env(
        "MILVUS_HOST",
        "MILVUS_PORT",
    )


def redis_env_configured() -> bool:
    return _any_explicit_env(
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
    ) or _all_explicit_env(
        "REDIS_HOST",
        "REDIS_PORT",
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
sgo_url = os.getenv(
    "SGO_URL",
    "https://sgo.csrcqsf.com/uc/sfsso/authByAccount?tenantId=1463844437338755072",
)
model_dir = os.getenv(
    "MODEL_DIR"

)
main_db_database = _first_explicit_then_non_empty_env(
    "MAIN_DB_DATABASE",
    "PG_DATABASE",
    default="coronavirusdb",
)
sgo_mysql_database = _first_explicit_then_non_empty_env(
    "SGO_MYSQL_DATABASE",
    default="mdpdb",
)


def _resolve_model_path(path: str | None) -> str:
    if path is None or path.strip() == "":
        return ""
    raw_path = path.strip()
    if os.path.isabs(raw_path):
        return raw_path
    return os.path.join(model_dir, raw_path)


def resolve_model_path(path: str | None) -> str:
    return _resolve_model_path(path)


sam3_model_path = resolve_model_path(os.getenv("SAM3_MODEL_PATH", "sam3"))


async def download_file(url, file_path):
    timeout = aiohttp.ClientTimeout(total=10000, sock_connect=3)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            if response.status == 200:
                async with await anyio.open_file(file_path, "wb") as file:
                    while True:
                        chunk = await response.content.read(8192)
                        if not chunk:
                            break
                        await file.write(chunk)
            else:
                print(f"下载失败，状态码: {response.status}")


SAM_MODEL = resolve_model_path(
    os.getenv("SAM_MODEL_PATH", "sam_vit_h_4b8939/sam_vit_h_4b8939.pth")
)

obj_model_path = os.path.join(model_dir, "yolo_obj_det.onnx")
edge_model_path = os.path.join(model_dir, "yolo_edge_det.onnx")
cls_model_path = os.path.join(model_dir, "paddle_cls_det.onnx")


# async def make_sure_models():
#     print("检查需要的model是否存在,如果不存在则自动下载")
#     if os.path.exists(SAM_MODEL) is False:
#         await download_file(
#             "https://bfr-assets.oss-cn-chengdu.aliyuncs.com/models/sam_vit_h_4b8939.pth",
#             SAM_MODEL,
#         )
#     if os.path.exists(obj_model_path) is False:
#         await download_file(
#             "https://bfr-assets.oss-cn-chengdu.aliyuncs.com/ocr_models/yolo_obj_det.onnx",
#             obj_model_path,
#         )
#     if os.path.exists(edge_model_path) is False:
#         await download_file(
#             "https://bfr-assets.oss-cn-chengdu.aliyuncs.com/ocr_models/yolo_edge_det.onnx",
#             edge_model_path,
#         )
#     if os.path.exists(cls_model_path) is False:
#         await download_file(
#             "https://bfr-assets.oss-cn-chengdu.aliyuncs.com/ocr_models/paddle_cls_det.onnx",
#             cls_model_path,
#         )


class AISettings(Settings):
    milvus_url: str = "http://192.168.100.12:19530"
    sgo_mysql_url: str = "192.168.100.12"
    sgo_mysql_port: str = "33306"
    sgo_mysql_password: str = "REMOVED_CREDENTIAL"
    sgo_mysql_username: str = "root"
    # basis 平台 gRPC 地址，用于文件解析结果导出后向外部平台发送文件任务通知。
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
        return (
            f"mysql+asyncmy://{self.sgo_mysql_username}:{self.sgo_mysql_password}"
            f"@{self.sgo_mysql_url}:{self.sgo_mysql_port}/{sgo_mysql_database}"
        )


def _apply_runtime_connection_overrides(settings: AISettings) -> None:
    settings.mysql.url = _first_explicit_then_non_empty_env(
        "MAIN_DB_HOST",
        "PG_HOST",
        default=settings.mysql.url,
    )
    settings.mysql.port = _first_explicit_then_non_empty_env(
        "MAIN_DB_PORT",
        "PG_PORT",
        default=settings.mysql.port,
    )
    settings.mysql.user_name = _first_explicit_then_non_empty_env(
        "MAIN_DB_USER",
        "PG_USER",
        default=settings.mysql.user_name,
    )
    settings.mysql.password = _first_explicit_then_non_empty_env(
        "MAIN_DB_PASSWORD",
        "PG_PASSWORD",
        default=settings.mysql.password,
    )
    settings.milvus_url = _build_service_url(
        explicit_url=_first_non_empty_env("MILVUS_URL"),
        host=_first_non_empty_env("MILVUS_HOST"),
        port=_first_non_empty_env("MILVUS_PORT"),
        default_url=settings.milvus_url,
    )
    settings.sgo_mysql_url = _first_non_empty_env(
        "SGO_MYSQL_HOST",
        "SGO_MYSQL_URL",
        default=settings.sgo_mysql_url,
    )
    settings.sgo_mysql_port = _first_non_empty_env(
        "SGO_MYSQL_PORT",
        default=settings.sgo_mysql_port,
    )
    settings.sgo_mysql_username = _first_non_empty_env(
        "SGO_MYSQL_USER",
        "SGO_MYSQL_USERNAME",
        default=settings.sgo_mysql_username,
    )
    settings.sgo_mysql_password = urllib.parse.quote_plus(_first_non_empty_env(
        "SGO_MYSQL_PASSWORD",
        default=settings.sgo_mysql_password,
    ))
    settings.basis_api_grpc_url = _first_non_empty_env(
        "BASIS_API_GRPC_URL",
        default=settings.basis_api_grpc_url,
    )


ai_settings = AISettings()
_apply_runtime_connection_overrides(ai_settings)
