from pymilvus import MilvusClient
#from pymilvus import AsyncMilvusClient
from csrcqsf.settings import ai_settings

milvus_client = MilvusClient(
    uri=ai_settings.milvus_url
)
