from functools import lru_cache

from pymilvus import MilvusClient
#from pymilvus import AsyncMilvusClient
from csrcqsf.core.settings import ai_settings


@lru_cache(maxsize=1)
def get_milvus_client() -> MilvusClient:
    return MilvusClient(uri=ai_settings.milvus_url)


class _LazyMilvusClient:
    def __getattr__(self, name: str):
        return getattr(get_milvus_client(), name)


milvus_client = _LazyMilvusClient()
