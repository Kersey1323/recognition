
from urllib.parse import quote_plus
import aiohttp
import os
import anyio
import sys
from bfrcommon.file import mkdir
from bfrcommon.settings import Settings
from pydantic import BaseModel
from dotenv import load_dotenv

# 加载环境变量
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

# 从环境变量读取配置
minio_bucket = os.getenv('MINIO_BUCKET', 'bfr-ai-files')
minio_reconstruction_video_bucket = os.getenv(
    'MINIO_RECONSTRUCTION_VIDEO_BUCKET',
    'bfr-3d-videos'
)
minio_reconstruction_file_bucket = os.getenv(
    'MINIO_RECONSTRUCTION_FILE_BUCKET',
    'bfr-reconstruction-files'
)
minio_search_history_bucket = os.getenv(
    'MINIO_SEARCH_HISTORY_BUCKET',
    'bfr-search-history-files'
)
minio_endpoint = os.getenv('MINIO_ENDPOINT', '192.168.100.2:9000')
minio_access_key = os.getenv('MINIO_ACCESS_KEY', 'root')
minio_secret_key = os.getenv('MINIO_SECRET_KEY', 'REMOVED_CREDENTIAL')
minio_secure = _env_bool('MINIO_SECURE', False)
temp_dir = os.getenv('TEMP_DIR', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp'))
brisconfig_url = os.getenv("brisconfig_url") or os.getenv("BASIS_API_GRPC_URL", "10.144.145.6:10001")
sgo_url = os.getenv('SGO_URL', 'https://sgo.csrcqsf.com/uc/sfsso/authByAccount?tenantId=1463844437338755072')
model_dir = os.getenv('MODEL_DIR', '/home/ubuntu/CV/models' if not sys.platform.startswith('win') else 'D:\\models')
pg_database = _first_non_empty_env("PG_DATABASE", default="zcsf")
sgo_mysql_database = _first_non_empty_env("SGO_MYSQL_DATABASE", default="mdpdb")


def _resolve_model_path(path: str | None) -> str:
    if path is None or path.strip() == "":
        return ""
    raw_path = path.strip()
    if os.path.isabs(raw_path):
        return raw_path
    return os.path.join(model_dir, raw_path)


def resolve_model_path(path: str | None) -> str:
    return _resolve_model_path(path)


sam3_model_path = resolve_model_path(os.getenv('SAM3_MODEL_PATH', 'sam3'))


# mkdir(temp_dir)
# mkdir(model_dir)


async def download_file(url, file_path):
    timeout = aiohttp.ClientTimeout(total=10000, sock_connect=3)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            # 检查响应状态码
            if response.status == 200:
                # 以二进制写入模式打开文件
                async with await anyio.open_file(file_path,  'wb') as file:
                    # 循环读取响应内容并写入文件
                    while True:
                        chunk = await response.content.read(8192)
                        if not chunk:
                            break
                        await file.write(chunk)
            else:
                print(f"下载失败，状态码: {response.status}")

SAM_MODEL = resolve_model_path(
    os.getenv('SAM_MODEL_PATH', 'sam_vit_h_4b8939/sam_vit_h_4b8939.pth')
)

obj_model_path = os.path.join(model_dir, 'yolo_obj_det.onnx')
edge_model_path = os.path.join(model_dir,'yolo_edge_det.onnx')
cls_model_path = os.path.join(model_dir,'paddle_cls_det.onnx')

async def make_sure_models():
    print('检查需要的model是否存在,如果不存在则自动下载')
    if os.path.exists(SAM_MODEL) == False:
        await download_file('https://bfr-assets.oss-cn-chengdu.aliyuncs.com/models/sam_vit_h_4b8939.pth', SAM_MODEL)
    if os.path.exists(obj_model_path) == False:
        await download_file('https://bfr-assets.oss-cn-chengdu.aliyuncs.com/ocr_models/yolo_obj_det.onnx',obj_model_path)
    if os.path.exists(edge_model_path) == False:
        await download_file('https://bfr-assets.oss-cn-chengdu.aliyuncs.com/ocr_models/yolo_edge_det.onnx',edge_model_path)
    if os.path.exists(cls_model_path) == False :
        await download_file('https://bfr-assets.oss-cn-chengdu.aliyuncs.com/ocr_models/paddle_cls_det.onnx',cls_model_path)





class AISettings(Settings):
    # ocr_url: str = 'http://192.168.100.8:55555'
    deepseek_url: str = ''
    api_key: str = ''
    neo4j_url = ''
    neo4j_outer_url: str = ''
    llm_model_name: str = ''
    embeddings_model_name: str = ''
    milvus_url: str = 'http://192.168.100.12:19530'
    minio_url: str = '192.168.100.2:9000'
    sgo_mysql_url: str = '192.168.100.12'
    sgo_mysql_port: str = '33306'
    sgo_mysql_password: str = 'REMOVED_CREDENTIAL'
    sgo_mysql_username: str = 'root'
    basis_api_grpc_url : str = '10.144.145.6:8701'
    search_use_vechile: bool = False

    def parse_config(self, response):
        data = self.parse_raw(response.formData)
        self.basis_api_grpc_url = data.basis_api_grpc_url
        self.deepseek_url = data.deepseek_url
        self.api_key = data.api_key
        #self.neo4j_url = data.neo4j_url
        self.neo4j_outer_url = data.neo4j_outer_url
        self.llm_model_name = data.llm_model_name
        self.embeddings_model_name = data.embeddings_model_name
        # self.milvus_url = data.milvus_url
        # self.minio_url = data.minio_url
        #self.sgo_mysql_url = data.sgo_mysql_url
        self.sgo_mysql_port = data.sgo_mysql_port
        self.sgo_mysql_password = data.sgo_mysql_password
        self.sgo_mysql_username = data.sgo_mysql_username
        self.search_use_vechile = data.search_use_vechile

    def get_neo4j_uri(self):
        return f"bolt://{self.neo4j_url}"

    def get_neo4j_outer_uri(self):
        return f"bolt://{self.neo4j_outer_url}"

    def get_pg_dsn(self):
        return f"postgresql+psycopg2://{self.pg.user_name}:{quote_plus(self.pg.password)}@{self.pg.url}:{self.pg.port}/{pg_database}"

    def get_async_pg_dsn(self):
        return f"postgresql+asyncpg://{self.pg.user_name}:{quote_plus(self.pg.password)}@{self.pg.url}:{self.pg.port}/{pg_database}"
    

    def get_sgo_dsn(self):
        return (
            f"mysql+asyncmy://{self.sgo_mysql_username}:{self.sgo_mysql_password}"
            f"@{self.sgo_mysql_url}:{self.sgo_mysql_port}/{sgo_mysql_database}"
        )


def _apply_runtime_connection_overrides(settings: AISettings) -> None:
    settings.minio_url = minio_endpoint
    settings.pg.url = _first_non_empty_env("PG_HOST", default=settings.pg.url)
    settings.pg.port = _first_non_empty_env("PG_PORT", default=settings.pg.port)
    settings.pg.user_name = _first_non_empty_env("PG_USER", default=settings.pg.user_name)
    settings.pg.password = _first_non_empty_env("PG_PASSWORD", default=settings.pg.password)
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
    settings.sgo_mysql_password = _first_non_empty_env(
        "SGO_MYSQL_PASSWORD",
        default=settings.sgo_mysql_password,
    )
    settings.basis_api_grpc_url = _first_non_empty_env(
        "BASIS_API_GRPC_URL",
        default=settings.basis_api_grpc_url,
    )


settings_path = os.path.join(os.path.dirname(
    __file__), "./settings_schema.json")

ai_settings = AISettings()
# ai_settings.register_config(
#     brisconfig_url, settings_path, "zcsf-ai", "zcsf-ai")

_apply_runtime_connection_overrides(ai_settings)
