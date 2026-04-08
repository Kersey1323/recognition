
from pydantic import BaseModel
from csrcqsf.biz.railwayparts.parts import RailwayPartsManager
from csrcqsf.data.milvus import milvus_client
from pymilvus import MilvusClient, DataType
from csrcqsf.biz.railwayparts.milvus import FeaturesIndex, ImageIndex, MilvusManager
from typing import Any
from bfrcommon.snowflake import get_id
from csrcqsf.data.pg import SessionLocal
from csrcqsf.models.item import Items
from pymilvus.client.embedding_list import EmbeddingList
schema = MilvusClient.create_schema(
    enable_dynamic_field=True,
    auto_id=False
)

collection_name = 'feature_new_index_4'


def create_index():
    schema = MilvusClient.create_schema(
        enable_dynamic_field=True,
        auto_id=False
    )
    schema.add_field(
        field_name="id", datatype=DataType.INT64, is_primary=True)

    schema.add_field(field_name="item_id",
                     datatype=DataType.INT64,  is_primary=False)

    schema.add_field(field_name="item_name",
                     datatype=DataType.VARCHAR, max_length=2000)

    schema.add_field(field_name='feature',
                     datatype=DataType.VARCHAR, max_length=2000)

    schema.add_field(field_name="feature_vector",
                     datatype=DataType.FLOAT_VECTOR, dim=512, mmap_enabled=True)
    schema.add_field(field_name="old_feature_vector",
                     datatype=DataType.FLOAT_VECTOR, dim=512, mmap_enabled=True)

    index_params = milvus_client.prepare_index_params()

    index_params.add_index(
        field_name="feature_vector",
        index_type="HNSW",
        metric_type="IP",
        params={
            "M": 64,  # Maximum number of neighbors each node can connect to in the graph
            # Number of candidate neighbors considered for connection during index construction
            "efConstruction": 100
        }  # Index building params

    )
    index_params.add_index(
        field_name="old_feature_vector",
        index_type="HNSW",
        metric_type="IP",
        params={
            "M": 64,  # Maximum number of neighbors each node can connect to in the graph
            # Number of candidate neighbors considered for connection during index construction
            "efConstruction": 100
        }  # Index building params

    )
    milvus_client.drop_collection(collection_name)
    milvus_client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params
    )


class NewFeatureIndex(BaseModel):
    id: int
    item_id: int
    item_name: str
    feature: str
    feature_vector: Any
    old_feature_vector: Any


async def sync_data():
    index_list = await MilvusManager.list_item_index()

    async with SessionLocal() as session:
        item_id_list = [k for k, _ in index_list.items()]
        item_dict: dict[int, Items] = {}
        async for item in Items.get_item_by_id_list(session, item_id_list):
            item_dict[item.id] = item

    for _, index in index_list.items():
        for feature in index.features:
            tensor = await MilvusManager.embedding_encode(feature.feature)
            new_index = NewFeatureIndex(
                id=get_id(),
                item_id=index.item_id,
                item_name=item_dict[index.item_id].item_name,
                feature=feature.feature,
                feature_vector=tensor,
                old_feature_vector=feature.feature_vector,
            )
            
            milvus_client.insert(
                collection_name, new_index.dict()
            )


async def search(feature_list: list[str]):
    query_vector_feature = EmbeddingList()
    for feature in feature_list:
        tensor = await MilvusManager.embedding_encode(feature)
    
        query_vector_feature.add(tensor)
    res = milvus_client.search(
        collection_name='PARTS_INDEX',
        anns_field="features[feature_vector]",
        data=[query_vector_feature],
        limit=3,
        search_params={"metric_type": "MAX_SIM_IP"},
        output_fields=["item_id", "features[feature]"]
    )
    print(res)

    res2 = milvus_client.search(
        collection_name=collection_name,
        anns_field="old_feature_vector",
        data=[tensor],
        limit=3,
        search_params={"metric_type": "IP"},
        output_fields=["item_name", "feature"]
    )

    print(res2)


# from anyio import run
# create_index()
# run(sync_data)

search(['500568青岛鸿裕吉工贸有限公司','青岛鸿裕吉工贸有限公司','HX-03-L'])