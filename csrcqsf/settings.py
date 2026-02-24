
from urllib.parse import quote_plus
import aiohttp
import os
import anyio
import sys
from bfrcommon.file import mkdir
from bfrcommon.settings import Settings
from pydantic import BaseModel
minio_bucket = 'bfr-ai-files'
temp_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp')
brisconfig_url = os.environ.get("brisconfig_url") or "10.144.145.6:10001"
sgo_url = 'https://sgo.csrcqsf.com/uc/sfsso/authByAccount?tenantId=1463844437338755072'

model_dir = '/opt/models' if sys.platform.startswith(
    'win') is False else 'D:\\models'

mkdir(temp_dir)
mkdir(model_dir)


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

SAM_MODEL = os.path.join(model_dir, 'sam_vit_h_4b8939.pth')
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
    milvus_url: str = 'http://10.144.145.4:19530'
    minio_url: str = '10.144.145.6:9000'
    sgo_mysql_url: str = '10.144.145.4'
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
        #self.milvus_url = data.milvus_url
        #self.minio_url = data.minio_url
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
        return f"postgresql+psycopg2://{self.pg.user_name}:{quote_plus(self.pg.password)}@{self.pg.url}:{self.pg.port}/zcsf"

    def get_async_pg_dsn(self):
        return f"postgresql+asyncpg://{self.pg.user_name}:{quote_plus(self.pg.password)}@10.144.145.6:{self.pg.port}/zcsf"
    

    def get_sgo_dsn(self):
        #return f"mysql+asyncmy://{self.sgo_mysql_username}:{self.sgo_mysql_password}@{self.sgo_mysql_url}:{self.sgo_mysql_port}/mdpdb"
        return f"mysql+asyncmy://{self.sgo_mysql_username}:{self.sgo_mysql_password}@10.144.145.4:{self.sgo_mysql_port}/mdpdb"


settings_path = os.path.join(os.path.dirname(
    __file__), "./settings_schema.json")

ai_settings = AISettings()
ai_settings.register_config(
    brisconfig_url, settings_path, "zcsf-ai", "zcsf-ai")

print(ai_settings.get_sgo_dsn())